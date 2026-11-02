"""Historique persistant de la partie : conversations, actions (et leurs raisons), pensées, événements.

Alimenté par le bus d'événements, sauvegardé avec la partie, affiché par l'écran Journal (touche J)
et exportable en page HTML (la chronique de la famille).
"""

from __future__ import annotations

import html
from pathlib import Path

from pydantic import BaseModel, Field

from sim.clock import DAY_NAMES, MINUTES_PER_DAY, format_hhmm
from sim.events import Event, EventBus

MAX_ENTRIES = 4000
CATEGORIES = {"conversation": "Conversations", "action": "Actions", "pensee": "Pensées", "evenement": "Événements"}
# Actions de routine trop fréquentes pour l'historique (sauf si l'IA a donné une raison)
ROUTINE = {"dormir", "flaner", "partir", "dejeuner", "souper", "cuisiner", "collation", "douche"}
EVENT_KINDS = ("evenement", "achat", "achat_objet", "pret", "pret_retard", "naissance", "deces", "hopital",
               "grossesse", "anniversaire", "plan_maison", "piece_batie", "chantier_debut", "entrepreneur",
               "agrandissement", "projet_bebe", "factures", "frigo_vide", "fin", "conge", "malade",
               "embauche", "promotion", "perte_emploi", "offre_emploi", "etudes", "diplome")


class HistoryEntry(BaseModel):
    minute: int
    category: str
    who: list[str] = Field(default_factory=list)
    title: str
    lines: list[str] = Field(default_factory=list)

    @property
    def day(self) -> int:
        return self.minute // MINUTES_PER_DAY

    def stamp(self) -> str:
        return f"Jour {self.day + 1} ({DAY_NAMES[self.day % 7]}) {format_hhmm(self.minute)}"

    def text(self) -> str:
        return " ".join([self.title, *self.lines]).lower()


class History:
    def __init__(self, bus: EventBus) -> None:
        self.entries: list[HistoryEntry] = []
        for kind in ("dialogue", "decision", "action", "plan", "reflexion", "promesse", "promesse_tenue", "entrevue", "souffle",
                     "promesse_brisee", *EVENT_KINDS):
            bus.subscribe(kind, self.on_event)

    def add(self, entry: HistoryEntry) -> None:
        self.entries.append(entry)
        del self.entries[:-MAX_ENTRIES]

    def on_event(self, event: Event) -> None:
        entry = self._entry(event)
        if entry is not None:
            self.add(entry)

    def _entry(self, event: Event) -> HistoryEntry | None:
        d, kind, minute = event.data, event.kind, event.minute
        if kind == "dialogue":
            lines = [f"{line['speaker']} : {line['text']}" for line in d.get("lines", [])]
            return HistoryEntry(minute=minute, category="conversation", who=list(d.get("participants", [])),
                                title=f"{' et '.join(d.get('participants', []))} ({d.get('room', '')})", lines=lines)
        if kind == "decision" and d.get("reason"):
            return None  # l'action qui suit porte la raison : pas de doublon
        if kind == "action":
            if d.get("action") in ROUTINE and not d.get("reason"):
                return None
            reason = f"« {d['reason']} »" if d.get("reason") else ""
            return HistoryEntry(minute=minute, category="action", who=[d.get("name", "")],
                                title=f"{d.get('name', '')} {d.get('label', '')}", lines=[reason] if reason else [])
        if kind == "plan":
            steps = [f"{format_hhmm(i['minute'])} {i['action']}" + (f" ({i['note']})" if i.get("note") else "")
                     for i in d.get("items", [])]
            what = "refait son plan" if d.get("replan") else "plan du jour"
            return HistoryEntry(minute=minute, category="pensee", who=[d.get("name", "")],
                                title=f"{d.get('name', '')}, {what} : {d.get('intention', '')}", lines=steps)
        if kind in ("entrevue", "souffle"):
            name = d.get("name", "")
            if kind == "entrevue":
                return HistoryEntry(minute=minute, category="conversation", who=[name], title=f"Entrevue avec {name}",
                                    lines=[f"Toi : {d.get('text', '')}", f"{name} : {d.get('answer', '')}"])
            return HistoryEntry(minute=minute, category="pensee", who=[name], title=f"Idée soufflée à {name}",
                                lines=[f"« {d.get('text', '')} »", f"{name} se dit : {d.get('answer', '')}"])
        if kind == "reflexion":
            lines = [f"Question : {q}" for q in d.get("questions", [])]
            evidence = d.get("evidence") or []
            for index, insight in enumerate(d.get("insights", [])):
                lines.append(insight["text"])
                proofs = evidence[index] if index < len(evidence) else []
                lines += [f"   ← {proof}" for proof in proofs[:2]]   # les souvenirs qui le prouvent
            if d.get("deep"):
                lines.append(f"Au fond : {d['deep']}")
            if d.get("goal"):
                lines.append(f"Objectif : {d['goal']}")
            return HistoryEntry(minute=minute, category="pensee", who=[d.get("name", "")],
                                title=f"Réflexion de {d.get('name', '')}", lines=lines)
        if kind.startswith("promesse"):
            label = {"promesse": "Promesse", "promesse_tenue": "Promesse tenue", "promesse_brisee": "Promesse brisée"}
            when = f" ({d['when']})" if d.get("when") else ""
            return HistoryEntry(minute=minute, category="pensee", who=list(d.get("people", [])),
                                title=f"{label[kind]} : {d.get('text', '')}{when}")
        if kind in EVENT_KINDS:
            text = d.get("text") or self._event_text(kind, d)
            who = [d["name"]] if d.get("name") else []
            return HistoryEntry(minute=minute, category="evenement", who=who, title=text)
        return None

    @staticmethod
    def _event_text(kind: str, d: dict) -> str:
        if kind == "deces":
            return f"Décès : {d.get('name')} ({d.get('cause')})"
        if kind == "hopital":
            return f"{d.get('name')} est à l'hôpital"
        if kind == "factures":
            return f"Factures de la semaine : {abs(d.get('amount', 0)):.0f} $"
        if kind == "frigo_vide":
            return "Le frigo est vide"
        if kind == "fin":
            return "La famille n'a pas survécu"
        return kind

    # ------------------------------------------------------------------ requêtes

    def people(self) -> list[str]:
        names: list[str] = []
        for entry in self.entries:
            for name in entry.who:
                if name and name not in names:
                    names.append(name)
        return names

    def filtered(self, category: str | None = None, person: str | None = None,
                 search: str = "") -> list[HistoryEntry]:
        query = search.strip().lower()
        return [e for e in self.entries
                if (category is None or e.category == category)
                and (person is None or person in e.who)
                and (not query or query in e.text())]

    # ------------------------------------------------------------------ sauvegarde, export

    def to_list(self) -> list[dict]:
        return [e.model_dump() for e in self.entries]

    def load_list(self, data: list[dict] | None) -> None:
        self.entries = [HistoryEntry.model_validate(raw) for raw in (data or [])][-MAX_ENTRIES:]

    def export_html(self, path: str | Path, title: str = "Chronique de la famille") -> Path:
        """Toute l'histoire, jour par jour, dans une page autonome à ouvrir dans un navigateur."""
        path = Path(path)
        colors = {"conversation": "#2f6db5", "action": "#4a8a3a", "pensee": "#7a5ab5", "evenement": "#b5562f"}
        parts = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>",
                 "<style>body{font-family:Segoe UI,sans-serif;max-width:820px;margin:2em auto;padding:0 1em;"
                 "background:#faf8f3;color:#222}h1{margin-bottom:.2em}h2{border-bottom:2px solid #ddd;"
                 "padding-top:1em}.e{margin:.5em 0;padding:.4em .7em;border-left:4px solid;background:#fff}"
                 ".t{color:#888;font-size:.85em}.l{margin:.15em 0 0 1em}</style>",
                 f"<h1>{html.escape(title)}</h1><p>{len(self.entries)} moments racontés.</p>"]
        current_day = None
        for entry in self.entries:
            if entry.day != current_day:
                current_day = entry.day
                parts.append(f"<h2>Jour {entry.day + 1} — {DAY_NAMES[entry.day % 7]}</h2>")
            lines = "".join(f"<div class='l'>{html.escape(line)}</div>" for line in entry.lines)
            parts.append(f"<div class='e' style='border-color:{colors.get(entry.category, '#999')}'>"
                         f"<span class='t'>{format_hhmm(entry.minute)} · {CATEGORIES[entry.category]}</span><br>"
                         f"{html.escape(entry.title)}{lines}</div>")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(parts), encoding="utf-8")
        return path
