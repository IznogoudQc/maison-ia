"""Rendu pixel art : la maison est dessinée en basse résolution puis agrandie sans lissage."""

from __future__ import annotations

import math

import pygame

from agents.agent import Agent
from ui import sprites, theme
from ui.sprites import TILE
from world.house import ROOMS, House

# Fenêtres sur les murs extérieurs : (x, y, verticale)
WINDOWS: list[tuple[int, int, bool]] = [
    (3, 0, False), (8, 0, False), (16, 0, False), (19, 0, False), (25, 0, False), (33, 0, False),
    (4, 23, False), (9, 23, False), (19, 23, False), (24, 23, False), (34, 23, False),
    (0, 4, True), (0, 17, True), (0, 20, True), (36, 5, True), (36, 16, True), (36, 20, True),
]
WALK_FPS = 8          # images de marche par seconde
SPRITE_LIFT = 4       # le personnage déborde un peu sur la tuile du dessus (effet de profondeur)
NIGHT_ALPHA = 135     # opacité du voile bleu en pleine nuit


class Renderer:
    def __init__(self, house: House, scale: float = 2.0) -> None:
        self.house = house
        self.scale = scale
        self.low_size = (house.width * TILE, house.height * TILE)
        self.ts = round(TILE * scale)  # taille d'une tuile à l'écran
        self.size = (house.width * self.ts, house.height * self.ts)
        self.background = self._build_background()
        self.low = pygame.Surface(self.low_size)
        self.night = pygame.Surface(self.low_size, pygame.SRCALPHA)
        self.labels = self._build_labels()
        self.spot_object = {pos: obj for obj in house.objects.values() for pos in obj.use_positions}
        # Position affichée (lissée), orientation et état de marche de chaque agent
        self.display_pos: dict[str, tuple[float, float]] = {}
        self.facing: dict[str, str] = {}
        self.moving: dict[str, bool] = {}
        self.time = 0.0

    # ------------------------------------------------------------------ décor statique

    def _build_background(self) -> pygame.Surface:
        surf = pygame.Surface(self.low_size)
        house = self.house
        for y in range(house.height):
            for x in range(house.width):
                pos = (x, y)
                if pos in house.doors:
                    sprites.draw_door_floor(surf, x, y)
                elif not house.is_wall(pos):
                    room = house.room_at(pos) or ""
                    sprites.draw_floor(surf, x, y, sprites.FLOOR_STYLES.get(room, "wood"),
                                       theme.ROOM_COLORS.get(room, (200, 200, 200)))
                else:
                    sprites.draw_wall(surf, x, y, floor_below=(x, y + 1) in house.floor)
        for x, y, vertical in WINDOWS:
            sprites.draw_window(surf, x, y, vertical, on_face=(x, y + 1) in house.floor)
        for obj in house.objects.values():
            sprites.draw_object(surf, obj)
        return surf

    def _build_labels(self) -> pygame.Surface:
        """Noms des pièces en haute résolution, pour rester lisibles après agrandissement."""
        surf = pygame.Surface(self.size, pygame.SRCALPHA)
        font = theme.font(12, bold=True)
        for name, (x0, _y0, _x1, y1) in ROOMS.items():
            text = font.render(name, True, (250, 248, 240))
            pill = text.get_rect().inflate(10, 2)
            pill.bottomleft = (x0 * self.ts + 3, (y1 + 1) * self.ts - 3)
            pygame.draw.rect(surf, (30, 26, 32, 150), pill, border_radius=6)
            surf.blit(text, text.get_rect(center=pill.center))
        return surf

    # ------------------------------------------------------------------ animation

    def update_display(self, agents: list[Agent], dt: float) -> None:
        # Lissage exponentiel vers la position logique ; téléportation si trop loin
        self.time += dt
        factor = 1.0 - math.exp(-dt * 10.0)
        for agent in agents:
            tx, ty = agent.pos
            cur = self.display_pos.get(agent.id)
            if cur is None or abs(cur[0] - tx) + abs(cur[1] - ty) > 8:
                self.display_pos[agent.id] = (float(tx), float(ty))
                self.moving[agent.id] = False
                continue
            dx, dy = tx - cur[0], ty - cur[1]
            self.display_pos[agent.id] = (cur[0] + dx * factor, cur[1] + dy * factor)
            moving = abs(dx) + abs(dy) > 0.08
            self.moving[agent.id] = moving
            if moving:
                self.facing[agent.id] = _direction(dx, dy)
            else:
                facing = self._facing_at_rest(agent, agents)
                if facing:
                    self.facing[agent.id] = facing

    def _facing_at_rest(self, agent: Agent, agents: list[Agent]) -> str | None:
        """Sur place : se tourner vers l'objet utilisé ou vers la personne avec qui on jase."""
        action = agent.action
        if action is None or not action.started:
            return None
        if action.name == "jaser" and action.target:
            other = next((a for a in agents if a.id == action.target), None)
            if other is not None:
                return _direction(other.pos[0] - agent.pos[0], other.pos[1] - agent.pos[1])
        obj = self.spot_object.get(agent.pos)
        if obj is not None:
            x, y, w, h = obj.rect
            return _direction(x + (w - 1) / 2 - agent.pos[0], y + (h - 1) / 2 - agent.pos[1])
        return None

    # ------------------------------------------------------------------ coordonnées

    def agent_screen_pos(self, agent: Agent) -> tuple[int, int]:
        if agent.is_sleeping:
            hx, hy = self._head_low_pos(agent)
            return int(hx * self.scale), int(hy * self.scale)
        fx, fy = self.display_pos.get(agent.id, agent.pos)
        return int(fx * self.ts + self.ts / 2), int(fy * self.ts + self.ts / 2)

    def agent_at(self, agents: list[Agent], screen_pos: tuple[int, int]) -> Agent | None:
        best, best_dist = None, self.ts * 0.9
        for agent in agents:
            if agent.is_away:
                continue
            ax, ay = self.agent_screen_pos(agent)
            dist = math.hypot(ax - screen_pos[0], ay - screen_pos[1])
            if dist < best_dist:
                best, best_dist = agent, dist
        return best

    def _head_low_pos(self, agent: Agent) -> tuple[float, float]:
        """Centre de la tête d'un dormeur, sur l'oreiller de sa place dans le lit."""
        bed = self.house.objects[agent.persona.bed]
        slot = 0
        if agent.action is not None and agent.action.use_pos in bed.use_positions:
            slot = bed.use_positions.index(agent.action.use_pos)
        x, y, w, _h = bed.rect
        places = max(1, bed.capacity)
        return x * TILE + w * TILE * (slot + 0.5) / places, y * TILE + 7

    # ------------------------------------------------------------------ dessin

    def draw(self, surface: pygame.Surface, agents: list[Agent], selected_id: str | None,
             minute_of_day: int) -> None:
        low = self.low
        low.blit(self.background, (0, 0))
        frame = int(self.time * WALK_FPS)
        tv_on = any(a.action is not None and a.action.name == "tele" and a.action.started for a in agents)
        tv = self.house.objects.get("tele")
        if tv_on and tv is not None:
            sprites.draw_tv_screen(low, tv, frame)

        visible = [a for a in agents if not a.is_away]
        for agent in sorted(visible, key=lambda a: self.display_pos.get(a.id, a.pos)[1]):
            if agent.is_sleeping:
                self._draw_sleeper(low, agent, agent.id == selected_id)
            else:
                self._draw_walker(low, agent, frame, agent.id == selected_id)

        alpha = _night_alpha(minute_of_day)
        if alpha:
            self.night.fill((10, 15, 50, alpha))
            low.blit(self.night, (0, 0))
            if tv_on and tv is not None:
                self._draw_tv_glow(low, tv, alpha)

        surface.blit(pygame.transform.scale(low, self.size), (0, 0))
        surface.blit(self.labels, (0, 0))
        for agent in visible:
            if agent.is_sleeping:
                self._draw_zzz(surface, agent)
            elif agent.thinking:
                self._draw_thinking(surface, agent)

    def _draw_walker(self, low: pygame.Surface, agent: Agent, frame: int, selected: bool) -> None:
        fx, fy = self.display_pos.get(agent.id, agent.pos)
        direction = self.facing.get(agent.id, "down")
        image = (1 + frame % 2) if self.moving.get(agent.id) else 0
        sprite = sprites.character_frames(agent.persona)[(direction, image)]
        left = round(fx * TILE + TILE / 2 - sprite.get_width() / 2)
        top = round(fy * TILE + TILE - sprite.get_height() + 1 - SPRITE_LIFT)
        shadow = pygame.Rect(0, 0, 10, 4)
        shadow.center = (round(fx * TILE + TILE / 2), round(fy * TILE + TILE - SPRITE_LIFT))
        pygame.draw.ellipse(low, (40, 32, 36), shadow)
        low.blit(sprite, (left, top))
        if selected:
            self._draw_marker(low, left + sprite.get_width() // 2, top + _first_opaque_row(sprite) - 2)

    def _draw_sleeper(self, low: pygame.Surface, agent: Agent, selected: bool) -> None:
        head = sprites.sleeping_head(agent.persona)
        hx, hy = self._head_low_pos(agent)
        rect = head.get_rect(center=(round(hx), round(hy)))
        low.blit(head, rect)
        if selected:
            self._draw_marker(low, rect.centerx, rect.top)

    def _draw_marker(self, low: pygame.Surface, x: int, y: int) -> None:
        """Petite flèche jaune qui flotte au-dessus de l'agent sélectionné."""
        bob = int(math.sin(self.time * 5) * 1.5)
        tip = y - 1 + bob
        pygame.draw.polygon(low, theme.ACCENT, [(x - 3, tip - 4), (x + 3, tip - 4), (x, tip - 1)])
        pygame.draw.polygon(low, sprites.OUTLINE, [(x - 3, tip - 4), (x + 3, tip - 4), (x, tip - 1)], 1)

    def _draw_tv_glow(self, low: pygame.Surface, tv, alpha: int) -> None:
        x, y, w, _h = tv.rect
        glow = pygame.Surface((w * TILE + 24, 4 * TILE), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (120, 170, 255, min(70, alpha)), glow.get_rect())
        low.blit(glow, (x * TILE - 12, y * TILE))

    def _draw_zzz(self, surface: pygame.Surface, agent: Agent) -> None:
        cx, cy = self.agent_screen_pos(agent)
        offset = (self.time * 12) % 12
        text = theme.font(12, bold=True).render("z z", True, (235, 238, 255))
        surface.blit(text, (cx + 8, cy - 18 - offset))

    def _draw_thinking(self, surface: pygame.Surface, agent: Agent) -> None:
        cx, cy = self.agent_screen_pos(agent)
        rect = pygame.Rect(0, 0, 30, 18)
        rect.midbottom = (cx, cy - self.ts // 2 - 12)
        pygame.draw.rect(surface, (250, 250, 252), rect, border_radius=8)
        pygame.draw.rect(surface, agent.persona.color, rect, 2, border_radius=8)
        dots = theme.font(14, bold=True).render("…", True, theme.TEXT_DARK)
        surface.blit(dots, dots.get_rect(center=(rect.centerx, rect.centery - 2)))


def _direction(dx: float, dy: float) -> str:
    if abs(dx) > abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _night_alpha(minute_of_day: int) -> int:
    # Assombrissement progressif entre 19 h et 22 h, éclaircissement entre 5 h et 7 h
    hour = minute_of_day / 60.0
    if 7 <= hour < 19:
        return 0
    if 19 <= hour < 22:
        return int((hour - 19) / 3 * NIGHT_ALPHA)
    if 5 <= hour < 7:
        return int((7 - hour) / 2 * NIGHT_ALPHA)
    return NIGHT_ALPHA


def _first_opaque_row(sprite: pygame.Surface) -> int:
    for y in range(sprite.get_height()):
        if any(sprite.get_at((x, y)).a for x in range(sprite.get_width())):
            return y
    return 0
