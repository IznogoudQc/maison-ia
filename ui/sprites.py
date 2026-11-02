"""Décor de fond dessiné dans le code : sols, murs, fenêtres, ombres, icônes (aucun fichier externe).

Tout est dessiné en basse résolution (TILE px par tuile) puis agrandi par le renderer. Les personnages,
meubles, arbres et éléments animés sont dessinés en haute résolution (ui/pawns.py, ui/props.py,
ui/living.py) ; les dessins d'objets d'ici servent de repli pour un objet inconnu et pour les ombres.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

import pygame

from agents.persona import Persona
from world.house import InteractiveObject

TILE = 16
Color = tuple[int, int, int]

OUTLINE: Color = (34, 28, 36)
WALL_TOP: Color = (172, 162, 146)    # dessus du mur (plâtre et pierre)
WALL_FACE: Color = (120, 108, 96)    # courte face visible au-dessus d'un plancher
EARTH: Color = (128, 116, 98)      # teinte vers laquelle on adoucit les couleurs (palette terreuse)
SHADOW_ALPHA = 70
GLASS: Color = (150, 200, 232)
FRAME: Color = (232, 226, 214)
WOOD: Color = (150, 104, 64)


def shade(color: Color, delta: int) -> Color:
    return tuple(max(0, min(255, c + delta)) for c in color)  # type: ignore[return-value]


def mute(color: Color, k: float = 0.2) -> Color:
    """Couleur adoucie : un peu ramenée vers une teinte terreuse, moins saturée."""
    return tuple(round(c + (e - c) * k) for c, e in zip(color, EARTH))  # type: ignore[return-value]


def _noise(x: int, y: int, salt: int = 0) -> float:
    """Valeur pseudo-aléatoire stable dans [-1, 1] pour une case (pas de motif répété)."""
    n = (x * 374761393 + y * 668265263 + salt * 2147483647) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 32767.5 - 1.0


def _smooth_noise(x: int, y: int, cell: int, salt: int = 0) -> float:
    """Bruit lissé (interpolé entre les coins d'une grande cellule) : des taches douces, pas des carrés."""
    gx, gy = x / cell, y / cell
    x0, y0 = math.floor(gx), math.floor(gy)
    fx, fy = gx - x0, gy - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    top = _noise(x0, y0, salt) * (1 - fx) + _noise(x0 + 1, y0, salt) * fx
    bottom = _noise(x0, y0 + 1, salt) * (1 - fx) + _noise(x0 + 1, y0 + 1, salt) * fx
    return top * (1 - fy) + bottom * fy


@lru_cache(maxsize=256)
def _shadow_image(width: int, height: int, ellipse: bool, alpha: int) -> pygame.Surface:
    image = pygame.Surface((max(1, width), max(1, height)), pygame.SRCALPHA)
    if ellipse:
        pygame.draw.ellipse(image, (20, 16, 18, alpha), image.get_rect())
    else:
        pygame.draw.rect(image, (20, 16, 18, alpha), image.get_rect(), border_radius=3)
    return image


def draw_shadow(surf: pygame.Surface, rect: pygame.Rect, ellipse: bool = False, alpha: int = SHADOW_ALPHA,
                offset: tuple[int, int] = (2, 3)) -> None:
    """Ombre douce et translucide, décalée vers le bas à droite (lumière venant du nord-ouest)."""
    surf.blit(_shadow_image(rect.width, rect.height, ellipse, alpha), (rect.x + offset[0], rect.y + offset[1]))


def draw_wall_shade(surf: pygame.Surface, x: int, y: int, north: bool, west: bool) -> None:
    """Le mur jette son ombre sur le plancher juste au sud et à l'est de lui."""
    t = TILE
    if north:
        surf.blit(_shadow_image(t, 4, False, 60), (x * t, y * t))
        surf.blit(_shadow_image(t, 2, False, 40), (x * t, y * t + 4))
    if west:
        surf.blit(_shadow_image(3, t, False, 50), (x * t, y * t))


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
    base = mute(base)
    rng = random.Random(x * 7919 + y * 104729)
    if style == "wood":
        plank = t // 4
        span = t * 3                       # longueur d'une planche
        for i in range(4):
            row = y * 4 + i
            start = (row * 11) % span      # les joints sont décalés d'une rangée à l'autre
            top = oy + i * plank
            # Une planche après l'autre le long de la rangée, chacune avec son ton
            px = ox
            while px < ox + t:
                index = (px - start) // span
                end = min(ox + t, start + (index + 1) * span)
                color = shade(base, round(_noise(index, row, 1) * 9))
                pygame.draw.rect(surf, color, (px, top, end - px, plank))
                gx = px + rng.randrange(max(1, end - px))
                pygame.draw.line(surf, shade(color, -10), (gx, top + 1), (min(end - 1, gx + 3), top + 1))
                if end < ox + t:
                    pygame.draw.line(surf, shade(base, -30), (end, top), (end, top + plank - 2))
                px = end
            pygame.draw.line(surf, shade(base, -30), (ox, top + plank - 1), (ox + t - 1, top + plank - 1))
    elif style == "ceramic":
        half = t // 2
        grout = shade(base, -34)
        pygame.draw.rect(surf, grout, (ox, oy, t, t))
        for j in range(2):
            for i in range(2):
                tone = round(_noise(x * 2 + i, y * 2 + j, 2) * 5)
                tile = pygame.Rect(ox + i * half, oy + j * half, half - 1, half - 1)
                pygame.draw.rect(surf, shade(base, tone), tile)
                pygame.draw.line(surf, shade(base, tone + 14), tile.topleft, (tile.right - 2, tile.top))
                surf.set_at((tile.right - 1, tile.bottom - 1), shade(base, tone - 10))
    else:  # tapis : tissage fin et bruit léger
        pygame.draw.rect(surf, base, (ox, oy, t, t))
        for k in range(0, t, 4):
            pygame.draw.line(surf, shade(base, -6), (ox + k, oy), (ox + k, oy + t - 1))
        for _ in range(18):
            delta = rng.choice((-14, -8, 8, 10))
            surf.set_at((ox + rng.randrange(t), oy + rng.randrange(t)), shade(base, delta))


GRASS: Color = (98, 132, 66)


def draw_grass(surf: pygame.Surface, x: int, y: int, lawn: float) -> None:
    """Gazon : plus il est long, plus il est foncé et plein de touffes (et de pissenlits)."""
    t = TILE
    # Grandes plaques plus claires ou plus foncées : le terrain n'a pas l'air d'un damier
    patch = round(_smooth_noise(x, y, 5, 3) * 6 + _smooth_noise(x, y, 13, 4) * 5)
    base = shade(GRASS, patch - int(lawn * 0.22))
    pygame.draw.rect(surf, base, (x * t, y * t, t, t))
    rng = random.Random(x * 92821 + y * 68917)
    for _ in range(5):  # terre et brins secs
        surf.set_at((x * t + rng.randrange(t), y * t + rng.randrange(t)), shade(base, rng.choice((-14, 12))))
    tufts = 4 + int(lawn / 8)
    for _ in range(tufts):
        px, py = x * t + rng.randrange(t), y * t + rng.randrange(1, t)
        height = 1 + int(lawn / 35)
        pygame.draw.line(surf, shade(base, 18), (px, py), (px, py - height))
    if lawn >= 60 and rng.random() < (lawn - 50) / 100:
        surf.set_at((x * t + rng.randrange(2, t - 2), y * t + rng.randrange(2, t - 2)), (250, 220, 60))


SNOW: Color = (234, 238, 245)


def draw_snow(surf: pygame.Surface, x: int, y: int, level: int) -> None:
    """Neige : 1 = mince (le sol perce par endroits), 2 et 3 = couche épaisse, bancs bleutés."""
    t = TILE
    rng = random.Random(x * 7919 + y * 104729)
    drift = round(_smooth_noise(x, y, 6, 9) * 8)
    base = shade(SNOW, drift - (6 if level == 1 else 0))
    pygame.draw.rect(surf, base, (x * t, y * t, t, t))
    if level == 1:
        for _ in range(6):  # brins d'herbe et terre qui percent
            surf.set_at((x * t + rng.randrange(t), y * t + rng.randrange(t)), shade(GRASS, -10))
    for _ in range(4 + level * 2):  # ombres bleutées et reflets
        px, py = x * t + rng.randrange(t), y * t + rng.randrange(t)
        surf.set_at((px, py), (206, 216, 232) if rng.random() < 0.6 else (252, 252, 255))


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
        dirt = shade((146, 120, 88), round(_smooth_noise(x, y, 4, 5) * 6))
        pygame.draw.rect(surf, dirt, rect)
        for _ in range(9):
            surf.set_at((rect.x + rng.randrange(t), rect.y + rng.randrange(t)), shade(dirt, rng.choice((-20, -12, 10))))
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


def draw_wall(surf: pygame.Surface, x: int, y: int, floor_below: bool,
              open_sides: frozenset[str] = frozenset()) -> None:
    """Mur plein vu de dessus : dessus clair, liseré clair au nord-ouest, bord foncé au sud-est.

    open_sides : côtés (n, s, e, o) qui ne touchent pas un autre mur. Quand le plancher est juste au sud,
    on voit en plus une courte face du mur, qui donne l'impression de hauteur.
    """
    t = TILE
    rect = pygame.Rect(x * t, y * t, t, t)
    top = shade(WALL_TOP, round(_noise(x, y, 6) * 3))
    pygame.draw.rect(surf, top, rect)
    rng = random.Random(x * 3301 + y * 7717)
    for _ in range(4):  # crépi
        surf.set_at((rect.x + rng.randrange(t), rect.y + rng.randrange(t)), shade(top, rng.choice((-8, 6))))
    if "n" in open_sides:
        pygame.draw.line(surf, shade(top, 26), rect.topleft, (rect.right - 1, rect.top))
    if "o" in open_sides:
        pygame.draw.line(surf, shade(top, 18), rect.topleft, (rect.left, rect.bottom - 1))
    if "e" in open_sides:
        pygame.draw.line(surf, shade(top, -40), (rect.right - 1, rect.top), (rect.right - 1, rect.bottom - 1))
    if floor_below:
        face = pygame.Rect(rect.x, rect.bottom - 5, t, 5)
        pygame.draw.rect(surf, WALL_FACE, face)
        pygame.draw.line(surf, shade(top, -45), face.topleft, (face.right - 1, face.top))
        pygame.draw.line(surf, shade(WALL_FACE, -45), (face.left, face.bottom - 1), (face.right - 1, face.bottom - 1))
    elif "s" in open_sides:
        pygame.draw.line(surf, shade(top, -45), (rect.left, rect.bottom - 1), (rect.right - 1, rect.bottom - 1))


def draw_window(surf: pygame.Surface, x: int, y: int, vertical: bool, on_face: bool,
                sky: Color = GLASS, stars: bool = False) -> None:
    """Fenêtre dont la vitre prend la couleur du ciel (aube, jour, soir, nuit étoilée)."""
    t = TILE
    if vertical:
        glass = pygame.Rect(x * t + t // 2 - 3, y * t + 2, 6, t - 4)
    elif on_face:
        glass = pygame.Rect(x * t + 2, y * t + 4, t - 4, 6)
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
    for dx, dy, radius, color in ((-5, -2, 9, (48, 94, 50)), (6, -1, 8, (54, 106, 54)),
                                  (0, -7, 10, (62, 116, 58)), (0, -3, 7, (76, 134, 66))):
        pygame.draw.circle(surf, color, (r.centerx + dx, r.centery + dy), radius)
    pygame.draw.circle(surf, (100, 152, 80), (r.centerx - 3, r.centery - 9), 3)


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


# ---------------------------------------------------------------------- terrain (scénario « terrain »)

TREE_COLORS = {
    "Érable": ((48, 94, 50), (62, 114, 58), (84, 136, 70)),
    "Bouleau": ((86, 126, 64), (106, 146, 76), (134, 166, 96)),
}


def _small_tree(surf: pygame.Surface, r: pygame.Rect, species: str) -> None:
    """Arbre d'une tuile dont le feuillage déborde : en rangées serrées, ça fait une forêt."""
    cx, bottom = r.centerx, r.bottom
    rng = random.Random(r.x * 7 + r.y * 13)
    if species == "Sapin":
        pygame.draw.rect(surf, (90, 62, 40), (cx - 1, bottom - 4, 3, 4))
        for i, (half, color) in enumerate(((8, (34, 78, 50)), (6, (42, 94, 58)), (4, (54, 110, 68)))):
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


def draw_stake_line(surf: pygame.Surface, rect: pygame.Rect, ready: bool) -> None:
    """Plan au sol : piquets aux coins et corde tendue en pointillés (terrain défriché : sol gratté)."""
    if ready:
        scratch = pygame.Surface(rect.size, pygame.SRCALPHA)
        scratch.fill((170, 136, 96, 90))
        surf.blit(scratch, rect.topleft)
    color = (250, 240, 200)
    for x in range(rect.left, rect.right, 4):
        surf.fill(color, (x, rect.top, 2, 1))
        surf.fill(color, (x, rect.bottom - 1, 2, 1))
    for y in range(rect.top, rect.bottom, 4):
        surf.fill(color, (rect.left, y, 1, 2))
        surf.fill(color, (rect.right - 1, y, 1, 2))
    for cx, cy in (rect.topleft, (rect.right - 2, rect.top), (rect.left, rect.bottom - 4),
                   (rect.right - 2, rect.bottom - 4)):
        surf.fill((120, 84, 50), (cx, cy - 2, 2, 5))


def draw_construction(surf: pygame.Surface, outer: tuple[int, int, int, int], fraction: float,
                      contractor: bool) -> None:
    """Chantier : dalle de béton, charpente qui monte le long des murs, pile de planches."""
    x0, y0, x1, y1 = outer
    slab = pygame.Rect((x0 + 1) * TILE, (y0 + 1) * TILE, (x1 - x0 - 1) * TILE, (y1 - y0 - 1) * TILE)
    pygame.draw.rect(surf, (178, 176, 168), slab)
    for gx in range(slab.left, slab.right, TILE):
        pygame.draw.line(surf, (160, 158, 150), (gx, slab.top), (gx, slab.bottom - 1))
    ring = ([(x, y0) for x in range(x0, x1 + 1)] + [(x1, y) for y in range(y0 + 1, y1 + 1)]
            + [(x, y1) for x in range(x1 - 1, x0 - 1, -1)] + [(x0, y) for y in range(y1 - 1, y0, -1)])
    built = int(len(ring) * min(1.0, fraction * 1.25))  # la charpente précède la finition
    for x, y in ring[:built]:
        r = pygame.Rect(x * TILE, y * TILE, TILE, TILE)
        pygame.draw.rect(surf, (206, 168, 110), (r.x, r.y + 2, TILE, 2))      # lisse du haut
        pygame.draw.rect(surf, (206, 168, 110), (r.x, r.bottom - 3, TILE, 2))  # lisse du bas
        for sx in (r.x + 2, r.x + 8, r.x + 14):
            pygame.draw.line(surf, (176, 132, 80), (sx, r.y + 2), (sx, r.bottom - 2))  # montants
    if fraction > 0.6:  # la toiture commence : contreplaqué sur la dalle
        roof = slab.copy()
        roof.height = int(slab.height * (fraction - 0.6) / 0.4)
        pygame.draw.rect(surf, (196, 160, 112), roof)
    pile = pygame.Rect(slab.right - 14, slab.bottom - 8, 12, 6)
    for i in range(3):
        pygame.draw.rect(surf, (214, 178, 120), (pile.x, pile.y + i * 2, pile.width, 2))
    if contractor:  # pancarte de l'entrepreneur
        sign = pygame.Rect((x1 + 1) * TILE + 2, y1 * TILE - 2, 12, 8)
        pygame.draw.line(surf, (110, 80, 50), (sign.centerx, sign.bottom), (sign.centerx, sign.bottom + 6))
        box(surf, sign, (240, 200, 40))
        pygame.draw.line(surf, (40, 40, 40), (sign.x + 2, sign.centery), (sign.right - 3, sign.centery))


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


def _workbench(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -4), (150, 108, 66))
    pygame.draw.line(surf, (90, 90, 96), (r.x + 4, r.centery - 1), (r.x + 10, r.centery - 1), 2)  # marteau
    pygame.draw.rect(surf, (200, 60, 50), (r.right - 9, r.centery - 2, 5, 3))                   # coffre à outils


# Meubles de la maison bâtie sur le terrain : ids générés, on les reconnaît par type puis par nom
def _crib(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -2), (230, 214, 186))
    pygame.draw.rect(surf, (250, 248, 240), r.inflate(-5, -5))
    for x in range(r.x + 3, r.right - 2, 3):
        pygame.draw.line(surf, (170, 140, 100), (x, r.y + 1), (x, r.y + 3))  # barreaux


def _console(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, pygame.Rect(r.x + 3, r.y + 6, 10, 5), (40, 40, 48))
    pygame.draw.circle(surf, (80, 200, 120), (r.x + 6, r.y + 8), 1)
    pygame.draw.rect(surf, (230, 230, 236), (r.x + 9, r.y + 12, 5, 3))  # manette


def _piano(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -4), (40, 28, 26))
    keys = pygame.Rect(r.x + 2, r.bottom - 6, r.width - 4, 3)
    pygame.draw.rect(surf, (245, 245, 240), keys)
    for x in range(keys.x + 2, keys.right, 3):
        surf.set_at((x, keys.y), (20, 20, 20))


def _trampoline(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.ellipse(surf, (40, 110, 200), r.inflate(-2, -2))
    pygame.draw.ellipse(surf, (20, 20, 26), r.inflate(-7, -7))


def _hammock(surf: pygame.Surface, r: pygame.Rect) -> None:
    for x in (r.x + 1, r.right - 3):
        pygame.draw.rect(surf, (110, 80, 50), (x, r.y + 2, 2, r.height - 4))
    pygame.draw.arc(surf, (210, 80, 60), pygame.Rect(r.x + 2, r.y - 2, r.width - 4, r.height), 3.4, 6.0, 3)


def _spa(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -2), (150, 110, 80))
    pygame.draw.rect(surf, (90, 180, 220), r.inflate(-6, -6))


def _garden(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.rect(surf, (110, 80, 52), r.inflate(-2, -2))
    for y in range(r.y + 4, r.bottom - 2, 5):
        for x in range(r.x + 4, r.right - 2, 5):
            pygame.draw.circle(surf, (70, 160, 70), (x, y), 2)
            surf.set_at((x + 1, y - 1), (220, 60, 50))  # une tomate


def _coop(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, pygame.Rect(r.x + 2, r.y + 2, r.width - 4, r.height // 2), (170, 60, 48))
    pygame.draw.rect(surf, (210, 200, 180), (r.x + 2, r.centery, r.width - 4, r.height // 2 - 2), 1)
    for x in (r.x + 7, r.x + 16, r.x + 23):
        pygame.draw.circle(surf, (250, 248, 240), (x, r.bottom - 6), 2)


def _solar(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -4), (40, 60, 110))
    for x in range(r.x + 5, r.right - 2, 5):
        pygame.draw.line(surf, (120, 150, 210), (x, r.y + 3), (x, r.bottom - 4))


def _freezer(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -4), (232, 236, 240))
    pygame.draw.line(surf, (160, 170, 180), (r.x + 4, r.centery), (r.right - 5, r.centery))


KIND_DRAWERS = {"berceau": _crib, "console": _console, "piano": _piano, "trampoline": _trampoline,
                "hamac": _hammock, "spa": _spa, "potager": _garden, "poulailler": _coop, "frigo": _fridge, "cuisiniere": _stove, "table": _table, "douche": _shower, "tele": _sofa,
                "livres": _bookshelf, "ordi": _computer, "jouets": _toys}
LABEL_DRAWERS = {"Panneaux": _solar, "Congélateur": _freezer, "Comptoir": _counter, "Toilette": _toilet, "Télé": _tv, "Commode": _dresser, "Établi": _workbench}


# Lot G3
def _espresso(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, pygame.Rect(r.x + 4, r.y + 4, 8, 9), (60, 60, 66))
    pygame.draw.rect(surf, (230, 230, 236), (r.x + 6, r.y + 10, 3, 3))  # la tasse


def _wood_stove(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-4, -4), (44, 40, 40))
    pygame.draw.rect(surf, (230, 120, 40), (r.x + 5, r.y + 8, 6, 4))
    pygame.draw.rect(surf, (70, 66, 66), (r.centerx - 1, r.y, 3, 3))  # le tuyau


def _washer(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-3, -3), (236, 238, 242))
    pygame.draw.circle(surf, (110, 150, 200), r.center, 4)
    pygame.draw.circle(surf, (80, 90, 100), r.center, 4, 1)


def _well(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.circle(surf, (130, 130, 136), r.center, 6)
    pygame.draw.circle(surf, (40, 70, 110), r.center, 4)
    pygame.draw.line(surf, (110, 80, 50), (r.x + 2, r.y + 2), (r.right - 3, r.y + 2), 2)


def _fire_pit(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.circle(surf, (120, 120, 126), r.center, min(r.width, r.height) // 2 - 3)
    pygame.draw.circle(surf, (60, 46, 40), r.center, min(r.width, r.height) // 2 - 6)
    pygame.draw.line(surf, (150, 104, 62), (r.centerx - 4, r.centery + 2), (r.centerx + 4, r.centery - 2), 2)


def _exercise_bike(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.line(surf, (60, 60, 66), (r.x + 3, r.bottom - 4), (r.right - 4, r.bottom - 4), 2)
    pygame.draw.circle(surf, (200, 60, 50), (r.right - 5, r.centery + 1), 3)
    pygame.draw.line(surf, (60, 60, 66), (r.x + 5, r.bottom - 4), (r.x + 6, r.y + 4), 2)


def _desk(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -6), (170, 128, 84))
    pygame.draw.rect(surf, (245, 245, 240), (r.x + 4, r.y + 5, 5, 4))  # un cahier


def _bunk_bed(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -2), (150, 108, 66))
    half = r.height // 2
    for y in (r.y + 2, r.y + half + 1):
        pygame.draw.rect(surf, (90, 130, 200), (r.x + 3, y, r.width - 6, half - 3))
    pygame.draw.line(surf, (110, 80, 50), (r.right - 3, r.y + 2), (r.right - 3, r.bottom - 3))


def _pool_table(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -4), (110, 70, 40))
    felt = r.inflate(-6, -8)
    pygame.draw.rect(surf, (40, 130, 70), felt)
    for color, dx in (((250, 248, 240), 4), ((220, 40, 40), 10), ((240, 200, 40), 14)):
        pygame.draw.circle(surf, color, (felt.x + dx, felt.centery), 1)


def _foosball(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -4), (70, 120, 70))
    for x in range(r.x + 5, r.right - 3, 6):
        pygame.draw.line(surf, (200, 200, 206), (x, r.y + 2), (x, r.bottom - 3))


def _ping_pong(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -4), (30, 80, 150))
    pygame.draw.line(surf, (250, 250, 250), (r.centerx, r.y + 2), (r.centerx, r.bottom - 3))


def _home_theater(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, pygame.Rect(r.x + 2, r.y + 2, r.width - 4, r.height - 6), (24, 24, 30))
    pygame.draw.rect(surf, (80, 120, 200), (r.x + 4, r.y + 4, r.width - 8, r.height - 10))
    for x in (r.x + 1, r.right - 4):
        pygame.draw.rect(surf, (50, 50, 56), (x, r.bottom - 5, 3, 4))  # les haut-parleurs


def _aquarium(surf: pygame.Surface, r: pygame.Rect) -> None:
    box(surf, r.inflate(-2, -5), (70, 70, 76))
    pygame.draw.rect(surf, (90, 170, 220), r.inflate(-4, -7))
    surf.set_at((r.x + 5, r.centery), (250, 140, 40))
    surf.set_at((r.x + 10, r.centery + 1), (250, 220, 60))


def _beehive(surf: pygame.Surface, r: pygame.Rect) -> None:
    for i, y in enumerate(range(r.y + 4, r.bottom - 3, 3)):
        pygame.draw.rect(surf, (240, 200, 60) if i % 2 else (220, 170, 40), (r.x + 4, y, r.width - 8, 3))


def _sugar_shack(surf: pygame.Surface, r: pygame.Rect) -> None:
    body = pygame.Rect(r.x + 3, r.y + 8, r.width - 6, r.height - 10)
    box(surf, body, (130, 86, 52))
    pygame.draw.polygon(surf, (170, 50, 40), [(body.x - 2, body.y), (body.right + 1, body.y), (body.centerx, r.y + 2)])
    pygame.draw.rect(surf, (90, 60, 40), (body.centerx - 2, body.bottom - 6, 4, 6))
    pygame.draw.rect(surf, (210, 210, 216), (body.right - 5, r.y + 1, 2, 5))  # cheminée de vapeur


def _kayak(surf: pygame.Surface, r: pygame.Rect) -> None:
    pygame.draw.ellipse(surf, (230, 120, 30), r.inflate(-6, -2))
    pygame.draw.ellipse(surf, (40, 40, 46), pygame.Rect(r.centerx - 2, r.centery - 3, 4, 6))


def _doghouse(surf: pygame.Surface, r: pygame.Rect) -> None:
    body = pygame.Rect(r.x + 2, r.y + 6, r.width - 4, r.height - 7)
    box(surf, body, (170, 120, 70))
    pygame.draw.polygon(surf, (150, 50, 40), [(body.x - 1, body.y), (body.right, body.y), (body.centerx, r.y + 1)])
    pygame.draw.ellipse(surf, (40, 30, 24), (body.centerx - 3, body.bottom - 6, 6, 6))


KIND_DRAWERS.update({"cafe": _espresso, "foyer": _fire_pit, "exercice": _exercise_bike, "etude": _desk,
                     "billard": _pool_table, "babyfoot": _foosball, "pingpong": _ping_pong,
                     "cinema": _home_theater, "aquarium": _aquarium, "ruche": _beehive,
                     "erabliere": _sugar_shack, "kayak": _kayak, "chien": _doghouse, "balancoire": _swing})
LABEL_DRAWERS.update({"Poêle à bois": _wood_stove, "Laveuse-sécheuse": _washer, "Puits artésien": _well,
                      "Lits superposés": _bunk_bed})


# Objets à plat au sol : pas d'ombre
FLAT_KINDS = {"patio", "piscine", "potager", "feu", "foyer", "porte"}
FLAT_IDS = {"patio", "piscine", "tapis"}


def _object_shadow(surf: pygame.Surface, obj: InteractiveObject, rect: pygame.Rect) -> None:
    if obj.kind == "arbre":
        size = 18 if rect.width <= TILE else rect.width
        draw_shadow(surf, pygame.Rect(rect.centerx - size // 2 + 2, rect.bottom - 6, size, 7), ellipse=True,
                    alpha=80, offset=(0, 0))
    elif obj.id == "tente":
        draw_shadow(surf, pygame.Rect(rect.x + 2, rect.bottom - 7, rect.width, 9), ellipse=True, offset=(0, 0))
    elif obj.kind in ("chien", "berceau") or obj.label.startswith(("Puits", "Ruche")):
        draw_shadow(surf, rect.inflate(-2, -4), ellipse=True)
    else:
        draw_shadow(surf, rect.inflate(-2, -2))


def draw_object(surf: pygame.Surface, obj: InteractiveObject, body: bool = True) -> None:
    """body=False : seulement l'ombre (l'objet est dessiné en haute résolution, voir ui/props.py)."""
    x, y, w, h = obj.rect
    rect = pygame.Rect(x * TILE, y * TILE, w * TILE, h * TILE)
    if obj.kind in ("auto", "vehicule") or obj.id == "corde_bois":
        return  # dessinées à chaque image : l'auto part et revient, la corde de bois grossit
    if w and h and obj.kind not in FLAT_KINDS and obj.id not in FLAT_IDS:
        _object_shadow(surf, obj, rect)
    if not body:
        return
    if obj.kind == "arbre":
        if w == 1 and h == 1:
            _small_tree(surf, rect, obj.label)
        else:
            _tree(surf, rect)
    elif obj.kind == "lit" and obj.label.startswith("Lits superposés"):
        _bunk_bed(surf, rect)
    elif obj.kind == "lit" and obj.id not in OBJECT_DRAWERS:
        _bed(surf, rect, obj)
    elif obj.id in OBJECT_DRAWERS:
        OBJECT_DRAWERS[obj.id](surf, rect)
    elif obj.kind in KIND_DRAWERS:
        KIND_DRAWERS[obj.kind](surf, rect)
    elif any(obj.label.startswith(name) for name in LABEL_DRAWERS):
        LABEL_DRAWERS[next(n for n in LABEL_DRAWERS if obj.label.startswith(n))](surf, rect)
    elif w and h:  # les objets sans tuile (places autour du feu) ne se dessinent pas
        box(surf, rect.inflate(-2, -2), (156, 136, 112))


# ====================================================================== personnages
# Couleurs des personnages (dessinés en haute résolution par ui/pawns.py)

# Apparence par persona ; les personas ajoutés ont un style par défaut
STYLES: dict[str, dict] = {
    "pere": {"hair": (92, 62, 38), "pants": (52, 64, 98), "long_hair": False},
    "mere": {"hair": (150, 74, 42), "pants": (70, 54, 78), "long_hair": True},
    "ado": {"hair": (36, 30, 40), "pants": (44, 44, 52), "long_hair": True},
    "enfant": {"hair": (226, 186, 92), "pants": (72, 112, 62), "long_hair": False},
}
DEFAULT_STYLE = {"hair": (84, 64, 48), "pants": (62, 62, 82), "long_hair": False}
SKIN: Color = (242, 204, 170)


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


def draw_floating(surf: pygame.Surface, name: str, x: int, y: int, t: float, period: float = 1.6) -> None:
    """Icône (cœur, étoile) qui s'élève au-dessus d'un personnage et disparaît."""
    phase = (t / period) % 1.0
    image = icon(name)
    image.set_alpha(round(255 * (1 - phase)))
    surf.blit(image, (x - image.get_width() // 2, y - round(phase * 8) - image.get_height()))
    image.set_alpha(255)


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
