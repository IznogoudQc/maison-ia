"""Panneau latéral : heure, vitesse, agent sélectionné, contrôles."""

from __future__ import annotations

import pygame

from agents.agent import Agent
from agents.needs import NEED_LABELS
from llm.service import LLMService
from sim.clock import SimClock
from ui import theme

CONTROLS = [
    "Espace : pause / reprise",
    "1-4 : vitesse",
    "Clic : sélectionner un agent",
    "Échap : quitter",
]


class Hud:
    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect

    def draw(self, surface: pygame.Surface, clock: SimClock, speed: float, paused: bool,
             agents: list[Agent], selected: Agent | None, llm: LLMService | None = None,
             llm_label: str = "") -> None:
        pygame.draw.rect(surface, theme.PANEL, self.rect)
        pygame.draw.line(surface, theme.PANEL_BORDER, self.rect.topleft, self.rect.bottomleft, 2)
        x, y = self.rect.x + 14, self.rect.y + 12
        surface.blit(theme.font(20, bold=True).render(clock.label(), True, theme.TEXT), (x, y))
        y += 32
        state = "PAUSE" if paused else f"Vitesse x{speed:g}"
        surface.blit(theme.font(15).render(state, True, theme.ACCENT if paused else theme.TEXT_DIM), (x, y))
        y += 24
        if llm is not None:
            y = self._draw_llm(surface, x, y, llm, llm_label)
        y += 8

        if selected is None:
            y = self._draw_family(surface, x, y, agents)
        else:
            y = self._draw_agent(surface, x, y, selected)

        y = self.rect.bottom - 18 * len(CONTROLS) - 10
        for line in CONTROLS:
            surface.blit(theme.font(13).render(line, True, theme.TEXT_DIM), (x, y))
            y += 18

    def _draw_llm(self, surface: pygame.Surface, x: int, y: int, llm: LLMService, label: str) -> int:
        stats = llm.stats
        lines = [
            f"LLM : {label}",
            f"Appels : {stats.calls}  ({llm.limiter.used()}/{llm.limiter.max_per_minute} cette minute)",
            f"Tokens : {stats.input_tokens:,} entrée / {stats.output_tokens:,} sortie".replace(",", " "),
            f"Échecs : {stats.failures}  —  replis : {stats.fallbacks}",
        ]
        for line in lines:
            surface.blit(theme.font(12).render(_clip(line, 56), True, theme.TEXT_DIM), (x, y))
            y += 16
        return y

    def _draw_family(self, surface: pygame.Surface, x: int, y: int, agents: list[Agent]) -> int:
        surface.blit(theme.font(15, bold=True).render("Famille", True, theme.TEXT), (x, y))
        y += 24
        for agent in agents:
            pygame.draw.circle(surface, agent.persona.color, (x + 7, y + 9), 7)
            text = f"{agent.name} — {agent.status_label}"
            surface.blit(theme.font(13).render(_clip(text, 44), True, theme.TEXT_DIM), (x + 20, y))
            y += 22
        return y

    def _draw_agent(self, surface: pygame.Surface, x: int, y: int, agent: Agent) -> int:
        persona = agent.persona
        pygame.draw.circle(surface, persona.color, (x + 9, y + 12), 9)
        title = f"{persona.name}, {persona.age} ans ({persona.role})"
        surface.blit(theme.font(17, bold=True).render(title, True, theme.TEXT), (x + 24, y))
        y += 28
        for line in (f"Action : {agent.status_label}",
                     f"Humeur : {agent.mood}",
                     f"Pièce : {agent.last_room or '-'}" if not agent.is_away else "Pièce : dehors"):
            surface.blit(theme.font(13).render(_clip(line, 48), True, theme.TEXT), (x, y))
            y += 19
        if agent.action is not None and agent.action.reason:
            surface.blit(theme.font(12).render(_clip(f"« {agent.action.reason} »", 54), True,
                                               theme.TEXT_DIM), (x, y))
            y += 18
        y += 6
        bar_w = self.rect.width - 120
        for name, value in agent.needs.as_dict().items():
            surface.blit(theme.font(13).render(NEED_LABELS[name], True, theme.TEXT_DIM), (x, y))
            bar = pygame.Rect(x + 80, y + 4, bar_w, 11)
            pygame.draw.rect(surface, (70, 70, 84), bar, border_radius=4)
            fill = bar.copy()
            fill.width = int(bar_w * value / 100)
            pygame.draw.rect(surface, _need_color(value), fill, border_radius=4)
            y += 20
        return y + 6


def _need_color(value: float) -> tuple[int, int, int]:
    if value < 25:
        return (220, 70, 60)
    if value < 50:
        return (230, 170, 60)
    return (90, 190, 110)


def _clip(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"
