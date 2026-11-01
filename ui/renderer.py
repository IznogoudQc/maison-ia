"""Rendu pixel art : la maison est dessinée en basse résolution puis agrandie sans lissage."""

from __future__ import annotations

import math

import pygame

from agents.agent import Agent
from ui import sprites, theme
from ui.sprites import SIT_FRAME, TILE
from world.house import House

ZOOM_LEVELS = (1.0, 1.5, 2.0, 3.0)
WILD_GRASS = 55.0      # herbe d'un terrain sauvage (jamais tondu)
MINIMAP_WIDTH = 180    # px à l'écran
FIRE_HOURS = (17, 23)  # le feu de camp brûle en soirée (ou quand on cuisine / veille autour)
WALK_FPS = 8          # images de marche par seconde
SPRITE_LIFT = 4       # le personnage déborde un peu sur la tuile du dessus (effet de profondeur)
NIGHT_ALPHA = 135     # opacité du voile bleu en pleine nuit
LIT_ROOM_FACTOR = 0.3  # part du voile de nuit qui reste dans une pièce éclairée
MOOD_THRESHOLD = 30.0  # besoin sous ce seuil : icône au-dessus de la tête
SITTING_ACTIONS = {"souper", "dejeuner", "tele", "veiller"}
LYING_ACTIONS = {"dormir", "sieste"}
SOFA_SEAT_OFFSET = 10  # px : les spectateurs de la télé s'assoient sur le canapé, juste derrière leur case
HEALTH_ICON_BELOW = 40.0


class Renderer:
    def __init__(self, house: House, scale: float = 2.0, viewport: tuple[int, int] | None = None) -> None:
        self.house = house
        self.low_size = (house.width * TILE, house.height * TILE)
        # Zone de carte à l'écran ; la caméra défile quand la carte agrandie la dépasse
        self.size = viewport or (round(self.low_size[0] * scale), round(self.low_size[1] * scale))
        self.camera = [0.0, 0.0]  # coin haut-gauche de la vue, en px basse résolution
        self.scale = scale
        self.ts = round(TILE * scale)  # taille d'une tuile à l'écran
        self.set_scale(scale)
        # État de la cour fourni par set_yard ; le décor est reconstruit quand il change
        self.lawn = 20.0
        self.car_home = False
        self.wood = 0
        self._built_key: tuple[int, int] | None = None
        self.background = self._build_background()
        self.low = pygame.Surface(self.low_size)
        self.night = pygame.Surface(self.low_size, pygame.SRCALPHA)
        self.tint = pygame.Surface(self.low_size, pygame.SRCALPHA)
        self._label_cache: dict[str, pygame.Surface] = {}
        indoor = {n: r for n, r in house.rooms.items() if n not in house.outdoor_rooms}
        self.room_rects = {name: pygame.Rect(x0 * TILE, y0 * TILE, (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE)
                           for name, (x0, y0, x1, y1) in indoor.items()}
        self.room_glows = {name: _warm_glow(rect.size) for name, rect in self.room_rects.items()}
        self.purchases: set[str] = set()  # achats du ménage qui changent le dessin (scie à chaîne)
        self._minimap: pygame.Surface | None = None
        self._minimap_revision = -1
        # Position affichée (lissée), orientation et état de marche de chaque agent
        self.display_pos: dict[str, tuple[float, float]] = {}
        self.facing: dict[str, str] = {}
        self.moving: dict[str, bool] = {}
        self.time = 0.0
        self.time_of_day = 12.0
        self._top_rows: dict[int, int] = {}

    # ------------------------------------------------------------------ décor statique

    def set_yard(self, lawn: float, car_home: bool, wood: int = 0) -> None:
        self.lawn = lawn
        self.car_home = car_home
        self.wood = wood

    # ------------------------------------------------------------------ caméra

    @property
    def min_scale(self) -> float:
        """Plus petit zoom où la carte couvre encore toute la zone d'affichage."""
        return max(self.size[0] / self.low_size[0], self.size[1] / self.low_size[1])

    @property
    def scrollable(self) -> bool:
        return (self.low_size[0] * self.scale > self.size[0] + 1
                or self.low_size[1] * self.scale > self.size[1] + 1)

    def set_scale(self, scale: float, anchor: tuple[int, int] | None = None) -> None:
        """Change le zoom en gardant fixe le point de l'écran anchor (défaut : centre de la vue)."""
        ax, ay = anchor or (self.size[0] // 2, self.size[1] // 2)
        world_x = self.camera[0] + ax / self.scale
        world_y = self.camera[1] + ay / self.scale
        self.scale = scale
        self.ts = round(TILE * scale)
        self.camera = [world_x - ax / scale, world_y - ay / scale]
        self._clamp_camera()

    def zoom(self, step: int, anchor: tuple[int, int] | None = None) -> None:
        levels = [z for z in ZOOM_LEVELS if z >= self.min_scale - 1e-6] or [ZOOM_LEVELS[-1]]
        current = min(range(len(levels)), key=lambda i: abs(levels[i] - self.scale))
        target = levels[max(0, min(len(levels) - 1, current + step))]
        if target != self.scale:
            self.set_scale(target, anchor)

    def pan(self, dx: float, dy: float) -> None:
        """Déplace la vue de (dx, dy) pixels écran."""
        self.camera[0] += dx / self.scale
        self.camera[1] += dy / self.scale
        self._clamp_camera()

    def center_on(self, tile_x: float, tile_y: float) -> None:
        self.camera = [tile_x * TILE + TILE / 2 - self.size[0] / self.scale / 2,
                       tile_y * TILE + TILE / 2 - self.size[1] / self.scale / 2]
        self._clamp_camera()

    def _clamp_camera(self) -> None:
        for i in (0, 1):
            limit = max(0.0, self.low_size[i] - self.size[i] / self.scale)
            self.camera[i] = max(0.0, min(limit, self.camera[i]))

    def _cam(self) -> tuple[int, int]:
        return int(self.camera[0]), int(self.camera[1])

    def view_rect(self) -> pygame.Rect:
        """Partie de la carte visible, en px basse résolution."""
        cx, cy = self._cam()
        rect = pygame.Rect(cx, cy, math.ceil(self.size[0] / self.scale) + 1,
                           math.ceil(self.size[1] / self.scale) + 1)
        return rect.clip(pygame.Rect((0, 0), self.low_size))

    def to_screen(self, low_x: float, low_y: float) -> tuple[int, int]:
        cx, cy = self._cam()
        return int((low_x - cx) * self.scale), int((low_y - cy) * self.scale)

    def on_screen(self, pos: tuple[int, int], margin: int = 0) -> bool:
        return -margin <= pos[0] < self.size[0] + margin and -margin <= pos[1] < self.size[1] + margin

    def _lawn_bucket(self) -> int:
        return min(3, int(self.lawn // 25))  # 4 états visuels du gazon

    def _grass_height(self) -> float:
        return WILD_GRASS if self.house.layout.wild else self._lawn_bucket() * 25 + 12

    def _draw_tile(self, surf: pygame.Surface, pos: tuple[int, int], lawn: float) -> None:
        house = self.house
        x, y = pos
        if pos in house.doors:
            sprites.draw_door_floor(surf, x, y)
        elif pos in house.water:
            sprites.draw_water(surf, x, y)
        elif house.is_outdoor(pos):
            surface = house.surface_at(pos)
            if surface:
                sprites.draw_surface(surf, x, y, surface)
            else:
                sprites.draw_grass(surf, x, y, lawn)
        elif not house.is_wall(pos):
            room = house.room_at(pos) or ""
            sprites.draw_floor(surf, x, y, sprites.FLOOR_STYLES.get(room, "wood"),
                               theme.ROOM_COLORS.get(room, (200, 200, 200)))
        elif pos in house.street:
            sprites.draw_surface(surf, x, y, "street")
        elif pos in house.fences:
            sprites.draw_fence(surf, x, y, lawn, vertical=x == house.width - 1)
        else:
            sprites.draw_wall(surf, x, y, floor_below=(x, y + 1) in house.floor)

    def _build_background(self) -> pygame.Surface:
        self._built_key = (self.house.revision, self._lawn_bucket())
        self.house.dirty.clear()
        lawn = self._grass_height()
        surf = pygame.Surface(self.low_size)
        house = self.house
        for y in range(house.height):
            for x in range(house.width):
                self._draw_tile(surf, (x, y), lawn)
        for obj in sorted(house.objects.values(), key=lambda o: o.rect[1]):
            sprites.draw_object(surf, obj)
        return surf

    def _refresh_background(self) -> None:
        """Arbre coupé, objet ajouté : on redessine seulement les tuiles touchées et leurs voisines."""
        house = self.house
        if not house.dirty:
            self.background = self._build_background()
            return
        area = {(x + dx, y + dy) for x, y in house.dirty for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        area = {p for p in area if house.in_bounds(p)}
        house.dirty.clear()
        lawn = self._grass_height()
        for pos in area:
            self._draw_tile(self.background, pos, lawn)
        xs, ys = [p[0] for p in area], [p[1] for p in area]
        x0, x1, y0, y1 = min(xs) - 2, max(xs) + 2, min(ys) - 2, max(ys) + 2
        near = [o for o in house.objects.values()
                if o.rect[0] <= x1 and o.rect[0] + max(1, o.rect[2]) - 1 >= x0
                and o.rect[1] <= y1 and o.rect[1] + max(1, o.rect[3]) - 1 >= y0]
        for obj in sorted(near, key=lambda o: o.rect[1]):
            sprites.draw_object(self.background, obj)
        self._built_key = (house.revision, self._lawn_bucket())

    def _draw_labels(self, surface: pygame.Surface) -> None:
        """Noms des pièces en haute résolution, pour rester lisibles après agrandissement."""
        if not self.house.layout.labels:
            return
        font = theme.font(12, bold=True)
        for name, (x0, _y0, _x1, y1) in self.house.rooms.items():
            text = self._label_cache.get(name)
            if text is None:
                text = self._label_cache[name] = font.render(name, True, (250, 248, 240))
            pill = text.get_rect().inflate(10, 2)
            left, bottom = self.to_screen(x0 * TILE, (y1 + 1) * TILE)
            pill.bottomleft = (left + 3, bottom - 3)
            panel = pygame.Surface(pill.size, pygame.SRCALPHA)
            pygame.draw.rect(panel, (30, 26, 32, 150), panel.get_rect(), border_radius=6)
            surface.blit(panel, pill.topleft)
            surface.blit(text, text.get_rect(center=pill.center))

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
        obj = self.house.object_at_spot(agent.pos)
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
        if self._active(agent, "douche") and "douche" in self.house.objects:
            return "shower"  # cabine de douche (au baril d'eau, on reste debout)
        if self._active(agent, "baignade") and "piscine" in self.house.objects:
            return "swimming"
        if self._active(agent, *SITTING_ACTIONS) and agent.pos == agent.action.use_pos and not self.moving.get(agent.id):
            return "sitting"
        return "standing"

    # ------------------------------------------------------------------ coordonnées

    def agent_screen_pos(self, agent: Agent) -> tuple[int, int]:
        if self._pose(agent) == "lying":
            hx, hy = self._head_low_pos(agent)
            return self.to_screen(hx, hy)
        fx, fy = self.display_pos.get(agent.id, agent.pos)
        return self.to_screen(fx * TILE + TILE / 2, fy * TILE + TILE / 2)

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
        self.time_of_day = minute_of_day / 60.0
        low = self.low
        t = self.time
        hour = minute_of_day / 60.0
        built = self._built_key
        if built != (self.house.revision, self._lawn_bucket()):
            lawn_changed = built is not None and built[1] != self._lawn_bucket() and not self.house.layout.wild
            if lawn_changed:
                self.background = self._build_background()  # le gazon a poussé
            else:
                self._refresh_background()                  # achat, arbre coupé
        view = self.view_rect()
        low.set_clip(view)
        low.blit(self.background, view.topleft, view)
        pile = self.house.objects.get("corde_bois")
        if pile is not None:
            sprites.draw_woodpile(low, pile, self.wood)
        car = self.house.objects.get("auto")
        if car is not None and self.car_home:
            sprites.draw_car(low, car)
        if "piscine" in self.house.objects:
            sprites.draw_pool_shimmer(low, self.house.objects["piscine"], t)
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
        self._draw_lighting(low, hour, visible, view)

        # Après l'éclairage, pour rester lisibles la nuit
        for agent, cx, top in overlays:
            bubble_shown = self._draw_feelings(low, agent, cx, top)
            if agent.id == selected_id:
                self._draw_marker(low, cx, top - (12 if bubble_shown else 0))

        low.set_clip(None)
        map_area = pygame.Rect((0, 0), self.size)
        previous_clip = surface.get_clip()
        surface.set_clip(map_area)
        scaled = pygame.transform.scale(low.subsurface(view),
                                        (round(view.w * self.scale), round(view.h * self.scale)))
        surface.fill((20, 22, 26), map_area)
        surface.blit(scaled, (0, 0))
        self._draw_labels(surface)
        for agent in visible:
            if self._pose(agent) == "lying":
                self._draw_zzz(surface, agent)
            elif agent.thinking:
                self._draw_thinking(surface, agent)
        if self.scrollable:
            self._draw_minimap(surface, agents)
        surface.set_clip(previous_clip)

    def _draw_windows(self, low: pygame.Surface, hour: float) -> None:
        sky = sprites.sky_color(hour)
        stars = hour >= 21 or hour < 5
        for x, y, vertical in self.house.layout.windows:
            sprites.draw_window(low, x, y, vertical, on_face=(x, y + 1) in self.house.floor, sky=sky, stars=stars)

    def _draw_memorials(self, low: pygame.Surface, agents: list[Agent]) -> None:
        """Un cadre avec ruban noir par membre décédé, sur la face du mur nord du salon."""
        tiles = self.house.layout.memorial_tiles
        departed = sorted((a for a in agents if a.dead), key=lambda a: a.died_minute or 0)
        for index, agent in enumerate(departed if tiles else []):
            tx, ty = tiles[index % len(tiles)]
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
        fire = objects.get("feu")
        if fire is not None and self._fire_burning(agents):
            steam.append(sprites.draw_flames(low, fire, self.time))
        if any(self._active(a, "bbq") for a in agents) and "bbq" in objects:
            x, y, _w, _h = objects["bbq"].rect
            steam.append((x * TILE + TILE // 2, y * TILE + 4))
        return steam

    def _fire_burning(self, agents: list[Agent]) -> bool:
        hour = self.time_of_day
        return FIRE_HOURS[0] <= hour < FIRE_HOURS[1] or any(self._active(a, "cuisiner", "veiller") for a in agents)

    def _draw_agent(self, low: pygame.Surface, agent: Agent) -> tuple[Agent, int, int]:
        pose = self._pose(agent)
        if pose == "lying" and agent.persona.bed == "tente":
            hx, hy = self._head_low_pos(agent)
            return agent, round(hx), round(hy) - 6  # dans la tente : on ne voit que les « z z »
        if pose == "lying":
            hx, hy = self._head_low_pos(agent)
            sprites.draw_blanket_bump(low, agent.persona.bed, (hx, hy), agent.persona.age < 13)
            head = sprites.sleeping_head(agent.persona)
            rect = head.get_rect(center=(round(hx), round(hy)))
            low.blit(head, rect)
            return agent, rect.centerx, rect.top
        if pose == "swimming":
            center = self._swim_spot(agent)
            sprites.draw_swimmer(low, agent.persona, center, self.time)
            return agent, center[0], center[1] - 6

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

    def _swim_spot(self, agent: Agent) -> tuple[int, int]:
        """Point dans l'eau, un peu à l'intérieur de la piscine depuis la case d'usage."""
        x, y, w, h = self.house.objects["piscine"].rect
        ax, ay = agent.pos
        px = x * TILE + 8 if ax < x else (x + w) * TILE - 8
        py = min(max(ay * TILE + TILE // 2, y * TILE + 8), (y + h) * TILE - 8)
        return px, py

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
        elif self._active(agent, "tondre"):
            sprites.draw_mower(low, left + (12 if direction != "left" else -2), top + 12)
        elif self._active(agent, "couper"):
            sprites.draw_axe(low, hand_x, hand_y, self.time, chainsaw="scie" in self.purchases)
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

    def _draw_lighting(self, low: pygame.Surface, hour: float, agents: list[Agent], view: pygame.Rect) -> None:
        # Lumière dorée en fin d'après-midi, rosée à l'aube
        golden = _triangle(hour, 16.5, 18.5, 20.5) * 45
        dawn = _triangle(hour, 5.5, 6.4, 7.5) * 35
        if golden >= 1:
            self.tint.fill((255, 168, 80, round(golden)), view)
            low.blit(self.tint, view.topleft, view)
        if dawn >= 1:
            self.tint.fill((255, 150, 140, round(dawn)), view)
            low.blit(self.tint, view.topleft, view)

        alpha = _night_alpha(hour)
        if not alpha:
            return
        # Lampes allumées là où quelqu'un est éveillé ; les pièces vides restent dans le noir
        lit = {self.house.room_at(a.pos) for a in agents if a.is_available} & set(self.room_rects)
        self.night.fill((10, 15, 50, alpha), view)
        for room in lit:
            self.night.fill((10, 15, 50, round(alpha * LIT_ROOM_FACTOR)), self.room_rects[room].clip(view))
        low.blit(self.night, view.topleft, view)
        fire = self.house.objects.get("feu")
        if fire is not None and self._fire_burning(agents):
            self._draw_fire_glow(low, fire, alpha)
        strength = min(255, alpha * 2)
        for room in lit:
            glow = self.room_glows[room]
            glow.set_alpha(strength)
            low.blit(glow, self.room_rects[room].topleft)
        if any(self._active(a, "tele") for a in agents) and "tele" in self.house.objects:
            self._draw_tv_glow(low, self.house.objects["tele"], alpha)

    def _draw_fire_glow(self, low: pygame.Surface, fire, alpha: int) -> None:
        x, y, _w, _h = fire.rect
        radius = 34 + int(math.sin(self.time * 7) * 2)
        glow = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        for i in range(5):
            pygame.draw.circle(glow, (255, 170, 90, min(255, alpha // 5 + i * 12)), (radius, radius),
                               radius - i * 6)
        low.blit(glow, (x * TILE + TILE // 2 - radius, y * TILE + TILE // 2 - radius))

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

    # ------------------------------------------------------------------ mini-carte

    def minimap_rect(self) -> pygame.Rect:
        scale = MINIMAP_WIDTH / self.house.width
        rect = pygame.Rect(0, 0, MINIMAP_WIDTH, round(self.house.height * scale))
        rect.bottomleft = (10, self.size[1] - 10)
        return rect

    def minimap_click(self, pos: tuple[int, int]) -> bool:
        """Clic sur la mini-carte : la vue se centre à cet endroit."""
        rect = self.minimap_rect()
        if not self.scrollable or not rect.collidepoint(pos):
            return False
        self.center_on((pos[0] - rect.x) / rect.width * self.house.width,
                       (pos[1] - rect.y) / rect.height * self.house.height)
        return True

    def _build_minimap(self) -> pygame.Surface:
        house = self.house
        surf = pygame.Surface((house.width, house.height))
        surf.fill((86, 140, 70))
        colors = {"dirt": (150, 120, 80), "concrete": (186, 184, 178), "asphalt": (90, 90, 96),
                  "pavers": (170, 146, 120)}
        for pos, kind in house.layout.surfaces.items():
            surf.set_at(pos, colors.get(kind, (150, 150, 150)))
        for pos in house.street:
            surf.set_at(pos, (80, 80, 86))
        for pos in house.water:
            surf.set_at(pos, (70, 130, 200))
        for obj in house.objects.values():
            color = (36, 84, 44) if obj.kind == "arbre" else (190, 150, 100)
            for tile in obj.tiles:
                surf.set_at(tile, color)
        return surf

    def _draw_minimap(self, surface: pygame.Surface, agents: list[Agent]) -> None:
        if self._minimap is None or self._minimap_revision != self.house.revision:
            self._minimap = self._build_minimap()
            self._minimap_revision = self.house.revision
        rect = self.minimap_rect()
        surface.blit(pygame.transform.scale(self._minimap, rect.size), rect.topleft)
        pygame.draw.rect(surface, (240, 236, 220), rect, 1)
        k = rect.width / self.low_size[0]
        view = self.view_rect()
        frame = pygame.Rect(rect.x + view.x * k, rect.y + view.y * k, max(2, view.w * k), max(2, view.h * k))
        pygame.draw.rect(surface, theme.ACCENT, frame.clip(rect), 1)
        for agent in agents:
            if agent.is_away or agent.dead:
                continue
            fx, fy = self.display_pos.get(agent.id, agent.pos)
            pygame.draw.circle(surface, agent.persona.color,
                               (round(rect.x + (fx + 0.5) / self.house.width * rect.width),
                                round(rect.y + (fy + 0.5) / self.house.height * rect.height)), 3)

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
