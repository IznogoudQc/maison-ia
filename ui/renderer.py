"""Dessin de la maison et des agents (formes simples, aucun asset)."""

from __future__ import annotations

import math

import pygame

from agents.agent import Agent
from ui import theme
from world.house import ROOMS, House


class Renderer:
    def __init__(self, house: House, tile_size: int) -> None:
        self.house = house
        self.ts = tile_size
        self.size = (house.width * tile_size, house.height * tile_size)
        self.background = self._build_background()
        # Position affichée (lissée) de chaque agent, en tuiles
        self.display_pos: dict[str, tuple[float, float]] = {}

    def _build_background(self) -> pygame.Surface:
        ts = self.ts
        surf = pygame.Surface(self.size)
        surf.fill(theme.WALL)
        for y in range(self.house.height):
            for x in range(self.house.width):
                pos = (x, y)
                rect = pygame.Rect(x * ts, y * ts, ts, ts)
                if pos in self.house.doors:
                    pygame.draw.rect(surf, theme.DOOR, rect)
                elif not self.house.is_wall(pos):
                    color = theme.ROOM_COLORS.get(self.house.room_at(pos) or "", (200, 200, 200))
                    pygame.draw.rect(surf, color, rect)
                    pygame.draw.rect(surf, _shade(color, -8), rect, 1)

        for obj in self.house.objects.values():
            x, y, w, h = obj.rect
            rect = pygame.Rect(x * ts + 2, y * ts + 2, w * ts - 4, h * ts - 4)
            color = theme.OBJECT_COLORS.get(obj.kind, theme.OBJECT_COLORS["deco"])
            pygame.draw.rect(surf, color, rect, border_radius=4)
            pygame.draw.rect(surf, _shade(color, -40), rect, 2, border_radius=4)
            text_color = theme.TEXT_DARK if sum(color) > 380 else theme.TEXT
            label = theme.font(11).render(obj.label.split(" (")[0], True, text_color)
            if label.get_width() <= rect.width + 10 and obj.kind not in ("porte",):
                surf.blit(label, label.get_rect(center=rect.center))

        for name, (x0, _y0, _x1, y1) in ROOMS.items():
            label = theme.font(13, bold=True).render(name, True, _shade(theme.ROOM_COLORS[name], -90))
            surf.blit(label, (x0 * ts + 4, (y1 + 1) * ts - label.get_height() - 1))
        return surf

    def update_display(self, agents: list[Agent], dt: float) -> None:
        # Lissage exponentiel vers la position logique ; téléportation si trop loin
        factor = 1.0 - math.exp(-dt * 10.0)
        for agent in agents:
            tx, ty = agent.pos
            cur = self.display_pos.get(agent.id)
            if cur is None or abs(cur[0] - tx) + abs(cur[1] - ty) > 8:
                self.display_pos[agent.id] = (float(tx), float(ty))
            else:
                self.display_pos[agent.id] = (cur[0] + (tx - cur[0]) * factor,
                                              cur[1] + (ty - cur[1]) * factor)

    def agent_screen_pos(self, agent: Agent) -> tuple[int, int]:
        fx, fy = self.display_pos.get(agent.id, agent.pos)
        return int(fx * self.ts + self.ts / 2), int(fy * self.ts + self.ts / 2)

    def agent_at(self, agents: list[Agent], screen_pos: tuple[int, int]) -> Agent | None:
        best, best_dist = None, self.ts * 0.9
        for agent in agents:
            ax, ay = self.agent_screen_pos(agent)
            dist = math.hypot(ax - screen_pos[0], ay - screen_pos[1])
            if dist < best_dist:
                best, best_dist = agent, dist
        return best

    def draw(self, surface: pygame.Surface, agents: list[Agent], selected_id: str | None,
             minute_of_day: int) -> None:
        surface.blit(self.background, (0, 0))
        radius = int(self.ts * 0.45)
        for agent in agents:
            if agent.is_away:
                continue
            cx, cy = self.agent_screen_pos(agent)
            if agent.id == selected_id:
                pygame.draw.circle(surface, theme.ACCENT, (cx, cy), radius + 4, 3)
            pygame.draw.circle(surface, (20, 20, 24), (cx + 1, cy + 2), radius)
            color = _shade(agent.persona.color, -50) if agent.is_sleeping else agent.persona.color
            pygame.draw.circle(surface, color, (cx, cy), radius)
            initial = theme.font(13, bold=True).render(agent.name[0], True, (255, 255, 255))
            surface.blit(initial, initial.get_rect(center=(cx, cy)))
            if agent.is_sleeping:
                zzz = theme.font(12, bold=True).render("z z", True, (240, 240, 255))
                surface.blit(zzz, (cx + radius - 2, cy - radius - 10))
        self._draw_night(surface, minute_of_day)

    def _draw_night(self, surface: pygame.Surface, minute_of_day: int) -> None:
        # Assombrissement progressif entre 19 h et 22 h, éclaircissement entre 5 h et 7 h
        hour = minute_of_day / 60.0
        if 7 <= hour < 19:
            return
        if 19 <= hour < 22:
            alpha = (hour - 19) / 3 * 90
        elif 5 <= hour < 7:
            alpha = (7 - hour) / 2 * 90
        else:
            alpha = 90
        overlay = pygame.Surface(self.size, pygame.SRCALPHA)
        overlay.fill((10, 15, 50, int(alpha)))
        surface.blit(overlay, (0, 0))


def _shade(color: tuple[int, int, int], delta: int) -> tuple[int, int, int]:
    return tuple(max(0, min(255, c + delta)) for c in color)  # type: ignore[return-value]
