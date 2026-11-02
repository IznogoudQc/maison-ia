"""Chronique illustrée : chaque semaine, l'IA raconte la semaine de la famille dans une page HTML avec captures.

Pendant la semaine, aux moments marquants (fête, visite, bordée de neige, projet réussi, naissance...) et en
fin de journée, le moteur demande une capture d'écran : main.py photographie la carte et la confie à la
chronique. Le lundi matin, la semaine écoulée (journal + captures) part à l'IA, qui écrit un titre et des
paragraphes, chacun illustré au besoin. La page est écrite dans le dossier « chroniques » à côté de la
sauvegarde, avec un sommaire (index.html) ; la touche K ouvre la dernière.
"""

from __future__ import annotations

import html
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from llm.chronicle_prompts import ChronicleText, Paragraph, build_chronicle_request, validate_chronicle
from sim.events import Event

if TYPE_CHECKING:
    from sim.engine import Engine

DAY = 24 * 60
WEEK = 7 * DAY
WRITE_HOUR = 6
MAX_SHOTS = 6                 # captures par semaine
SHOT_GAP = 180                # minutes de jeu entre deux captures
EVENING_SHOT = 18 * 60 + 30   # une capture en fin de journée, s'il n'y en a pas eu
MAX_EVENTS = 70
SHOT_KINDS = ("fete", "visite", "neige", "fete_saison", "projet_reussi", "projet_mois", "naissance", "piece_batie",
              "personnalite", "anniversaire", "rumeur_decouverte", "achat_objet", "deces", "embauche", "diplome")
SKIP_CATEGORIES = ("action",)     # trop de routine pour la chronique


class Snapshot(BaseModel):
    file: str
    caption: str
    minute: int


class Page(BaseModel):
    week: int
    title: str
    file: str


class Chronicle:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.out_dir: Path | None = None     # fourni par main.py (à côté de la sauvegarde) ; None : pas de chronique
        self.snapshots: list[Snapshot] = []
        self.pages: list[Page] = []
        self.last_week = engine.clock.day // 7
        self.wanted: str | None = None       # légende de la capture demandée
        self.pending: tuple[Future, int, list[Snapshot]] | None = None
        for kind in SHOT_KINDS:
            engine.bus.subscribe(kind, self.on_event)

    # ------------------------------------------------------------------ captures

    def on_event(self, event: Event) -> None:
        text = event.data.get("text") or event.data.get("title") or event.kind
        if self._can_shoot(event.minute):
            self.wanted = str(text)

    def _can_shoot(self, minute: int) -> bool:
        if self.out_dir is None:
            return False
        week = minute // WEEK
        mine = [s for s in self.snapshots if s.minute // WEEK == week]
        return len(mine) < MAX_SHOTS and (not mine or minute - mine[-1].minute >= SHOT_GAP)

    def snapshot_request(self) -> str | None:
        """Légende de la capture à prendre maintenant (main.py la prend), ou None."""
        return self.wanted

    def add_snapshot(self, file: str, caption: str) -> None:
        self.snapshots.append(Snapshot(file=file, caption=caption, minute=self.engine.clock.total_minutes))
        self.snapshots = self.snapshots[-3 * MAX_SHOTS:]
        self.wanted = None

    def next_shot_name(self) -> str:
        return f"semaine_{self.engine.clock.day // 7 + 1}_{self.engine.clock.total_minutes}.png"

    # ------------------------------------------------------------------ chaque minute

    def update(self) -> None:
        engine = self.engine
        clock = engine.clock
        if self.out_dir is None:
            return
        day_shots = [s for s in self.snapshots if s.minute // DAY == clock.day]
        if clock.minute_of_day >= EVENING_SHOT and not day_shots and self.wanted is None \
                and self._can_shoot(clock.total_minutes):
            self.wanted = f"Fin de journée, {engine.calendar.label(clock.day)}"
        week = clock.day // 7
        if week > self.last_week and clock.minute_of_day >= WRITE_HOUR * 60 and self.pending is None:
            done, self.last_week = self.last_week, week
            self.write_week(done)

    def week_label(self, week: int) -> str:
        return f"semaine du {self.engine.calendar.label(week * 7)}"

    def week_events(self, week: int) -> list[str]:
        lines = []
        for entry in self.engine.history.entries:
            if entry.day // 7 != week or entry.category in SKIP_CATEGORIES:
                continue
            text = f"{['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche'][entry.day % 7]} : {entry.title}"
            if entry.category == "conversation" and entry.lines:
                text += " — " + " / ".join(entry.lines[:2])
            lines.append(text[:240])
        return lines[-MAX_EVENTS:]

    def write_week(self, week: int) -> None:
        engine = self.engine
        events = self.week_events(week)
        shots = [s for s in self.snapshots if s.minute // WEEK == week]
        if not events and not shots:
            return
        fallback = self._fallback(week, events, shots)
        if engine.llm is None:
            self._publish(week, fallback, shots)
            return
        request = build_chronicle_request(engine.agents, self.week_label(week), events,
                                          [s.caption for s in shots], engine.config.llm.max_tokens)
        future = engine.llm.try_submit(request, ChronicleText, fallback, lambda t: validate_chronicle(t, len(shots)))
        if future is None:
            self._publish(week, fallback, shots)
        else:
            self.pending = (future, week, shots)

    def _fallback(self, week: int, events: list[str], shots: list[Snapshot]) -> ChronicleText:
        """Sans IA : les faits de la semaine, regroupés par jour, une capture par paragraphe."""
        by_day: dict[str, list[str]] = {}
        for line in events:
            day, _, text = line.partition(" : ")
            by_day.setdefault(day, []).append(text)
        paragraphs = [Paragraph(text=f"{day.capitalize()} : " + " ; ".join(items[:8]) + ".",
                                image=i + 1 if i < len(shots) else None)
                      for i, (day, items) in enumerate(by_day.items())]
        while len(paragraphs) < 2:
            paragraphs.append(Paragraph(text="Une semaine tranquille à la maison.",
                                        image=len(paragraphs) + 1 if len(paragraphs) < len(shots) else None))
        return ChronicleText(title=f"La {self.week_label(week)}", paragraphs=paragraphs)

    def poll(self) -> None:
        if self.pending is None or not self.pending[0].done():
            return
        future, week, shots = self.pending
        self.pending = None
        try:
            text = future.result().value
        except Exception:  # erreur inattendue dans le thread
            text = None
        self._publish(week, text or self._fallback(week, self.week_events(week), shots), shots)

    # ------------------------------------------------------------------ page HTML

    def _publish(self, week: int, text: ChronicleText, shots: list[Snapshot]) -> None:
        if self.out_dir is None:
            return
        path = self.write_html(week, text, shots)
        self.pages = [p for p in self.pages if p.week != week] + [Page(week=week, title=text.title, file=path.name)]
        self.write_index()
        self.engine.publish("chronique", week=week + 1, file=str(path),
                            text=f"La chronique de la semaine est prête : « {text.title} » (touche K)")

    def write_html(self, week: int, text: ChronicleText, shots: list[Snapshot]) -> Path:
        assert self.out_dir is not None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        parts = [f"<!doctype html><html lang='fr'><meta charset='utf-8'><title>{html.escape(text.title)}</title>",
                 "<meta name='viewport' content='width=device-width,initial-scale=1'>", STYLE,
                 "<main><p class='kicker'>Chez nous — " + html.escape(self.week_label(week)) + "</p>",
                 f"<h1>{html.escape(text.title)}</h1>"]
        for paragraph in text.paragraphs:
            parts.append("<section>")
            if paragraph.image is not None and paragraph.image <= len(shots):
                shot = shots[paragraph.image - 1]
                parts.append(f"<figure><img src='{html.escape(shot.file)}' alt='{html.escape(shot.caption)}'>"
                             f"<figcaption>{html.escape(shot.caption)}</figcaption></figure>")
            parts.append(f"<p>{html.escape(paragraph.text)}</p></section>")
        parts.append("<p class='back'><a href='index.html'>Toutes les chroniques</a></p></main></html>")
        path = self.out_dir / f"semaine_{week + 1}.html"
        path.write_text("".join(parts), encoding="utf-8")
        return path

    def write_index(self) -> Path:
        assert self.out_dir is not None
        items = "".join(f"<li><a href='{html.escape(p.file)}'>Semaine {p.week + 1} — {html.escape(p.title)}</a></li>"
                        for p in sorted(self.pages, key=lambda p: p.week, reverse=True))
        path = self.out_dir / "index.html"
        path.write_text(f"<!doctype html><html lang='fr'><meta charset='utf-8'><title>Chroniques</title>{STYLE}"
                        f"<main><h1>Les chroniques de la famille</h1><ul>{items}</ul></main></html>",
                        encoding="utf-8")
        return path

    def latest(self) -> Path | None:
        if self.out_dir is None or not self.pages:
            return None
        return self.out_dir / max(self.pages, key=lambda p: p.week).file

    # ------------------------------------------------------------------ sauvegarde

    def to_dict(self) -> dict:
        return {"last_week": self.last_week, "snapshots": [s.model_dump() for s in self.snapshots],
                "pages": [p.model_dump() for p in self.pages]}

    def load_dict(self, data: dict | None) -> None:
        data = data or {}
        self.last_week = int(data.get("last_week", self.engine.clock.day // 7))
        self.snapshots = [Snapshot.model_validate(s) for s in data.get("snapshots", [])]
        self.pages = [Page.model_validate(p) for p in data.get("pages", [])]
        self.pending, self.wanted = None, None


STYLE = ("<style>body{margin:0;background:#f6f1e7;color:#2a2622;font:17px/1.65 Georgia,'Times New Roman',serif}"
         "main{max-width:760px;margin:0 auto;padding:32px 16px 64px}"
         ".kicker{font:600 13px/1.2 'Segoe UI',sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#9a5b2e}"
         "h1{font-size:2.1em;line-height:1.15;margin:.2em 0 .8em}section{margin:0 0 1.4em}"
         "figure{margin:0 0 .8em}img{width:100%;border-radius:6px;box-shadow:0 2px 10px rgba(0,0,0,.18)}"
         "figcaption{font:13px/1.4 'Segoe UI',sans-serif;color:#6f665c;margin-top:.4em}"
         "a{color:#9a5b2e}li{margin:.4em 0}.back{margin-top:2em;font-family:'Segoe UI',sans-serif}</style>")
