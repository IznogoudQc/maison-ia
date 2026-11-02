"""Écran d'entrevue (touche T) : poser une question à la personne sélectionnée, ou lui souffler une idée.

Tab : question ou idée ; Entrée : envoyer ; flèches gauche/droite (champ vide) : personne suivante ; Échap : fermer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ui import theme
from ui.dialogue_box import wrap_text

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

ME, THEM, WHISPER = (140, 190, 240), (235, 235, 240), (190, 160, 240)
MAX_TEXT = 200


class InterviewScreen:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.open = False
        self.agent_id: str | None = None
        self.text = ""
        self.whisper = False
        self._swallow = ""   # la lettre de la touche qui a ouvert l'écran ne doit pas s'écrire

    @property
    def agent(self) -> Agent | None:
        return self.engine.agent_by_id(self.agent_id) if self.agent_id else None

    def people(self) -> list[Agent]:
        return [a for a in self.engine.agents if not a.dead and a.persona.stage != "bebe"]

    def show(self, agent_id: str | None, key_char: str = "t") -> None:
        if self.open:
            self.open = False
            return
        people = self.people()
        if not people:
            return
        chosen = self.engine.agent_by_id(agent_id) if agent_id else None
        self.agent_id = (chosen if chosen in people else people[0]).id
        self.open, self.text, self._swallow = True, "", key_char

    def handle_key(self, event: pygame.event.Event) -> bool:
        """Écran ouvert : il garde tout le clavier (on écrit une question)."""
        if not self.open:
            return False
        key = event.key
        if key == pygame.K_ESCAPE:
            self.open = False
        elif key == pygame.K_TAB:
            self.whisper = not self.whisper
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            agent = self.agent
            if agent is not None and self.text.strip() and self.engine.interviews.ask(agent, self.text, self.whisper):
                self.text = ""
        elif key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
        elif key in (pygame.K_LEFT, pygame.K_RIGHT) and not self.text:
            people = self.people()
            index = next((i for i, a in enumerate(people) if a.id == self.agent_id), 0)
            self.agent_id = people[(index + (1 if key == pygame.K_RIGHT else -1)) % len(people)].id
        return True

    def handle_text(self, text: str) -> None:
        """Caractères tapés (événement TEXTINPUT : accents compris)."""
        if not self.open:
            return
        if self._swallow and text.lower() == self._swallow:
            self._swallow = ""
            return
        self._swallow = ""
        self.text = (self.text + text)[:MAX_TEXT]

    def draw(self, surface: pygame.Surface, area: pygame.Rect) -> None:
        agent = self.agent
        if not self.open or agent is None:
            return
        panel = area.inflate(-32, -32)
        veil = pygame.Surface(panel.size, pygame.SRCALPHA)
        veil.fill((22, 22, 28, 240))
        surface.blit(veil, panel.topleft)
        pygame.draw.rect(surface, theme.PANEL_BORDER, panel, 2, border_radius=6)
        x, y = panel.x + 16, panel.y + 12
        pygame.draw.circle(surface, tuple(agent.persona.color), (x + 8, y + 11), 8)
        title = f"Entrevue avec {agent.name} ({agent.mood})"
        title_font = theme.font(18, bold=True)
        surface.blit(title_font.render(title, True, theme.TEXT), (x + 24, y))
        tx = x + 24 + title_font.size(title)[0] + 30
        for index, label in enumerate(("Question", "Souffler une idée")):
            active = (index == 1) == self.whisper
            image = theme.font(14, bold=active).render(label, True, theme.ACCENT if active else theme.TEXT_DIM)
            surface.blit(image, (tx, y + 3))
            if active:
                pygame.draw.line(surface, theme.ACCENT, (tx, y + 22), (tx + image.get_width(), y + 22), 2)
            tx += image.get_width() + 18
        font, small = theme.font(14), theme.font(12)
        width = panel.width - 40
        rows: list[tuple[str, tuple[int, int, int]]] = []
        for exchange in self.engine.interviews.history(agent.id):
            answer = exchange.answer or "(réfléchit…)"
            if exchange.whisper:
                rows += [(f"Tu lui souffles : {exchange.text}", WHISPER), (f"{agent.name} se dit : {answer}", WHISPER)]
            else:
                rows += [(f"Toi : {exchange.text}", ME), (f"{agent.name} : {answer}", THEM)]
            rows.append(("", THEM))
        if not rows:
            hint = ("Souffle une idée : elle restera en tête, à la personne de décider si elle y donne suite."
                    if self.whisper else "Pose une question : la réponse vient de ses vrais souvenirs et constats.")
            rows = [(hint, theme.TEXT_DIM)]
        lines = [(line, color) for text, color in rows for line in (wrap_text(text, font, width) if text else [""])]
        box = pygame.Rect(x, panel.bottom - 74, width, 32)
        y += 40
        visible = max(1, (box.y - 12 - y) // 19)
        for text, color in lines[-visible:]:
            surface.blit(font.render(text, True, color), (x, y))
            y += 19
        pygame.draw.rect(surface, (40, 40, 50), box, border_radius=4)
        pygame.draw.rect(surface, theme.ACCENT if self.text else theme.PANEL_BORDER, box, 1, border_radius=4)
        caret = "_" if pygame.time.get_ticks() // 500 % 2 else ""
        typed = ("Idée : " if self.whisper else "Question : ") + self.text + caret
        while font.size(typed)[0] > width - 16 and len(typed) > 2:
            typed = "…" + typed[2:]   # on garde la fin de ce qu'on tape
        surface.blit(font.render(typed, True, theme.TEXT), (box.x + 8, box.y + 7))
        help_text = "Entrée : envoyer   Tab : question ou idée   ← → : autre personne   Échap : fermer"
        surface.blit(small.render(help_text, True, theme.TEXT_DIM), (x, panel.bottom - 26))
