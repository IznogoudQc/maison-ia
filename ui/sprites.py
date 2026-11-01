"""Pixel art généré dans le code : sols, murs, meubles et personnages (aucun fichier externe).

Tout est dessiné en basse résolution (TILE px par tuile) puis agrandi par le renderer.
"""

from __future__ import annotations

import math
import random

import pygame

from agents.persona import Persona
from world.house import InteractiveObject

TILE = 16
Color = tuple[int, int, int]

OUTLINE: Color = (34, 28, 36)
WALL_TOP: Color = (66, 58, 66)
WALL_FACE: Color = (176, 156, 136)
GLASS: Color = (150, 200, 232)
FRAME: Color = (232, 226, 214)
WOOD: Color = (150, 104, 64)


def shade(color: Color, delta: int) -> Color:
    return tuple(max(0, min(255, c + delta)) for c in color)  # type: ignore[return-value]


def box(surf: pygame.Surface, rect: pygame.Rect, color: Color, outline: int = -55) -> None:
    """Rectangle plein avec un contour 1 px plus foncé."""
    pygame.draw.rect(surf, color, rect)
    pygame.draw.rect(surf, shade(color, outline), rect, 1)


# ====================================================================== sols et murs

FLOOR_STYLES = {
    "Chambre parents": "wood", "Salon": "wood", "Couloir": "wood",
    "Cuisine": "ceramic", "Salle de bain": "ceramic",
    "Chambre ado": "carpet", "Chambre enfant": "carpet",
}


def draw_floor(surf: pygame.Surface, x: int, y: int, style: str, base: Color) -> None:
    t = TILE
    ox, oy = x * t, y * t
    if style == "wood":
        plank = t // 4
        for i in range(4):
            color = shade(base, 5 if (y * 4 + i) % 2 else -5)
            pygame.draw.rect(surf, color, (ox, oy + i * plank, t, plank))
            pygame.draw.line(surf, shade(base, -28), (ox, oy + (i + 1) * plank - 1),
                             (ox + t - 1, oy + (i + 1) * plank - 1))
            # Joints décalés d'une rangée de planches à l'autre
            joint = (x * t + (y * 4 + i) * 11) % (t * 3)
            if joint < t:
                pygame.draw.line(surf, shade(base, -28), (ox + joint, oy + i * plank),
                                 (ox + joint, oy + (i + 1) * plank - 2))
    elif style == "ceramic":
        half = t // 2
        for j in range(2):
            for i in range(2):
                color = base if (x * 2 + i + y * 2 + j) % 2 else shade(base, -14)
                rect = pygame.Rect(ox + i * half, oy + j * half, half, half)
                pygame.draw.rect(surf, color, rect)
                pygame.draw.rect(surf, shade(base, 18), rect, 1)
    else:  # tapis : bruit léger et déterministe
        pygame.draw.rect(surf, base, (ox, oy, t, t))
        rng = random.Random(x * 7919 + y * 104729)
        for _ in range(12):
            delta = rng.choice((-14, -8, 8))
            surf.set_at((ox + rng.randrange(t), oy + rng.randrange(t)), shade(base, delta))


GRASS: Color = (96, 158, 72)


def draw_grass(surf: pygame.Surface, x: int, y: int, lawn: float) -> None:
    """Gazon : plus il est long, plus il est foncé et plein de touffes (et de pissenlits)."""
    t = TILE
    base = shade(GRASS, -int(lawn * 0.25))
    pygame.draw.rect(surf, base, (x * t, y * t, t, t))
    rng = random.Random(x * 92821 + y * 68917)
    tufts = 4 + int(lawn / 8)
    for _ in range(tufts):
        px, py = x * t + rng.randrange(t), y * t + rng.randrange(1, t)
        height = 1 + int(lawn / 35)
        pygame.draw.line(surf, shade(base, 28), (px, py), (px, py - height))
    if lawn >= 60 and rng.random() < (lawn - 50) / 100:
        surf.set_at((x * t + rng.randrange(2, t - 2), y * t + rng.randrange(2, t - 2)), (250, 220, 60))


def draw_surface(surf: pygame.Surface, x: int, y: int, kind: str) -> None:
    """Revêtements extérieurs : asphalte (entrée, rue), béton (trottoir), pavés (allée)."""
    t = TILE
    rect = pygame.Rect(x * t, y * t, t, t)
    rng = random.Random(x * 31 + y * 17)
    if kind == "asphalt" or kind == "street":
        pygame.draw.rect(surf, (78, 78, 84), rect)
        for _ in range(6):
            surf.set_at((rect.x + rng.randrange(t), rect.y + rng.randrange(t)), (96, 96, 102))
        if kind == "street" and x % 3 == 0:
            pygame.draw.rect(surf, (236, 200, 70), (rect.x + 2, rect.centery - 1, t - 4, 2))
    elif kind == "concrete":
        pygame.draw.rect(surf, (196, 194, 188), rect)
        pygame.draw.line(surf, (160, 158, 152), rect.topleft, (rect.left, rect.bottom - 1))
        pygame.draw.line(surf, (170, 168, 162), rect.topleft, (rect.right - 1, rect.top))
    elif kind == "dirt":
        pygame.draw.rect(surf, (156, 124, 86), rect)
        for _ in range(7):
            surf.set_at((rect.x + rng.randrange(t), rect.y + rng.randrange(t)), (132, 104, 72))
    else:  # pavés de l'allée
        pygame.draw.rect(surf, (176, 150, 126), rect)
        for j in range(0, t, 4):
            offset = 0 if (j // 4) % 2 == 0 else 4
            pygame.draw.line(surf, (140, 116, 96), (rect.x, rect.y + j), (rect.right - 1, rect.y + j))
            for i in range(offset, t, 8):
                pygame.draw.line(surf, (140, 116, 96), (rect.x + i, rect.y + j), (rect.x + i, rect.y + j + 3))


def draw_fence(surf: pygame.Surface, x: int, y: int, lawn: float, vertical: bool = False) -> None:
    """Clôture de bois blanchie sur fond de gazon."""
    draw_grass(surf, x, y, lawn)
    t = TILE
    ox, oy = x * t, y * t
    if vertical:
        pygame.draw.line(surf, (226, 220, 206), (ox + 5, oy), (ox + 5, oy + t - 1))
        pygame.draw.line(surf, (226, 220, 206), (ox + 11, oy), (ox + 11, oy + t - 1))
        for j in range(1, t, 4):
            pygame.draw.rect(surf, (240, 236, 224), (ox + 2, oy + j, 12, 2))
        return
    pygame.draw.line(surf, (226, 220, 206), (ox, oy + 5), (ox + t - 1, oy + 5))
    pygame.draw.line(surf, (226, 220, 206), (ox, oy + 11), (ox + t - 1, oy + 11))
    for i in range(1, t, 4):
        pygame.draw.rect(surf, (240, 236, 224), (ox + i, oy + 2, 2, 12))
        surf.set_at((ox + i, oy + 2), (200, 194, 180))


def draw_door_floor(surf: pygame.Surface, x: int, y: int) -> None:
    t = TILE
    pygame.draw.rect(surf, shade(WOOD, 10), (x * t, y * t, t, t))
    for i in range(0, t, 4):
        pygame.draw.line(surf, shade(WOOD, -25), (x * t + i, y * t), (x * t + i, y * t + t - 1))


def draw_wall(surf: pygame.Surface, x: int, y: int, floor_below: bool) -> None:
    """Dessus du mur foncé ; face peinte visible quand le sol est juste au sud."""
    t = TILE
    rect = pygame.Rect(x * t, y * t, t, t)
    pygame.draw.rect(surf, WALL_TOP, rect)
    pygame.draw.line(surf, shade(WALL_TOP, 18), rect.topleft, (rect.right - 1, rect.top))
    if floor_below:
        face = pygame.Rect(rect.x, rect.y + t // 2, t, t // 2)
        pygame.draw.rect(surf, WALL_FACE, face)
        pygame.draw.line(surf, shade(WALL_FACE, 25), face.topleft, (face.right - 1, face.top))
        pygame.draw.line(surf, shade(WALL_FACE, -50), (face.left, face.bottom - 2),
                         (face.right - 1, face.bottom - 2))
        pygame.draw.line(surf, shade(WALL_FACE, -70), (face.left, face.bottom - 1),
                         (face.right - 1, face.bottom - 1))


def draw_window(surf: pygame.Surface, x: int, y: int, vertical: bool, on_face: bool,
                sky: Color = GLASS, stars: bool = False) -> None:
    """Fenêtre dont la vitre prend la couleur du ciel (aube, jour, soir, nuit étoilée)."""
    t = TILE
    if vertical:
        glass = pygame.Rect(x * t + t // 2 - 3, y * t + 2, 6, t - 4)
    elif on_face:
        glass = pygame.Rect(x * t + 3, y * t + t // 2 + 1, t - 6, t // 2 - 4)
    else:
        glass = pygame.Rect(x * t + 2, y * t + t // 2 - 3, t - 4, 6)
    pygame.draw.rect(surf, sky, glass)
    pygame.draw.rect(surf, FRAME, glass, 1)
    if stars:
        surf.set_at((glass.x + 2 + (x + y) % max(1, glass.width - 4), glass.y + 2), (250, 245, 200))
    else:
        surf.set_at((glass.x + 2, glass.y + 2), shade(sky, 50))


SKY_KEYS: list[tuple[float, Color]] = [
    (0.0, (20, 28, 70)), (5.0, (40, 42, 92)), (6.3, (238, 160, 124)), (8.0, (150, 200, 232)),
    (17.0, (150, 200, 232)), (19.0, (238, 150, 92)), (21.0, (40, 42, 92)), (24.0, (20, 28, 70)),
]


def sky_color(hour: float) -> Color:
    """Couleur du ciel interpolée entre des heures clés."""
    for (h0, c0), (h1, c1) in zip(SKY_KEYS, SKY_KEYS[1:]):
        if h0 <= hour <= h1:
            k = (hour - h0) / (h1 - h0)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1))  # type: ignore[return-value]
    return SKY_KEYS[0][1]


# ====================================================================== meubles

BLANKETS: dict[str, Color] = {
    "lit_parents": (92, 120, 178),
    "lit_ado": (124, 78, 160),
    "lit_enfant": (226, 140, 46),
}


def _bed(surf: pygame.Surface, r: pygame.Rect, obj: InteractiveObject) -> None:
    box(surf, r, (118, 82, 52))
    mattress = r.inflate(-4, -4)
    pygame.draw.rect(surf, (238, 234, 226), mattress)
    places = max(1, obj.capacity)
    pillow_w = mattress.width // places - 4
    for i in range(places):
        pillow = pygame.Rect(mattress.x + 2 + i * (mattress.width // places), mattress.y + 1, pillow_w, 5)
        box(surf, pillow, (250, 250, 248), -30)
    blanket = pygame.Rect(mattress.x, mattress.y + 8, mattress.width, mattress.height - 8)
    color = BLANKETS.get(obj.id, (110, 132, 190))
    pygame.draw.rect(surf, color, blanket)
    pygame.draw.line(surf, shade(color, 40), blanket.topleft, (blanket.right - 1, blanket.top))
    for yy in range(blanket.y + 4, blanket.bottom, 5):
        pygame.draw.line(surf, shade(color, -18), (blanket.x + 2, yy), (blanket.right - 3, yy))


def _fridge(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -2), (232, 236, 242), -70)
    inner = r.inflate(-2, -2)
    pygame.draw.line(surf, (190, 196, 206), (inner.centerx, inner.y + 1), (inner.centerx, inner.bottom - 2))
    for dx, color in ((4, (220, 60, 60)), (8, (60, 140, 220)), (inner.width - 6, (240, 190, 40))):
        surf.set_at((inner.x + dx, inner.y + 4), color)


def _stove(surf: pygame.Surface, r: pygame.Rect) -> None:
    inner = r.inflate(-2, -2)
    box(surf, inner, (72, 72, 80))
    for cx in (inner.x + inner.width // 4, inner.x + 3 * inner.width // 4):
        pygame.draw.circle(surf, (40, 40, 44), (cx, inner.centery), 4)
        pygame.draw.circle(surf, (120, 120, 128), (cx, inner.centery), 4, 1)


def _counter(surf: pygame.Surface, r: pygame.Rect) -> None:
    inner = r.inflate(-2, -2)
    box(surf, inner, (184, 150, 112))
    sink = pygame.Rect(0, 0, 12, 8)
    sink.center = inner.center
    box(surf, sink, (170, 186, 200), -50)
    surf.set_at((sink.centerx, sink.y + 1), (90, 96, 104))


def table_plates(r: pygame.Rect) -> list[tuple[int, int]]:
    """Centres des assiettes (une par place) pour une table de rectangle r."""
    inner = r.inflate(-2, -2)
    return [(inner.left + 6, inner.centery), (inner.right - 7, inner.centery),
            (inner.centerx - 4, inner.top + 5), (inner.centerx + 4, inner.bottom - 6)]


def _table(surf: pygame.Surface, r: pygame.Rect) -> None:
    inner = r.inflate(-2, -2)
    box(surf, inner, (146, 100, 62))
    pygame.draw.rect(surf, shade((146, 100, 62), 18), inner.inflate(-4, -4), 1)
    for px, py in table_plates(r):
        pygame.draw.circle(surf, (244, 244, 240), (px, py), 3)
        pygame.draw.circle(surf, (200, 200, 196), (px, py), 3, 1)


def _dresser(surf: pygame.Surface, r: pygame.Rect) -> None:
    inner = r.inflate(-2, -2)
    box(surf, inner, (132, 92, 58))
    pygame.draw.line(surf, shade((132, 92, 58), -40), (inner.centerx, inner.y + 2), (inner.centerx, inner.bottom - 3))
    for cx in (inner.x + inner.width // 4, inner.x + 3 * inner.width // 4):
        surf.set_at((cx, inner.centery), (220, 200, 150))


def _computer(surf: pygame.Surface, r: pygame.Rect) -> None:
    inner = r.inflate(-2, -2)
    box(surf, inner, (150, 110, 72))
    screen = pygame.Rect(inner.x + 4, inner.y + 2, inner.width - 8, 6)
    box(surf, screen, (40, 44, 58), -10)
    pygame.draw.rect(surf, (90, 170, 230), screen.inflate(-2, -2))
    pygame.draw.line(surf, (190, 190, 196), (inner.x + 6, inner.bottom - 3), (inner.right - 7, inner.bottom - 3))


def _toys(surf: pygame.Surface, r: pygame.Rect) -> None:
    inner = r.inflate(-2, -4)
    box(surf, inner, (222, 120, 78))
    pygame.draw.line(surf, shade((222, 120, 78), -45), (inner.x, inner.y + 3), (inner.right - 1, inner.y + 3))
    for i, color in enumerate(((230, 60, 60), (60, 120, 230), (250, 210, 50), (70, 180, 90))):
        pygame.draw.rect(surf, color, (inner.x + 3 + i * 6, inner.y - 2, 3, 2))


def _shower(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.rect(surf, (214, 234, 242), r)
    for i in range(r.x, r.right, 4):
        pygame.draw.line(surf, (190, 214, 226), (i, r.y), (i, r.bottom - 1))
    for j in range(r.y, r.bottom, 4):
        pygame.draw.line(surf, (190, 214, 226), (r.x, j), (r.right - 1, j))
    pygame.draw.circle(surf, (130, 140, 150), r.center, 2)
    pygame.draw.rect(surf, (170, 220, 245), r, 1)
    pygame.draw.line(surf, (240, 250, 255), (r.x, r.bottom - 1), (r.right - 1, r.bottom - 1))


def _toilet(surf: pygame.Surface, r: pygame.Rect) -> None:
    tank = pygame.Rect(r.x + 3, r.y + 1, r.width - 6, 4)
    box(surf, tank, (240, 242, 244), -60)
    bowl = pygame.Rect(r.x + 3, r.y + 5, r.width - 6, r.height - 7)
    pygame.draw.ellipse(surf, (244, 246, 248), bowl)
    pygame.draw.ellipse(surf, (170, 176, 184), bowl, 1)


def _tv(surf: pygame.Surface, r: pygame.Rect) -> None:
    stand = r.inflate(-2, -4)
    box(surf, stand, (110, 76, 50))
    screen = pygame.Rect(r.x + 6, r.y + 2, r.width - 12, 7)
    box(surf, screen, (26, 26, 32), -10)


def draw_tv_screen(surf: pygame.Surface, obj: InteractiveObject, frame: int) -> None:
    """Écran allumé (appelé à chaque image quand quelqu'un regarde la télé)."""
    x, y, w, _h = obj.rect
    screen = pygame.Rect(x * TILE + 7, y * TILE + 3, w * TILE - 14, 5)
    colors = ((120, 180, 236), (150, 210, 160), (230, 190, 120))
    pygame.draw.rect(surf, colors[(frame // 20) % len(colors)], screen)
    surf.set_at((screen.x + 3 + (frame // 6) % (screen.width - 6), screen.y + 2), (255, 255, 255))


def _sofa(surf: pygame.Surface, r: pygame.Rect) -> None:
    color = (156, 62, 62)
    box(surf, r.inflate(0, -2), color)
    body = r.inflate(0, -2)
    back = pygame.Rect(body.x, body.bottom - 5, body.width, 5)
    pygame.draw.rect(surf, shade(color, -30), back)
    for arm_x in (body.x, body.right - 4):
        pygame.draw.rect(surf, shade(color, -20), (arm_x, body.y, 4, body.height))
    for sx in range(body.x + 4 + 14, body.right - 4, 14):
        pygame.draw.line(surf, shade(color, -40), (sx, body.y + 1), (sx, back.y - 1))
    pygame.draw.rect(surf, OUTLINE, body, 1)


def _bookshelf(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r, (112, 76, 46))
    rng = random.Random(42)
    for shelf_y in range(r.y + 2, r.bottom - 2, 8):
        pygame.draw.line(surf, (82, 54, 32), (r.x + 1, shelf_y + 6), (r.right - 2, shelf_y + 6))
        for bx in range(r.x + 2, r.right - 2, 2):
            color = rng.choice(((190, 60, 60), (60, 110, 180), (220, 190, 80), (80, 150, 90), (230, 230, 220)))
            pygame.draw.line(surf, color, (bx, shelf_y + 1 + rng.randrange(2)), (bx, shelf_y + 5))


def _bus_stop(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.line(surf, (120, 120, 128), (r.centerx, r.y + 2), (r.centerx, r.bottom - 1))
    sign = pygame.Rect(r.centerx - 5, r.y - 6, 10, 8)
    box(surf, sign, (40, 110, 200))
    pygame.draw.rect(surf, (250, 250, 250), sign.inflate(-4, -4))


def _shed(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r, (150, 70, 56))
    for yy in range(r.y + 3, r.bottom - 1, 4):
        pygame.draw.line(surf, (120, 52, 42), (r.x + 1, yy), (r.right - 2, yy))
    pygame.draw.line(surf, (90, 40, 32), (r.centerx, r.y), (r.centerx, r.bottom - 1))  # faîte du toit
    door = pygame.Rect(r.centerx - 4, r.bottom - 8, 8, 8)
    box(surf, door, (196, 180, 150))


def _patio(surf: pygame.Surface, r: pygame.Rect) -> None:
    table = r.inflate(-6, -6)
    pygame.draw.ellipse(surf, (236, 236, 230), table)
    pygame.draw.ellipse(surf, (150, 150, 150), table, 1)
    pygame.draw.circle(surf, (230, 90, 70), table.center, 4)  # parasol vu de haut
    pygame.draw.circle(surf, (250, 240, 230), table.center, 4, 1)


def _swing(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.line(surf, (110, 80, 50), (r.x + 1, r.y + 3), (r.right - 2, r.y + 3), 2)
    for px in (r.x + 1, r.right - 3):
        pygame.draw.rect(surf, (110, 80, 50), (px, r.y, 2, r.height))
    seat = pygame.Rect(r.centerx - 4, r.y + 9, 8, 3)
    pygame.draw.line(surf, (90, 90, 90), (seat.x + 1, r.y + 4), (seat.x + 1, seat.y))
    pygame.draw.line(surf, (90, 90, 90), (seat.right - 2, r.y + 4), (seat.right - 2, seat.y))
    box(surf, seat, (200, 60, 60))


def _tree(surf: pygame.Surface, r: pygame.Rect) -> None:
    trunk = pygame.Rect(r.centerx - 2, r.bottom - 8, 4, 7)
    pygame.draw.rect(surf, (100, 70, 44), trunk)
    for dx, dy, radius, color in ((-5, -2, 9, (54, 112, 52)), (6, -1, 8, (60, 124, 56)),
                                  (0, -7, 10, (68, 136, 60)), (0, -3, 7, (84, 156, 70))):
        pygame.draw.circle(surf, color, (r.centerx + dx, r.centery + dy), radius)
    pygame.draw.circle(surf, (110, 176, 86), (r.centerx - 3, r.centery - 9), 3)


def _mailbox(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.line(surf, (110, 80, 50), (r.centerx, r.y + 6), (r.centerx, r.bottom - 1), 2)
    body = pygame.Rect(r.centerx - 4, r.y + 2, 9, 5)
    box(surf, body, (50, 50, 60))
    surf.set_at((body.right - 2, body.y + 1), (220, 50, 50))  # drapeau


def _pool(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r, (210, 214, 220), -60)
    water = r.inflate(-4, -4)
    pygame.draw.rect(surf, (70, 160, 220), water)
    pygame.draw.rect(surf, (110, 190, 236), water, 1)
    ladder = pygame.Rect(r.right - 3, r.centery - 3, 2, 6)
    pygame.draw.rect(surf, (230, 230, 236), ladder)


def draw_pool_shimmer(surf: pygame.Surface, pool: InteractiveObject, t: float) -> None:
    """Reflets qui bougent sur l'eau."""
    x, y, w, h = pool.rect
    water = pygame.Rect(x * TILE + 3, y * TILE + 3, w * TILE - 6, h * TILE - 6)
    rng = random.Random(int(t * 2))
    for _ in range(14):
        px, py = water.x + rng.randrange(water.width - 3), water.y + rng.randrange(water.height)
        pygame.draw.line(surf, (170, 220, 250), (px, py), (px + 2, py))


def _bbq(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.circle(surf, (30, 30, 34), r.center, 6)
    pygame.draw.circle(surf, (70, 70, 76), r.center, 6, 1)
    pygame.draw.line(surf, (90, 90, 96), (r.centerx - 4, r.centery), (r.centerx + 4, r.centery))
    pygame.draw.line(surf, (90, 90, 96), (r.centerx, r.centery - 4), (r.centerx, r.centery + 4))


def draw_car(surf: pygame.Surface, car: InteractiveObject) -> None:
    """Auto vue de dessus, garée dans l'entrée."""
    x, y, w, h = car.rect
    body = pygame.Rect(x * TILE + 3, y * TILE + 2, w * TILE - 6, h * TILE - 4)
    for wx in (body.x - 1, body.right - 2):
        for wy in (body.y + 6, body.bottom - 10):
            pygame.draw.rect(surf, (24, 24, 28), (wx, wy, 3, 6))
    pygame.draw.rect(surf, (178, 40, 44), body, border_radius=5)
    pygame.draw.rect(surf, (110, 20, 24), body, 1, border_radius=5)
    windshield = pygame.Rect(body.x + 3, body.y + 8, body.width - 6, 6)
    pygame.draw.rect(surf, (150, 196, 226), windshield, border_radius=2)
    rear = pygame.Rect(body.x + 3, body.bottom - 12, body.width - 6, 5)
    pygame.draw.rect(surf, (130, 176, 206), rear, border_radius=2)
    for lx in (body.x + 2, body.right - 4):
        pygame.draw.rect(surf, (252, 240, 180), (lx, body.y + 1, 2, 2))


def draw_mower(surf: pygame.Surface, x: int, y: int) -> None:
    pygame.draw.rect(surf, (200, 40, 40), (x, y, 6, 5))
    pygame.draw.rect(surf, (30, 30, 30), (x, y, 6, 5), 1)
    pygame.draw.line(surf, (60, 60, 60), (x + 1, y), (x - 2, y - 5))


def draw_swimmer(surf: pygame.Surface, persona: Persona, center: tuple[int, int], t: float) -> None:
    """Tête qui dépasse de l'eau, avec des ronds dans l'eau."""
    head = character_frames(persona)[("down", 0)].subsurface((0, 0, 16, 9))
    cx, cy = center
    bob = round(math.sin(t * 3) * 1)
    ripple = pygame.Rect(0, 0, 14, 6)
    ripple.center = (cx, cy + 4)
    pygame.draw.ellipse(surf, (150, 206, 240), ripple, 1)
    surf.blit(head, (cx - 8, cy - 6 + bob))



# ---------------------------------------------------------------------- terrain (scénario « terrain »)

TREE_COLORS = {
    "Érable": ((54, 112, 52), (68, 136, 60), (92, 160, 72)),
    "Bouleau": ((96, 150, 70), (120, 172, 84), (150, 196, 104)),
}


def _small_tree(surf: pygame.Surface, r: pygame.Rect, species: str) -> None:
    """Arbre d'une tuile dont le feuillage déborde : en rangées serrées, ça fait une forêt."""
    cx, bottom = r.centerx, r.bottom
    rng = random.Random(r.x * 7 + r.y * 13)
    if species == "Sapin":
        pygame.draw.rect(surf, (90, 62, 40), (cx - 1, bottom - 4, 3, 4))
        for i, (half, color) in enumerate(((8, (34, 86, 52)), (6, (42, 102, 60)), (4, (52, 118, 70)))):
            top = bottom - 7 - i * 5
            pygame.draw.polygon(surf, color, [(cx - half, top + 6), (cx + half, top + 6), (cx, top - 3)])
        return
    trunk = (226, 222, 210) if species == "Bouleau" else (100, 70, 44)
    pygame.draw.rect(surf, trunk, (cx - 1, bottom - 6, 3, 6))
    if species == "Bouleau":
        surf.set_at((cx, bottom - 4), (40, 40, 40))
    dark, mid, light = TREE_COLORS.get(species, TREE_COLORS["Érable"])
    jitter = rng.randint(-1, 1)
    pygame.draw.circle(surf, dark, (cx + jitter, bottom - 9), 8)
    pygame.draw.circle(surf, mid, (cx - 2 + jitter, bottom - 11), 6)
    pygame.draw.circle(surf, light, (cx - 3 + jitter, bottom - 13), 2)


def draw_water(surf: pygame.Surface, x: int, y: int, t: float = 0.0) -> None:
    rect = pygame.Rect(x * TILE, y * TILE, TILE, TILE)
    pygame.draw.rect(surf, (64, 124, 196), rect)
    rng = random.Random(x * 101 + y * 37)
    for _ in range(2):
        px, py = rect.x + rng.randrange(2, TILE - 4), rect.y + rng.randrange(2, TILE - 2)
        pygame.draw.line(surf, (110, 168, 226), (px, py), (px + 3, py))


def _tent(surf: pygame.Surface, r: pygame.Rect) -> None:
    body = r.inflate(-2, -2)
    pygame.draw.polygon(surf, (60, 120, 90), [body.bottomleft, body.bottomright, (body.centerx, body.top - 6)])
    pygame.draw.polygon(surf, (40, 90, 66), [body.bottomleft, body.bottomright, (body.centerx, body.top - 6)], 1)
    pygame.draw.polygon(surf, (36, 60, 48), [(body.centerx - 5, body.bottom), (body.centerx + 5, body.bottom),
                                            (body.centerx, body.top + 4)])  # ouverture
    pygame.draw.line(surf, (200, 200, 190), (body.left - 2, body.bottom), (body.left + 3, body.bottom - 4))
    pygame.draw.line(surf, (200, 200, 190), (body.right + 1, body.bottom), (body.right - 4, body.bottom - 4))


def _campfire(surf: pygame.Surface, r: pygame.Rect) -> None:
    rng = random.Random(r.x + r.y)
    for angle in range(0, 360, 45):
        a = math.radians(angle + rng.randint(-8, 8))
        pygame.draw.circle(surf, (128, 124, 120), (r.centerx + round(math.cos(a) * 6), r.centery + round(math.sin(a) * 5)), 2)
    pygame.draw.line(surf, (110, 70, 40), (r.centerx - 4, r.centery + 2), (r.centerx + 4, r.centery - 2), 2)
    pygame.draw.line(surf, (96, 60, 36), (r.centerx - 4, r.centery - 2), (r.centerx + 4, r.centery + 2), 2)


def draw_flames(surf: pygame.Surface, fire: InteractiveObject, t: float) -> tuple[int, int]:
    """Flammes animées du feu de camp ; renvoie le point d'où monte la fumée."""
    x, y, _w, _h = fire.rect
    cx, cy = x * TILE + TILE // 2, y * TILE + TILE // 2
    for i, (color, height) in enumerate((((236, 96, 40), 6), ((250, 170, 50), 4), ((255, 236, 140), 2))):
        flicker = math.sin(t * 9 + i * 1.7) * 1.5
        top = cy - 4 - height - round(flicker)
        pygame.draw.polygon(surf, color, [(cx - 4 + i, cy + 1), (cx + 4 - i, cy + 1), (cx, top)])
    return cx, cy - 8


def _cooler(surf: pygame.Surface, r: pygame.Rect) -> None:
    body = pygame.Rect(r.x + 2, r.y + 4, r.width - 4, r.height - 6)
    box(surf, body, (210, 60, 56))
    pygame.draw.rect(surf, (244, 244, 240), (body.x, body.y, body.width, 3))
    pygame.draw.line(surf, (60, 60, 60), (body.centerx - 2, body.y - 1), (body.centerx + 2, body.y - 1))


def _picnic_table(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.rect(surf, (128, 92, 58), (r.x, r.y - 3, r.width, 2))   # banc du haut
    pygame.draw.rect(surf, (128, 92, 58), (r.x, r.bottom + 1, r.width, 2))  # banc du bas
    top = pygame.Rect(r.x + 1, r.y + 2, r.width - 2, r.height - 4)
    box(surf, top, (166, 120, 76))
    for xx in range(top.x + 4, top.right - 1, 5):
        pygame.draw.line(surf, (140, 100, 62), (xx, top.y + 1), (xx, top.bottom - 2))


def _barrel(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.ellipse(surf, (60, 90, 140), r.inflate(-3, -3))
    pygame.draw.ellipse(surf, (40, 60, 100), r.inflate(-3, -3), 1)
    pygame.draw.ellipse(surf, (110, 160, 210), r.inflate(-8, -8))


def _outhouse(surf: pygame.Surface, r: pygame.Rect) -> None:
    body = r.inflate(-2, 0)
    box(surf, body, (138, 98, 60))
    pygame.draw.polygon(surf, (90, 60, 40), [(body.x - 1, body.y + 3), (body.right, body.y + 3),
                                            (body.centerx, body.y - 2)])
    pygame.draw.circle(surf, (40, 30, 20), (body.centerx, body.y + 9), 2)  # la lune dans la porte


OBJECT_DRAWERS = {
    "frigo": _fridge, "cuisiniere": _stove, "comptoir": _counter, "table": _table,
    "commode": _dresser, "ordi": _computer, "jouets": _toys, "douche": _shower,
    "toilette": _toilet, "tele": _tv, "canape": _sofa, "biblio": _bookshelf, "porte": _bus_stop,
    "cabanon": _shed, "patio": _patio, "balancoire": _swing, "boite_lettres": _mailbox,
    "piscine": _pool, "bbq": _bbq, "tente": _tent, "feu": _campfire, "glaciere": _cooler,
    "table_pique_nique": _picnic_table, "baril": _barrel, "becosse": _outhouse,
}


def draw_object(surf: pygame.Surface, obj: InteractiveObject) -> None:
    x, y, w, h = obj.rect
    rect = pygame.Rect(x * TILE, y * TILE, w * TILE, h * TILE)
    if obj.kind == "auto":
        return  # dessinée à chaque image : elle part et revient
    if obj.kind == "arbre":
        if w == 1 and h == 1:
            _small_tree(surf, rect, obj.label)
        else:
            _tree(surf, rect)
    elif obj.kind == "lit" and obj.id not in OBJECT_DRAWERS:
        _bed(surf, rect, obj)
    elif obj.id in OBJECT_DRAWERS:
        OBJECT_DRAWERS[obj.id](surf, rect)
    elif w and h:  # les objets sans tuile (places autour du feu) ne se dessinent pas
        box(surf, rect.inflate(-2, -2), (156, 136, 112))


# ====================================================================== personnages
# Grilles 16 colonnes : H cheveux, S peau, E yeux, T chandail, P pantalon, B chaussures

HEADS = {
    "down": ["................", ".....HHHHHH.....", "....HHHHHHHH....", "....HSSSSSSH....",
             "....SSESSESS....", "....SSSSSSSS....", ".....SSSSSS....."],
    "up": ["................", ".....HHHHHH.....", "....HHHHHHHH....", "....HHHHHHHH....",
           "....HHHHHHHH....", "....SHHHHHHS....", ".....SSSSSS....."],
    "left": ["................", ".....HHHHHH.....", "....HHHHHHHH....", "....SSSSHHHH....",
             "....SESSSHHH....", "....SSSSSSHH....", ".....SSSSSS....."],
}
TORSOS = {
    "down": ["....TTTTTTTT....", "...TTTTTTTTTT...", "...STTTTTTTTS...", "...STTTTTTTTS...",
             "....TTTTTTTT...."],
    "left": [".....TTTTTT.....", ".....TTTTTT.....", ".....TTTTTT.....", ".....TSTTTT.....",
             ".....TTTTTT....."],
}
TORSOS["up"] = TORSOS["down"]
LEGS = {
    "down": [
        ["....PPPPPPPP....", "....PPP..PPP....", "....PPP..PPP....", "....BBB..BBB...."],
        ["....PPPPPPPP....", "....PPP..PPP....", "....BBB..PPP....", ".........BBB...."],
        ["....PPPPPPPP....", "....PPP..PPP....", "....PPP..BBB....", "....BBB........."],
    ],
    "left": [
        [".....PPPPPP.....", ".....PPPPPP.....", "......PPPP......", ".....BBBBB......"],
        [".....PPPPPP.....", "....PPP..PPP....", "...PPP....PPP...", "..BBB......BBB.."],
        [".....PPPPPP.....", ".....PPPPPP.....", ".....PPPPP......", "....BBBBB......."],
    ],
}
LEGS["up"] = LEGS["down"]
# Assis : cuisses repliées (vues de face) ou allongées devant soi (de profil)
SIT_LEGS = {
    "down": ["....PPPPPPPP....", "....BBB..BBB...."],
    "up": ["....PPPPPPPP...."],
    "left": ["...PPPPPPPP.....", "...BB..........."],
}
SIT_FRAME = 3   # index de l'image « assis » dans character_frames
EMPTY_ROW = "." * 16
SPRITE_ROWS = 16  # hauteur utile ; une rangée vide est ajoutée pour le contour

# Apparence par persona ; les personas ajoutés ont un style par défaut
STYLES: dict[str, dict] = {
    "pere": {"hair": (92, 62, 38), "pants": (52, 64, 98), "long_hair": False},
    "mere": {"hair": (150, 74, 42), "pants": (70, 54, 78), "long_hair": True},
    "ado": {"hair": (36, 30, 40), "pants": (44, 44, 52), "long_hair": True},
    "enfant": {"hair": (226, 186, 92), "pants": (72, 112, 62), "long_hair": False},
}
DEFAULT_STYLE = {"hair": (84, 64, 48), "pants": (62, 62, 82), "long_hair": False}
SKIN: Color = (242, 204, 170)


def _set(rows: list[str], y: int, cols: range | tuple[int, ...], char: str) -> None:
    row = list(rows[y])
    for x in cols:
        row[x] = char
    rows[y] = "".join(row)


def _long_hair(rows: list[str], direction: str) -> None:
    if direction == "down":
        for y in range(3, 8):
            _set(rows, y, (4, 11), "H")
    elif direction == "up":
        rows[5] = rows[6] = "....HHHHHHHH...."
        _set(rows, 7, range(5, 11), "H")
    else:
        for y in range(3, 7):
            _set(rows, y, range(9, 12), "H")
        _set(rows, 7, (9, 10), "H")


def _body_rows(direction: str, legs: list[str], long_hair: bool, child: bool) -> list[str]:
    rows = list(HEADS[direction] + TORSOS[direction] + legs)
    if long_hair:
        _long_hair(rows, direction)
    if child:
        # Enfant : un rang de torse (et de jambes debout) en moins, grosse tête conservée
        dropped = (8, 13) if len(legs) == 4 else (8,)
        rows = [r for i, r in enumerate(rows) if i not in dropped]
    # Pieds alignés en bas : un personnage assis ou un enfant est plus bas
    rows = [EMPTY_ROW] * (SPRITE_ROWS - len(rows)) + rows
    return rows + [EMPTY_ROW]  # place pour le contour sous les pieds


def _palette(persona: Persona) -> tuple[dict[str, Color], dict]:
    style = {**DEFAULT_STYLE, **STYLES.get(persona.id, {}), **persona.look}
    palette = {
        "H": style["hair"], "S": SKIN, "E": (40, 30, 44),
        "T": tuple(persona.color), "P": style["pants"], "B": (46, 36, 32),
    }
    return palette, style  # type: ignore[return-value]


def sprite_from_rows(rows: list[str], palette: dict[str, Color]) -> pygame.Surface:
    surf = pygame.Surface((len(rows[0]), len(rows)), pygame.SRCALPHA)
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char != ".":
                surf.set_at((x, y), palette[char])
    return surf


def add_outline(surf: pygame.Surface, color: Color = OUTLINE) -> pygame.Surface:
    width, height = surf.get_size()
    out = surf.copy()
    for y in range(height):
        for x in range(width):
            if surf.get_at((x, y)).a:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and surf.get_at((nx, ny)).a:
                    out.set_at((x, y), color)
                    break
    return out


# Caches par id de persona (les modèles pydantic ne sont pas hashables)
_FRAMES: dict[str, dict[tuple[str, int], pygame.Surface]] = {}
_HEADS: dict[str, pygame.Surface] = {}


def character_frames(persona: Persona) -> dict[tuple[str, int], pygame.Surface]:
    """Images (direction, image) : direction parmi down/up/left/right.

    Image 0 = immobile, 1 et 2 = marche, SIT_FRAME = assis.
    """
    if persona.id not in _FRAMES:
        palette, style = _palette(persona)
        child = persona.age < 13
        frames: dict[tuple[str, int], pygame.Surface] = {}
        for direction in ("down", "up", "left"):
            poses = LEGS[direction] + [SIT_LEGS[direction]]
            for frame, legs in enumerate(poses):
                rows = _body_rows(direction, legs, style["long_hair"], child)
                frames[(direction, frame)] = add_outline(sprite_from_rows(rows, palette))
        for frame in range(SIT_FRAME + 1):
            frames[("right", frame)] = pygame.transform.flip(frames[("left", frame)], True, False)
        _FRAMES[persona.id] = frames
    return _FRAMES[persona.id]


def sleeping_head(persona: Persona) -> pygame.Surface:
    """Tête aux yeux fermés, posée sur l'oreiller."""
    if persona.id not in _HEADS:
        palette, style = _palette(persona)
        rows = list(HEADS["down"])
        if style["long_hair"]:
            for y in range(3, 7):
                _set(rows, y, (4, 11), "H")
        rows[4] = rows[4].replace("E", "e")  # yeux fermés
        palette = {**palette, "e": shade(SKIN, -70)}
        _HEADS[persona.id] = add_outline(sprite_from_rows(rows, palette))
    return _HEADS[persona.id]


def draw_blanket_bump(surf: pygame.Surface, bed_id: str, head_center: tuple[float, float], child: bool) -> None:
    """Bosse du corps sous la douillette, sous la tête du dormeur."""
    color = BLANKETS.get(bed_id, (110, 132, 190))
    hx, hy = head_center
    body = pygame.Rect(0, 0, 10, 12 if child else 17)
    body.midtop = (round(hx), round(hy) + 3)
    pygame.draw.ellipse(surf, shade(color, 16), body)
    pygame.draw.ellipse(surf, shade(color, -35), body, 1)


# ====================================================================== icônes d'humeur

ICON_PALETTE: dict[str, Color] = {
    "R": (214, 54, 60), "G": (80, 150, 70), "W": (255, 255, 255), "B": (70, 120, 210),
    "K": (60, 60, 70), "C": (150, 156, 168), "Y": (250, 206, 60),
}
ICONS: dict[str, list[str]] = {
    "hunger": ["...G...", "..G....", ".RRRRR.", "RRRRRRR", "RRRRRWR", "RRRRRRR", ".RRRRR."],
    "energy": ["BBBBBB.", "....B..", "...B...", "..B....", ".B.....", "BBBBBB.", "......."],
    "hygiene": ["...B...", "..BBB..", "..BBB..", ".BBWBB.", ".BBBBB.", ".BBBBB.", "..BBB.."],
    "social": [".KKKKK.", "KWWWWWK", "KWKWKWK", "KWWWWWK", ".KKKKK.", "..K....", ".K....."],
    "fun": ["..CCC..", ".CCCCC.", "CCCCCCC", ".CCCCC.", "..B.B..", ".B.B...", "......."],
    "heart": [".RR.RR.", "RRRRRRR", "RRRRRRR", ".RRRRR.", "..RRR..", "...R..."],
    "star": ["...Y...", "...Y...", "YYYYYYY", ".YYYYY.", "..Y.Y..", ".Y...Y."],
    "health": ["..RRR..", "..RRR..", "RRRRRRR", "RRRRRRR", "RRRRRRR", "..RRR..", "..RRR.."],
}


def draw_memorial(surf: pygame.Surface, x: int, y: int, persona: Persona) -> None:
    """Cadre photo au mur (coin supérieur gauche en x, y) avec un ruban noir en coin."""
    frame = pygame.Rect(x, y, 11, 8)
    box(surf, frame, (150, 110, 60), -50)
    photo = frame.inflate(-2, -2)
    pygame.draw.rect(surf, shade(tuple(persona.color), 60), photo)
    style = STYLES.get(persona.id, DEFAULT_STYLE)
    pygame.draw.rect(surf, style["hair"], (photo.centerx - 2, photo.y, 5, 2))
    pygame.draw.rect(surf, SKIN, (photo.centerx - 2, photo.y + 2, 5, 3))
    pygame.draw.rect(surf, tuple(persona.color), (photo.centerx - 3, photo.bottom - 1, 7, 1))
    # Ruban de deuil en diagonale dans le coin supérieur droit
    pygame.draw.line(surf, (20, 18, 22), (frame.right - 4, frame.y), (frame.right - 1, frame.y + 3))
    pygame.draw.line(surf, (20, 18, 22), (frame.right - 5, frame.y), (frame.right - 1, frame.y + 4))
_ICONS: dict[str, pygame.Surface] = {}


def icon(name: str) -> pygame.Surface:
    if name not in _ICONS:
        _ICONS[name] = sprite_from_rows(ICONS[name], ICON_PALETTE)
    return _ICONS[name]


def draw_mood_bubble(surf: pygame.Surface, name: str, center_x: int, bottom: int) -> None:
    """Petite bulle de pensée pixel contenant l'icône du besoin."""
    bubble = pygame.Rect(0, 0, 11, 10)
    bubble.midbottom = (center_x, bottom - 2)
    pygame.draw.rect(surf, (252, 252, 250), bubble, border_radius=3)
    pygame.draw.rect(surf, OUTLINE, bubble, 1, border_radius=3)
    surf.set_at((center_x, bottom - 2), (252, 252, 250))
    surf.set_at((center_x, bottom - 1), OUTLINE)
    surf.blit(icon(name), (bubble.x + 2, bubble.y + 2))


# ====================================================================== accessoires et effets

_PUFF: pygame.Surface | None = None


def draw_steam(surf: pygame.Surface, x: int, y: int, t: float, count: int = 3, height: int = 10) -> None:
    """Bouffées de vapeur qui montent en ondulant puis s'estompent."""
    global _PUFF
    if _PUFF is None:
        _PUFF = pygame.Surface((5, 5), pygame.SRCALPHA)
        pygame.draw.circle(_PUFF, (245, 245, 250, 210), (2, 2), 2)
    for i in range(count):
        phase = (t * 0.7 + i / count) % 1.0
        px = x + round(math.sin(phase * 6.3 + i) * 2)
        py = y - round(phase * height)
        _PUFF.set_alpha(round(255 * (1 - phase)))
        surf.blit(_PUFF, (px - 2, py - 2))


def draw_floating(surf: pygame.Surface, name: str, x: int, y: int, t: float, period: float = 1.6) -> None:
    """Icône (cœur, étoile) qui s'élève au-dessus d'un personnage et disparaît."""
    phase = (t / period) % 1.0
    image = icon(name)
    image.set_alpha(round(255 * (1 - phase)))
    surf.blit(image, (x - image.get_width() // 2, y - round(phase * 8) - image.get_height()))
    image.set_alpha(255)


def draw_phone(surf: pygame.Surface, x: int, y: int, t: float) -> None:
    pygame.draw.rect(surf, (30, 30, 36), (x, y, 3, 4))
    glow = (120, 200, 255) if int(t * 3) % 4 else (200, 240, 255)
    pygame.draw.rect(surf, glow, (x + 1, y + 1, 1, 2))


def draw_book(surf: pygame.Surface, x: int, y: int) -> None:
    pygame.draw.rect(surf, (246, 244, 236), (x, y, 7, 4))
    pygame.draw.rect(surf, (150, 60, 50), (x, y, 7, 4), 1)
    pygame.draw.line(surf, (150, 60, 50), (x + 3, y), (x + 3, y + 3))


LEGO_COLORS: list[Color] = [(230, 60, 60), (60, 120, 230), (250, 210, 50), (70, 180, 90), (240, 240, 240)]


def draw_lego(surf: pygame.Surface, cx: int, cy: int) -> None:
    """Briques éparpillées autour de l'enfant (disposition fixe)."""
    for i, (dx, dy) in enumerate(((-9, 3), (7, 5), (-5, 7), (10, -1), (2, 8), (-11, -2))):
        pygame.draw.rect(surf, LEGO_COLORS[i % len(LEGO_COLORS)], (cx + dx, cy + dy, 3, 2))


def draw_mug(surf: pygame.Surface, x: int, y: int) -> None:
    pygame.draw.rect(surf, (240, 240, 236), (x, y, 3, 3))
    surf.set_at((x + 1, y + 1), (110, 70, 40))
    surf.set_at((x + 3, y + 1), (240, 240, 236))


def draw_food(surf: pygame.Surface, plate: tuple[int, int], dinner: bool) -> None:
    px, py = plate
    if dinner:  # spaghat' sauce tomate
        pygame.draw.circle(surf, (236, 200, 120), (px, py), 2)
        surf.set_at((px, py), (200, 60, 40))
    else:       # rôties
        pygame.draw.rect(surf, (210, 160, 90), (px - 1, py - 1, 3, 3))


def draw_pan(surf: pygame.Surface, stove: InteractiveObject) -> tuple[int, int]:
    """Poêle sur le rond gauche ; renvoie le point d'où monte la vapeur."""
    x, y, w, _h = stove.rect
    cx, cy = x * TILE + 1 + (w * TILE - 2) // 4, y * TILE + TILE // 2
    pygame.draw.circle(surf, (50, 50, 56), (cx, cy), 4)
    pygame.draw.circle(surf, (200, 170, 90), (cx, cy), 2)
    pygame.draw.line(surf, (50, 50, 56), (cx + 4, cy), (cx + 8, cy))
    return cx, cy - 3


def draw_fridge_open(surf: pygame.Surface, fridge: InteractiveObject) -> None:
    x, y, w, h = fridge.rect
    door = pygame.Rect(x * TILE + 1, (y + h) * TILE - 2, w * TILE // 2, 4)
    box(surf, door, (232, 236, 242), -70)
    pygame.draw.line(surf, (255, 250, 200), (door.x + 2, door.y + 1), (door.right - 3, door.y + 1))


def draw_computer_screen(surf: pygame.Surface, computer: InteractiveObject, t: float) -> None:
    x, y, w, _h = computer.rect
    screen = pygame.Rect(x * TILE + 6, y * TILE + 4, w * TILE - 12, 4)
    pygame.draw.rect(surf, (30, 60, 90), screen)
    rng = random.Random(int(t * 4))
    for _ in range(5):
        surf.set_at((screen.x + rng.randrange(screen.width), screen.y + rng.randrange(screen.height)),
                    rng.choice(((120, 230, 140), (240, 200, 80), (140, 200, 255))))
