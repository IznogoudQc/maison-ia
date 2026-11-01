"""Fiche personnage (touche P) : caractère, humeur et pourquoi, avis sur chacun.

Tab ou flèches gauche/droite : personne suivante ; P ou Échap : fermer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from agents.actions import ACTIONS
from sim.food import FOODS
from ui import theme
from ui.dialogue_box import wrap_text

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

GOOD, BAD, NOTE = (140, 210, 120), (235, 120, 110), (200, 190, 150)
HEADER = (235, 200, 120)
Row = tuple[str, tuple[int, int, int]]


def character_rows(agent: Agent) -> list[Row]:
    p = agent.persona
    rows: list[Row] = [("Caractère", HEADER), ("Traits : " + ", ".join(p.traits), theme.TEXT)]
    if p.qualites:
        rows.append(("Qualités : " + ", ".join(p.qualites), GOOD))
    if p.defauts:
        rows.append(("Défauts : " + ", ".join(p.defauts), BAD))
    if p.interests:
        rows.append(("Intérêts : " + ", ".join(p.interests), theme.TEXT_DIM))
    likes = [FOODS[f].label for f in p.aime if f in FOODS]
    likes += [ACTIONS[a].label.replace("{target}", "").strip() for a in p.favorite_actions if a in ACTIONS]
    if likes:
        rows.append(("Aime : " + ", ".join(likes), theme.TEXT_DIM))
    return rows


def mood_rows(engine: Engine, agent: Agent) -> list[Row]:
    rows: list[Row] = [(f"Humeur : {agent.mood}", HEADER)]
    portraits = engine.portraits
    feeling = portraits.feeling(agent)
    if feeling:
        rows.append((f"« {feeling} »", theme.ACCENT))
    elif portraits.thinking(agent):
        rows.append(("(l'IA met des mots sur son ressenti…)", theme.TEXT_DIM))
    causes = portraits.causes(agent)
    if not causes:
        rows.append(("Rien de spécial : une journée ordinaire.", theme.TEXT_DIM))
    for text, sign in causes:
        mark, color = ("+", GOOD) if sign > 0 else ("−", BAD) if sign < 0 else ("•", NOTE)
        rows.append((f"{mark} {text}", color))
    return rows


class PortraitScreen:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.open = False
        self.agent_id: str | None = None

    def people(self) -> list[Agent]:
        return [a for a in self.engine.agents if not a.dead]

    @property
    def agent(self) -> Agent | None:
        return self.engine.agent_by_id(self.agent_id) if self.agent_id else None

    def show(self, agent_id: str | None) -> None:
        """Ouvre la fiche (de la personne sélectionnée, sinon la première) ou la ferme."""
        if self.open:
            self.open = False
            return
        people = self.people()
        if not people:
            return
        chosen = self.engine.agent_by_id(agent_id) if agent_id else None
        self._select(chosen if chosen is not None and not chosen.dead else people[0])
        self.open = True

    def _select(self, agent: Agent) -> None:
        self.agent_id = agent.id
        self.engine.portraits.request(agent)

    def handle_key(self, event: pygame.event.Event) -> bool:
        """Touche pour la fiche ouverte ; True si elle est consommée (le jeu ne la voit pas)."""
        if not self.open:
            return False
        key = event.key
        if key in (pygame.K_ESCAPE, pygame.K_p):
            self.open = False
        elif key in (pygame.K_TAB, pygame.K_RIGHT, pygame.K_LEFT):
            people = self.people()
            if people:
                index = next((i for i, a in enumerate(people) if a.id == self.agent_id), 0)
                step = -1 if key == pygame.K_LEFT else 1
                self._select(people[(index + step) % len(people)])
        return True

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
        title = f"{agent.name}, {agent.persona.age} ans ({agent.persona.role})"
        surface.blit(theme.font(18, bold=True).render(title, True, theme.TEXT), (x + 24, y))
        surface.blit(theme.font(13).render(agent.status_label.capitalize(), True, theme.TEXT_DIM), (x + 24, y + 24))
        top = y + 52
        font = theme.font(13)
        column = (panel.width - 48) // 2
        # Colonne de gauche : caractère puis humeur
        y = top
        for text, color in character_rows(agent) + [("", theme.TEXT)] + mood_rows(self.engine, agent):
            for line in wrap_text(text, font, column) if text else [""]:
                if y > panel.bottom - 44:
                    break
                surface.blit(font.render(line, True, color), (x, y))
                y += 18
        # Colonne de droite : ce qu'il pense des autres
        rx, y = x + column + 16, top
        surface.blit(font.render(f"Ce que {agent.name} pense des autres", True, HEADER), (rx, y))
        y += 22
        small = theme.font(12)
        for opinion in self.engine.portraits.opinions(agent):
            if y > panel.bottom - 70:
                break
            other = opinion.other
            pygame.draw.circle(surface, tuple(other.persona.color), (rx + 5, y + 8), 5)
            surface.blit(theme.font(13, bold=True).render(other.name, True, theme.TEXT), (rx + 14, y))
            surface.blit(small.render(opinion.label, True, theme.TEXT_DIM), (rx + 110, y + 1))
            y += 18
            self._bar(surface, rx + 14, y, "affection", opinion.affection, GOOD)
            self._bar(surface, rx + 14 + column // 2, y, "tension", opinion.tension, BAD)
            y += 14
            for line in wrap_text(opinion.text, font, column - 14):
                surface.blit(font.render(line, True, theme.TEXT), (rx + 14, y))
                y += 17
            if opinion.note:
                for line in wrap_text(f"Dernière impression : « {opinion.note} »", small, column - 14):
                    surface.blit(small.render(line, True, NOTE), (rx + 14, y))
                    y += 15
            y += 8
        help_text = "Tab : personne suivante   P : fermer"
        surface.blit(small.render(help_text, True, theme.TEXT_DIM), (x, panel.bottom - 26))

    @staticmethod
    def _bar(surface: pygame.Surface, x: int, y: int, label: str, value: float, color) -> None:
        surface.blit(theme.font(11).render(label, True, theme.TEXT_DIM), (x, y - 2))
        bar = pygame.Rect(x + 58, y + 2, 90, 7)
        pygame.draw.rect(surface, (60, 60, 70), bar, border_radius=3)
        pygame.draw.rect(surface, color, (bar.x, bar.y, round(bar.width * value / 100), bar.height), border_radius=3)
