"""Panneau latéral : heure, vitesse, contrôles."""

from __future__ import annotations

import pygame

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

    def draw(self, surface: pygame.Surface, clock: SimClock, speed: float, paused: bool) -> None:
        pygame.draw.rect(surface, theme.PANEL, self.rect)
        pygame.draw.line(surface, theme.PANEL_BORDER, self.rect.topleft, self.rect.bottomleft, 2)
        x, y = self.rect.x + 14, self.rect.y + 12
        surface.blit(theme.font(20, bold=True).render(clock.label(), True, theme.TEXT), (x, y))
        y += 32
        state = "PAUSE" if paused else f"Vitesse x{speed:g}"
        surface.blit(theme.font(15).render(state, True, theme.ACCENT if paused else theme.TEXT_DIM), (x, y))
        y = self.rect.bottom - 18 * len(CONTROLS) - 10
        for line in CONTROLS:
            surface.blit(theme.font(13).render(line, True, theme.TEXT_DIM), (x, y))
            y += 18
