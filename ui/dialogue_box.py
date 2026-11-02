"""Bulles de dialogue au-dessus des agents et panneau d'historique."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import pygame

from agents.agent import Agent
from sim.events import Event
from ui import theme
from ui.renderer import Renderer

BUBBLE_MAX_WIDTH = 230
MAX_ACTIVE_CONVERSATIONS = 3
NEWS_KINDS = ("evenement", "deces", "hopital", "factures", "frigo_vide", "achat",
              "promesse", "promesse_tenue", "promesse_brisee", "plan_maison", "emplacement_pret", "piece_batie",
              "chantier_debut", "entrepreneur", "projet_bebe", "grossesse", "naissance", "anniversaire",
              "agrandissement", "achat_objet", "pret", "pret_retard", "visite", "fin_visite",
              "fete_prevue", "fete", "fin_fete", "rumeur_decouverte", "neige", "froid", "fete_saison", "projet_mois", "projet_reussi")
MIND_KINDS = ("plan", "reflexion")
THOUGHT = (180, 170, 230)
TOAST_SECONDS = 6.0
MAX_TOASTS = 3
GOOD = (40, 130, 70)
BAD = (160, 50, 50)
NEUTRAL = (70, 70, 110)


def wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Découpe en lignes tenant dans max_width pixels (coupe les mots trop longs)."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        while font.size(word)[0] > max_width and len(word) > 1:
            cut = len(word)
            while cut > 1 and font.size(word[:cut])[0] > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines or [""]


@dataclass
class Conversation:
    lines: list[tuple[str, str]]          # (id d'agent, texte)
    index: int = 0
    elapsed: float = 0.0
    conv_id: int | None = None            # conversation tour par tour (répliques ajoutées au fil de l'eau)
    elapsed_done: bool = False            # dernière réplique déjà montrée une fois


@dataclass
class HistoryEntry:
    time: str
    room: str
    speaker: str
    text: str
    color: tuple[int, int, int]


@dataclass
class DialogueBox:
    renderer: Renderer
    agents: list[Agent]
    line_display_s: float = 3.5
    history_size: int = 300
    show_history: bool = False
    active: list[Conversation] = field(default_factory=list)
    history: deque[HistoryEntry] = field(default_factory=deque)
    scroll: int = 0  # lignes remontées dans l'historique
    toasts: list[list] = field(default_factory=list)  # [texte, couleur, secondes restantes]
    _last_empty_fridge_day: int = -1

    def on_news(self, event: Event) -> None:
        """Bannière en haut de la carte + ligne dans l'historique pour les nouvelles de la famille."""
        data = event.data
        if event.kind == "evenement":
            text, color = data["text"], GOOD if data["good"] else BAD
        elif event.kind == "deces":
            text, color = f"Décès : {data['name']} ({data['cause']})", BAD
        elif event.kind == "hopital":
            text, color = f"Hôpital : {data['name']} y passera quelques jours", BAD
        elif event.kind == "factures":
            text, color = f"Factures de la semaine : {data['amount']:,.0f} $".replace(",", " "), NEUTRAL
        elif event.kind == "frigo_vide":
            day = event.minute // (24 * 60)
            if day == self._last_empty_fridge_day:
                return  # une seule alerte par jour
            self._last_empty_fridge_day = day
            text, color = "Le frigo est vide !", BAD
        elif event.kind in ("achat", "plan_maison", "piece_batie", "chantier_debut", "entrepreneur",
                            "grossesse", "naissance", "anniversaire", "agrandissement", "achat_objet"):
            text, color = data["text"], GOOD
        elif event.kind == "pret":
            text, color = data["text"], GOOD if data["ok"] else BAD
        elif event.kind == "pret_retard":
            text, color = data["text"], BAD
        elif event.kind in ("visite", "fin_visite", "fin_fete"):
            text, color = data["text"], NEUTRAL
        elif event.kind in ("fete_prevue", "fete"):
            text, color = data["text"], GOOD
        elif event.kind in ("rumeur_decouverte", "froid"):
            text, color = data["text"], BAD
        elif event.kind == "neige":
            text, color = data["text"], NEUTRAL
        elif event.kind in ("fete_saison", "projet_mois", "projet_reussi"):
            text, color = data["text"], GOOD
        elif event.kind == "projet_bebe":
            text, color = data["text"], GOOD if data["yes"] else NEUTRAL
        elif event.kind == "emplacement_pret":
            text, color = f"Emplacement dégagé : {data['room']}", GOOD
        elif event.kind == "promesse":
            text, color = f"Promesse : {data['text']} ({data['when']})", NEUTRAL
        elif event.kind == "promesse_tenue":
            text, color = f"Promesse tenue : {data['text']}", GOOD
        elif event.kind == "promesse_brisee":
            who = ", ".join(data["missing"]) or "personne"
            text, color = f"Promesse brisée ({who}) : {data['text']}", BAD
        else:
            return
        self.toasts.append([text, color, TOAST_SECONDS])
        del self.toasts[:-MAX_TOASTS]
        minute = event.minute % (24 * 60)
        self.history.append(HistoryEntry(f"{minute // 60:02d}:{minute % 60:02d}", "Famille", "Nouvelle",
                                         text, color))
        while len(self.history) > self.history_size:
            self.history.popleft()

    def on_mind(self, event: Event) -> None:
        """Plans et réflexions : seulement dans l'historique (H), en italique de pensée."""
        data = event.data
        if event.kind == "plan":
            label = "Nouveau plan" if data.get("replan") else "Plan du jour"
            text = data.get("intention") or ", ".join(i["action"] for i in data.get("items", []))
        else:
            label = "Réflexion"
            text = " ".join(i["text"] for i in data.get("insights", []))
            if data.get("goal"):
                text += f" (objectif : {data['goal']})"
        minute = event.minute % (24 * 60)
        self.history.append(HistoryEntry(f"{minute // 60:02d}:{minute % 60:02d}", label, data["name"],
                                         text, THOUGHT))
        while len(self.history) > self.history_size:
            self.history.popleft()

    def on_line(self, event: Event) -> None:
        """Mode tour par tour : chaque réplique s'ajoute à la file de sa conversation dès qu'elle arrive."""
        data = event.data
        conv = next((c for c in self.active if c.conv_id == data["conv"]), None)
        if conv is None:
            if len(self.active) >= MAX_ACTIVE_CONVERSATIONS:
                self.active.pop(0)
            conv = Conversation([], conv_id=data["conv"])
            self.active.append(conv)
        conv.lines.append((data["agent"], data["text"]))
        agent = next((a for a in self.agents if a.id == data["agent"]), None)
        color = tuple(min(255, c + 70) for c in agent.persona.color) if agent else theme.TEXT
        self.history.append(HistoryEntry(data.get("time", ""), data.get("room", ""), data["speaker"],
                                         data["text"], color))  # type: ignore[arg-type]
        while len(self.history) > self.history_size:
            self.history.popleft()

    def on_dialogue(self, event: Event) -> None:
        if event.data.get("live"):
            return  # répliques déjà affichées une à une par on_line
        by_name = {a.name: a for a in self.agents}
        lines = [(by_name[l["speaker"]].id, l["text"]) for l in event.data["lines"] if l["speaker"] in by_name]
        if not lines:
            return
        if len(self.active) >= MAX_ACTIVE_CONVERSATIONS:
            self.active.pop(0)  # vitesses élevées : on privilégie les conversations récentes
        self.active.append(Conversation(lines))
        for speaker_id, text in lines:
            agent = next(a for a in self.agents if a.id == speaker_id)
            # Couleur éclaircie pour rester lisible sur le fond sombre du panneau
            color = tuple(min(255, c + 70) for c in agent.persona.color)
            self.history.append(HistoryEntry(event.data.get("time", ""), event.data.get("room", ""),
                                             agent.name, text, color))  # type: ignore[arg-type]
        while len(self.history) > self.history_size:
            self.history.popleft()

    def update(self, dt: float) -> None:
        for toast in self.toasts:
            toast[2] -= dt
        self.toasts = [t for t in self.toasts if t[2] > 0]
        for conv in list(self.active):
            conv.elapsed += dt
            if conv.elapsed >= self.line_display_s:
                conv.elapsed = 0.0
                if conv.index + 1 < len(conv.lines):
                    conv.index += 1
                    conv.elapsed_done = False
                elif conv.conv_id is None or conv.elapsed_done:
                    self.active.remove(conv)
                else:
                    conv.elapsed_done = True  # dernière réplique affichée : on attend un peu la suivante

    def toggle_history(self) -> None:
        self.show_history = not self.show_history
        self.scroll = 0

    def scroll_history(self, delta: int) -> None:
        self.scroll = max(0, min(self.scroll + delta, max(0, len(self.history) - 5)))

    # ------------------------------------------------------------------ dessin

    def draw(self, surface: pygame.Surface) -> None:
        for conv in self.active:
            speaker_id, text = conv.lines[conv.index]
            agent = next((a for a in self.agents if a.id == speaker_id), None)
            if agent is not None and agent.is_available:
                self._draw_bubble(surface, agent, text)
        self._draw_toasts(surface)
        if self.show_history:
            self._draw_history(surface)

    def _draw_toasts(self, surface: pygame.Surface) -> None:
        font = theme.font(15, bold=True)
        y = 12
        for text, color, remaining in self.toasts:
            image = font.render(text, True, (250, 250, 250))
            box = image.get_rect().inflate(28, 12)
            box.midtop = (self.renderer.size[0] // 2, y)
            panel = pygame.Surface(box.size, pygame.SRCALPHA)
            alpha = int(225 * min(1.0, remaining / 0.6))  # fondu de sortie
            panel.fill((*color, alpha))
            surface.blit(panel, box.topleft)
            pygame.draw.rect(surface, (250, 250, 250), box, 1, border_radius=4)
            surface.blit(image, image.get_rect(center=box.center))
            y = box.bottom + 6

    def _draw_bubble(self, surface: pygame.Surface, agent: Agent, text: str) -> None:
        font = theme.font(13)
        lines = wrap_text(text, font, BUBBLE_MAX_WIDTH)
        line_h = font.get_linesize()
        width = max(font.size(line)[0] for line in lines) + 16
        height = line_h * len(lines) + 10
        cx, cy = self.renderer.agent_screen_pos(agent)
        if not self.renderer.on_screen((cx, cy), 20):
            return  # personnage hors de la vue (grand terrain)
        rect = pygame.Rect(0, 0, width, height)
        rect.midbottom = (cx, cy - self.renderer.ts // 2 - 16)  # au-dessus de la tête du sprite
        map_rect = pygame.Rect((0, 0), self.renderer.size)
        rect.clamp_ip(map_rect)
        tail_x = max(rect.left + 10, min(cx, rect.right - 10))
        pygame.draw.polygon(surface, (252, 252, 250),
                            [(tail_x - 6, rect.bottom - 1), (tail_x + 6, rect.bottom - 1), (cx, rect.bottom + 8)])
        pygame.draw.rect(surface, (252, 252, 250), rect, border_radius=9)
        pygame.draw.rect(surface, agent.persona.color, rect, 2, border_radius=9)
        for i, line in enumerate(lines):
            surface.blit(font.render(line, True, theme.TEXT_DARK), (rect.x + 8, rect.y + 5 + i * line_h))

    def _draw_history(self, surface: pygame.Surface) -> None:
        map_w, map_h = self.renderer.size
        panel = pygame.Rect(16, 16, map_w - 32, map_h - 32)
        overlay = pygame.Surface(panel.size, pygame.SRCALPHA)
        overlay.fill((24, 24, 30, 232))
        surface.blit(overlay, panel.topleft)
        pygame.draw.rect(surface, theme.PANEL_BORDER, panel, 2, border_radius=6)
        title = theme.font(16, bold=True).render("Historique des dialogues (H pour fermer, molette pour défiler)",
                                                 True, theme.TEXT)
        surface.blit(title, (panel.x + 14, panel.y + 10))

        font = theme.font(13)
        line_h = font.get_linesize()
        text_w = panel.width - 40
        rendered: list[tuple[str, tuple[int, int, int]]] = []
        for entry in self.history:
            prefix = f"[{entry.time} · {entry.room}] {entry.speaker} : "
            for i, line in enumerate(wrap_text(prefix + entry.text, font, text_w)):
                rendered.append((line if i == 0 else "      " + line, entry.color if i == 0 else theme.TEXT))
        if not rendered:
            rendered = [("Aucun dialogue pour l'instant.", theme.TEXT_DIM)]
        visible = (panel.height - 50) // line_h
        end = len(rendered) - self.scroll
        y = panel.y + 40
        for line, color in rendered[max(0, end - visible):end]:
            surface.blit(font.render(line, True, color), (panel.x + 20, y))
            y += line_h
