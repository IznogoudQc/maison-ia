"""Rendu pixel art : la maison est dessinée en basse résolution puis agrandie sans lissage."""

from __future__ import annotations

import math

import pygame

from agents.agent import Agent
from ui import sprites, theme
from ui.sprites import SIT_FRAME, TILE
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
LIT_ROOM_FACTOR = 0.3  # part du voile de nuit qui reste dans une pièce éclairée
MOOD_THRESHOLD = 30.0  # besoin sous ce seuil : icône au-dessus de la tête
SITTING_ACTIONS = {"souper", "dejeuner", "tele"}
LYING_ACTIONS = {"dormir", "sieste"}
SOFA_SEAT_OFFSET = 10  # px : les spectateurs de la télé s'assoient sur le canapé, juste derrière leur case
HEALTH_ICON_BELOW = 40.0
# Cases de mur (face peinte visible) du salon où accrocher les cadres commémoratifs
MEMORIAL_TILES = [(17, 12), (19, 12), (21, 12), (23, 12)]


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
        self.tint = pygame.Surface(self.low_size, pygame.SRCALPHA)
        self.labels = self._build_labels()
        self.room_rects = {name: pygame.Rect(x0 * TILE, y0 * TILE, (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE)
                           for name, (x0, y0, x1, y1) in ROOMS.items()}
        self.room_glows = {name: _warm_glow(rect.size) for name, rect in self.room_rects.items()}
        self.spot_object = {pos: obj for obj in house.objects.values() for pos in obj.use_positions}
        # Position affichée (lissée), orientation et état de marche de chaque agent
        self.display_pos: dict[str, tuple[float, float]] = {}
        self.facing: dict[str, str] = {}
        self.moving: dict[str, bool] = {}
        self.time = 0.0
        self._top_rows: dict[int, int] = {}

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
        if action.name in ("telephone", "lire", "jouer"):
            return "down"  # face au joueur pour qu'on voie le téléphone, le livre, les Lego
        if action.name == "tele":
            return "up"    # assis sur le canapé, face à la télé
        obj = self.spot_object.get(agent.pos)
        if obj is not None:
            x, y, w, h = obj.rect
            return _direction(x + (w - 1) / 2 - agent.pos[0], y + (h - 1) / 2 - agent.pos[1])
        return None

    # ------------------------------------------------------------------ état visuel d'un agent

    @staticmethod
    def _active(agent: Agent, *names: str) -> bool:
        action = agent.action
        return action is not None and action.started and action.name in names

    def _pose(self, agent: Agent) -> str:
        if self._active(agent, *LYING_ACTIONS):
            return "lying"
        if self._active(agent, "douche"):
            return "shower"
        if self._active(agent, *SITTING_ACTIONS) and agent.pos == agent.action.use_pos and not self.moving.get(agent.id):
            return "sitting"
        return "standing"

    # ------------------------------------------------------------------ coordonnées

    def agent_screen_pos(self, agent: Agent) -> tuple[int, int]:
        if self._pose(agent) == "lying":
            hx, hy = self._head_low_pos(agent)
            return int(hx * self.scale), int(hy * self.scale)
        fx, fy = self.display_pos.get(agent.id, agent.pos)
        return int(fx * self.ts + self.ts / 2), int(fy * self.ts + self.ts / 2)

    def agent_at(self, agents: list[Agent], screen_pos: tuple[int, int]) -> Agent | None:
        best, best_dist = None, self.ts * 0.9
        for agent in agents:
            if agent.is_away or agent.dead:
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
        t = self.time
        hour = minute_of_day / 60.0
        low.blit(self.background, (0, 0))
        self._draw_windows(low, hour)
        self._draw_memorials(low, agents)
        visible = [a for a in agents if not a.is_away and not a.dead]
        steam_points = self._draw_object_states(low, visible)

        # Personnages du haut vers le bas pour que ceux du bas passent devant
        overlays: list[tuple[Agent, int, int]] = []  # (agent, centre x, haut de la tête) en basse résolution
        for agent in sorted(visible, key=lambda a: self.display_pos.get(a.id, a.pos)[1]):
            overlays.append(self._draw_agent(low, agent))

        for x, y in steam_points:
            sprites.draw_steam(low, x, y, t)
        self._draw_lighting(low, hour, visible)

        # Après l'éclairage, pour rester lisibles la nuit
        for agent, cx, top in overlays:
            bubble_shown = self._draw_feelings(low, agent, cx, top)
            if agent.id == selected_id:
                self._draw_marker(low, cx, top - (12 if bubble_shown else 0))

        surface.blit(pygame.transform.scale(low, self.size), (0, 0))
        surface.blit(self.labels, (0, 0))
        for agent in visible:
            if self._pose(agent) == "lying":
                self._draw_zzz(surface, agent)
            elif agent.thinking:
                self._draw_thinking(surface, agent)

    def _draw_windows(self, low: pygame.Surface, hour: float) -> None:
        sky = sprites.sky_color(hour)
        stars = hour >= 21 or hour < 5
        for x, y, vertical in WINDOWS:
            sprites.draw_window(low, x, y, vertical, on_face=(x, y + 1) in self.house.floor, sky=sky, stars=stars)

    def _draw_memorials(self, low: pygame.Surface, agents: list[Agent]) -> None:
        """Un cadre avec ruban noir par membre décédé, sur la face du mur nord du salon."""
        departed = sorted((a for a in agents if a.dead), key=lambda a: a.died_minute or 0)
        for index, agent in enumerate(departed):
            tx, ty = MEMORIAL_TILES[index % len(MEMORIAL_TILES)]
            sprites.draw_memorial(low, tx * TILE + 2, ty * TILE + TILE // 2, agent.persona)

    def _draw_object_states(self, low: pygame.Surface, agents: list[Agent]) -> list[tuple[int, int]]:
        """Objets animés selon les actions en cours ; renvoie les points d'où monte de la vapeur."""
        objects = self.house.objects
        frame = int(self.time * WALK_FPS)
        steam: list[tuple[int, int]] = []
        if any(self._active(a, "tele") for a in agents) and "tele" in objects:
            sprites.draw_tv_screen(low, objects["tele"], frame)
        if any(self._active(a, "ordi") for a in agents) and "ordi" in objects:
            sprites.draw_computer_screen(low, objects["ordi"], self.time)
        if any(self._active(a, "collation") for a in agents) and "frigo" in objects:
            sprites.draw_fridge_open(low, objects["frigo"])
        if any(self._active(a, "cuisiner") for a in agents) and "cuisiniere" in objects:
            steam.append(sprites.draw_pan(low, objects["cuisiniere"]))
        meal = next((a.action.name for a in agents if self._active(a, "souper", "dejeuner")), None)
        if meal and "table" in objects:
            x, y, w, h = objects["table"].rect
            for plate in sprites.table_plates(pygame.Rect(x * TILE, y * TILE, w * TILE, h * TILE)):
                sprites.draw_food(low, plate, dinner=meal == "souper")
        if any(self._active(a, "douche") for a in agents) and "douche" in objects:
            x, y, w, h = objects["douche"].rect
            steam.append((x * TILE + w * TILE // 2, y * TILE + 6))
        return steam

    def _draw_agent(self, low: pygame.Surface, agent: Agent) -> tuple[Agent, int, int]:
        pose = self._pose(agent)
        if pose == "lying":
            hx, hy = self._head_low_pos(agent)
            sprites.draw_blanket_bump(low, agent.persona.bed, (hx, hy), agent.persona.age < 13)
            head = sprites.sleeping_head(agent.persona)
            rect = head.get_rect(center=(round(hx), round(hy)))
            low.blit(head, rect)
            return agent, rect.centerx, rect.top

        fx, fy = self.display_pos.get(agent.id, agent.pos)
        cx = round(fx * TILE + TILE / 2)
        feet = round(fy * TILE + TILE - SPRITE_LIFT)
        direction = self.facing.get(agent.id, "down")
        frames = sprites.character_frames(agent.persona)
        if pose == "shower":
            # Dans la cabine, derrière la vitre embuée
            x, y, w, h = self.house.objects["douche"].rect
            cx, feet, direction = x * TILE + w * TILE // 2, (y + h) * TILE - 3, "down"
            sprite = frames[(direction, 0)]
        elif pose == "sitting":
            sprite = frames[(direction, SIT_FRAME)]
            if self._active(agent, "tele"):
                feet += SOFA_SEAT_OFFSET
        else:
            image = (1 + int(self.time * WALK_FPS) % 2) if self.moving.get(agent.id) else 0
            sprite = frames[(direction, image)]

        left = cx - sprite.get_width() // 2
        top = feet - sprite.get_height() + 1
        if pose != "shower":
            shadow = pygame.Rect(0, 0, 10, 4)
            shadow.center = (cx, feet)
            pygame.draw.ellipse(low, (40, 32, 36), shadow)
        low.blit(sprite, (left, top))
        head_top = top + self._top_row(sprite)
        if pose == "shower":
            self._draw_shower_glass(low)
        else:
            self._draw_accessory(low, agent, direction, left, top)
        return agent, cx, head_top

    def _draw_shower_glass(self, low: pygame.Surface) -> None:
        x, y, w, h = self.house.objects["douche"].rect
        glass = pygame.Surface((w * TILE, h * TILE // 2 + 2), pygame.SRCALPHA)
        glass.fill((225, 240, 248, 170))
        low.blit(glass, (x * TILE, y * TILE + h * TILE // 2 - 2))
        pygame.draw.line(low, (170, 220, 245), (x * TILE, (y + h) * TILE - 1), ((x + w) * TILE - 1, (y + h) * TILE - 1))

    def _draw_accessory(self, low: pygame.Surface, agent: Agent, direction: str, left: int, top: int) -> None:
        """Objet tenu ou posé selon l'action en cours (coordonnées du sprite 16 px de large)."""
        hand_x = {"down": left + 11, "left": left + 5, "right": left + 8, "up": left + 11}[direction]
        hand_y = top + 10
        if self._active(agent, "telephone") and direction != "up":
            sprites.draw_phone(low, hand_x, hand_y, self.time)
        elif self._active(agent, "lire") and direction != "up":
            sprites.draw_book(low, left + 5 if direction == "down" else hand_x - 2, hand_y + 1)
        elif self._active(agent, "jouer"):
            sprites.draw_lego(low, left + 8, top + 14)
        elif self._active(agent, "dejeuner") and agent.persona.age >= 18 and "table" in self.house.objects:
            # Café du matin posé sur la table, entre l'adulte et le centre de la table
            x, y, w, h = self.house.objects["table"].rect
            tcx, tcy = (x + w / 2) * TILE, (y + h / 2) * TILE
            px, py = left + 8, top + 12
            sprites.draw_mug(low, round(px + (tcx - px) * 0.35), round(py + (tcy - py) * 0.35))

    def _top_row(self, sprite: pygame.Surface) -> int:
        key = id(sprite)
        if key not in self._top_rows:
            self._top_rows[key] = next((y for y in range(sprite.get_height())
                                        if any(sprite.get_at((x, y)).a for x in range(sprite.get_width()))), 0)
        return self._top_rows[key]

    # ------------------------------------------------------------------ éclairage

    def _draw_lighting(self, low: pygame.Surface, hour: float, agents: list[Agent]) -> None:
        # Lumière dorée en fin d'après-midi, rosée à l'aube
        golden = _triangle(hour, 16.5, 18.5, 20.5) * 45
        dawn = _triangle(hour, 5.5, 6.4, 7.5) * 35
        if golden >= 1:
            self.tint.fill((255, 168, 80, round(golden)))
            low.blit(self.tint, (0, 0))
        if dawn >= 1:
            self.tint.fill((255, 150, 140, round(dawn)))
            low.blit(self.tint, (0, 0))

        alpha = _night_alpha(hour)
        if not alpha:
            return
        # Lampes allumées là où quelqu'un est éveillé ; les pièces vides restent dans le noir
        lit = {self.house.room_at(a.pos) for a in agents if a.is_available} - {None}
        self.night.fill((10, 15, 50, alpha))
        for room in lit:
            self.night.fill((10, 15, 50, round(alpha * LIT_ROOM_FACTOR)), self.room_rects[room])
        low.blit(self.night, (0, 0))
        strength = min(255, alpha * 2)
        for room in lit:
            glow = self.room_glows[room]
            glow.set_alpha(strength)
            low.blit(glow, self.room_rects[room].topleft)
        if any(self._active(a, "tele") for a in agents) and "tele" in self.house.objects:
            self._draw_tv_glow(low, self.house.objects["tele"], alpha)

    def _draw_tv_glow(self, low: pygame.Surface, tv, alpha: int) -> None:
        x, y, w, _h = tv.rect
        glow = pygame.Surface((w * TILE + 24, 4 * TILE), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (120, 170, 255, min(70, alpha)), glow.get_rect())
        low.blit(glow, (x * TILE - 12, y * TILE))

    # ------------------------------------------------------------------ humeur

    @staticmethod
    def _mood_icon(agent: Agent) -> str | None:
        if agent.thinking or not agent.is_available:
            return None
        if agent.health < HEALTH_ICON_BELOW:
            return "health"
        need, value = agent.needs.lowest()
        return need if value < MOOD_THRESHOLD else None

    def _draw_feelings(self, low: pygame.Surface, agent: Agent, cx: int, top: int) -> bool:
        """Icône de besoin ou petit effet de bonheur ; True si une bulle d'icône est affichée."""
        name = self._mood_icon(agent)
        if name is not None:
            critical = agent.health < 20 if name == "health" else agent.needs.lowest()[1] < 15
            # État critique : l'icône clignote
            if not critical or int(self.time * 3) % 2 == 0:
                sprites.draw_mood_bubble(low, name, cx, top)
                return True
            return False
        if self._active(agent, "jaser") or (self._active(agent, "souper") and agent.mood == "excellente"):
            # Décalage stable par agent pour que les cœurs ne montent pas tous en même temps
            offset = sum(map(ord, agent.id)) % 7 * 0.23
            sprites.draw_floating(low, "heart", cx + 5, top, self.time + offset)
        elif self._active(agent, "jouer"):
            sprites.draw_floating(low, "star", cx + 5, top, self.time)
        return False

    def _draw_marker(self, low: pygame.Surface, x: int, y: int) -> None:
        """Petite flèche jaune qui flotte au-dessus de l'agent sélectionné."""
        bob = int(math.sin(self.time * 5) * 1.5)
        tip = y - 1 + bob
        pygame.draw.polygon(low, theme.ACCENT, [(x - 3, tip - 4), (x + 3, tip - 4), (x, tip - 1)])
        pygame.draw.polygon(low, sprites.OUTLINE, [(x - 3, tip - 4), (x + 3, tip - 4), (x, tip - 1)], 1)

    # ------------------------------------------------------------------ haute résolution

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


def _triangle(x: float, start: float, peak: float, end: float) -> float:
    """0 hors de [start, end], 1 au sommet, linéaire entre les deux."""
    if x <= start or x >= end:
        return 0.0
    return (x - start) / (peak - start) if x < peak else (end - x) / (end - peak)


def _night_alpha(hour: float) -> int:
    # Assombrissement progressif entre 19 h et 22 h, éclaircissement entre 5 h et 7 h
    if 7 <= hour < 19:
        return 0
    if 19 <= hour < 22:
        return int((hour - 19) / 3 * NIGHT_ALPHA)
    if 5 <= hour < 7:
        return int((7 - hour) / 2 * NIGHT_ALPHA)
    return NIGHT_ALPHA


def _warm_glow(size: tuple[int, int]) -> pygame.Surface:
    """Halo chaud elliptique (plus intense au centre) pour une pièce éclairée la nuit."""
    glow = pygame.Surface(size, pygame.SRCALPHA)
    width, height = size
    rings = 6
    for i in range(rings):
        k = 1 - i / rings
        rect = pygame.Rect(0, 0, round(width * k), round(height * k))
        rect.center = (width // 2, height // 2)
        pygame.draw.ellipse(glow, (255, 196, 120, 10 + i * 9), rect)
    return glow
