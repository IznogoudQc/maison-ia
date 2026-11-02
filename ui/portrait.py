"""Fiche personnage (touche P) : caractère, humeur et pourquoi, avis sur chacun ; M : flux de mémoire.

Tab ou flèches gauche/droite : personne suivante ; M : souvenirs et réflexions ; P ou Échap : fermer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from agents.actions import ACTIONS
from sim.food import FOODS
from sim.mind import REFLECT_THRESHOLD
from ui import theme
from ui.dialogue_box import wrap_text

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

GOOD, BAD, NOTE = (140, 210, 120), (235, 120, 110), (200, 190, 150)
THOUGHT = (190, 160, 240)   # réflexions dans le flux de mémoire
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


def career_rows(engine: Engine, agent: Agent) -> list[Row]:
    """Travail et études : emploi, employeur, satisfaction, offre, diplômes, faits marquants."""
    lines = engine.careers.lines(agent)
    if not lines:
        return []
    rows: list[Row] = [("", theme.TEXT), ("Travail et études", HEADER), (lines[0], theme.TEXT)]
    return rows + [(line, NOTE if line.startswith("Jour ") else theme.TEXT_DIM) for line in lines[1:]]


def project_rows(engine: Engine, agent: Agent) -> list[Row]:
    """Projet de vie : aspiration, mois, semaine, geste du jour, étapes marquantes."""
    if agent.persona.stage == "bebe":
        return []
    lines = engine.projects.lines(agent)
    rows: list[Row] = [("", theme.TEXT), ("Projet de vie", HEADER), (lines[0], theme.ACCENT)]
    return rows + [(line, NOTE if "réussi" in line or "accompli" in line else theme.TEXT_DIM) for line in lines[1:]]


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
        self.memory_view = False   # M : flux de mémoire au lieu de la fiche

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
        elif key == pygame.K_m:
            self.memory_view = not self.memory_view
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
        if self.memory_view:
            self._draw_memory(surface, panel, agent, x, top, column)
            return
        # Colonne de gauche : caractère puis humeur
        y = top
        rows = (character_rows(agent) + career_rows(self.engine, agent) + project_rows(self.engine, agent)
                + [("", theme.TEXT)] + mood_rows(self.engine, agent))
        for text, color in rows:
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
        help_text = "Tab : personne suivante   M : flux de mémoire   P : fermer"
        surface.blit(small.render(help_text, True, theme.TEXT_DIM), (x, panel.bottom - 26))

    @staticmethod
    def _bar(surface: pygame.Surface, x: int, y: int, label: str, value: float, color) -> None:
        surface.blit(theme.font(11).render(label, True, theme.TEXT_DIM), (x, y - 2))
        bar = pygame.Rect(x + 58, y + 2, 90, 7)
        pygame.draw.rect(surface, (60, 60, 70), bar, border_radius=3)
        pygame.draw.rect(surface, color, (bar.x, bar.y, round(bar.width * value / 100), bar.height), border_radius=3)

    def _draw_memory(self, surface: pygame.Surface, panel: pygame.Rect, agent: Agent, x: int, top: int,
                     column: int) -> None:
        """Flux de mémoire : chaque souvenir avec son importance, les réflexions, ce que l'IA a retenu."""
        font, small = theme.font(13), theme.font(12)
        memory = agent.memory
        surface.blit(font.render("Flux de mémoire (du plus récent au plus ancien)", True, HEADER), (x, top))
        y = top + 22
        for event in reversed(memory.all_events()):
            if y > panel.bottom - 46:
                break
            when = f"J{event.minute // (24 * 60) + 1} {event.time}"
            surface.blit(small.render(when, True, theme.TEXT_DIM), (x, y + 1))
            bar = pygame.Rect(x + 70, y + 5, 40, 6)
            pygame.draw.rect(surface, (60, 60, 70), bar, border_radius=3)
            color = BAD if event.importance >= 8 else HEADER if event.importance >= 5 else theme.TEXT_DIM
            pygame.draw.rect(surface, color, (bar.x, bar.y, round(bar.width * event.importance / 10), bar.height),
                             border_radius=3)
            text_color = THOUGHT if event.kind == "reflection" else theme.TEXT
            line = wrap_text(event.text, small, column - 120)[0]
            surface.blit(small.render(line, True, text_color), (x + 118, y))
            y += 17
        rx, y = x + column + 16, top
        surface.blit(font.render("Retenus pour sa dernière demande à l'IA", True, HEADER), (rx, y))
        y += 22
        recalled = self.engine.last_recall.get(agent.id, [])
        for event in recalled or []:
            for line in wrap_text(f"• {event.text}", small, column)[:2]:
                surface.blit(small.render(line, True, THOUGHT if event.kind == "reflection" else theme.TEXT),
                             (rx, y))
                y += 15
        if not recalled:
            surface.blit(small.render("(pas encore de demande depuis le chargement)", True, theme.TEXT_DIM), (rx, y))
            y += 15
        y += 12
        surface.blit(font.render("Constats en tête", True, HEADER), (rx, y))
        y += 22
        for belief in reversed(memory.beliefs):
            for line in wrap_text(f"{belief.importance}/10  {belief.text}", small, column)[:2]:
                surface.blit(small.render(line, True, THOUGHT), (rx, y))
                y += 15
        y += 12
        charge = min(memory.importance_since_reflection, REFLECT_THRESHOLD)
        surface.blit(small.render(f"Importance accumulée depuis la dernière réflexion : {charge}/{REFLECT_THRESHOLD}",
                                  True, theme.TEXT_DIM), (rx, y))
        help_text = "Tab : personne suivante   M : revenir à la fiche   P : fermer"
        surface.blit(small.render(help_text, True, theme.TEXT_DIM), (x, panel.bottom - 26))
