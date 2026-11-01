"""Pixel art généré dans le code : sols, murs, meubles et personnages (aucun fichier externe).

Tout est dessiné en basse résolution (TILE px par tuile) puis agrandi par le renderer.
"""

from __future__ import annotations

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


def draw_window(surf: pygame.Surface, x: int, y: int, vertical: bool, on_face: bool) -> None:
    t = TILE
    if vertical:
        glass = pygame.Rect(x * t + t // 2 - 3, y * t + 2, 6, t - 4)
    elif on_face:
        glass = pygame.Rect(x * t + 3, y * t + t // 2 + 1, t - 6, t // 2 - 4)
    else:
        glass = pygame.Rect(x * t + 2, y * t + t // 2 - 3, t - 4, 6)
    pygame.draw.rect(surf, GLASS, glass)
    pygame.draw.rect(surf, FRAME, glass, 1)
    surf.set_at((glass.x + 2, glass.y + 2), (235, 245, 255))


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


def _table(surf: pygame.Surface, r: pygame.Rect) -> None:
    inner = r.inflate(-2, -2)
    box(surf, inner, (146, 100, 62))
    pygame.draw.rect(surf, shade((146, 100, 62), 18), inner.inflate(-4, -4), 1)
    for px, py in ((inner.left + 6, inner.centery), (inner.right - 7, inner.centery),
                   (inner.centerx - 4, inner.top + 5), (inner.centerx + 4, inner.bottom - 6)):
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


def _door(surf: pygame.Surface, r: pygame.Rect) -> None:
    door = pygame.Rect(r.x + 2, r.y, r.width - 4, r.height - 2)
    box(surf, door, (128, 84, 44))
    pygame.draw.rect(surf, shade((128, 84, 44), 20), door.inflate(-4, -6), 1)
    surf.set_at((door.right - 3, door.centery), (240, 210, 90))


OBJECT_DRAWERS = {
    "frigo": _fridge, "cuisiniere": _stove, "comptoir": _counter, "table": _table,
    "commode": _dresser, "ordi": _computer, "jouets": _toys, "douche": _shower,
    "toilette": _toilet, "tele": _tv, "canape": _sofa, "biblio": _bookshelf, "porte": _door,
}


def draw_object(surf: pygame.Surface, obj: InteractiveObject) -> None:
    x, y, w, h = obj.rect
    rect = pygame.Rect(x * TILE, y * TILE, w * TILE, h * TILE)
    if obj.kind == "lit":
        _bed(surf, rect, obj)
    elif obj.id in OBJECT_DRAWERS:
        OBJECT_DRAWERS[obj.id](surf, rect)
    else:
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
EMPTY_ROW = "." * 16

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


def _body_rows(direction: str, frame: int, long_hair: bool, child: bool) -> list[str]:
    rows = HEADS[direction] + TORSOS[direction] + LEGS[direction][frame]
    rows = list(rows)
    if long_hair:
        _long_hair(rows, direction)
    if child:
        # Enfant : un rang de torse et un rang de jambes en moins, grosse tête conservée
        rows = [r for i, r in enumerate(rows) if i not in (8, 13)]
        rows = [EMPTY_ROW, EMPTY_ROW] + rows
    return rows + [EMPTY_ROW]  # place pour le contour sous les pieds


def _palette(persona: Persona) -> tuple[dict[str, Color], dict]:
    style = STYLES.get(persona.id, DEFAULT_STYLE)
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
    """Images (direction, image) : direction parmi down/up/left/right, image 0 = immobile."""
    if persona.id not in _FRAMES:
        palette, style = _palette(persona)
        child = persona.age < 13
        frames: dict[tuple[str, int], pygame.Surface] = {}
        for direction in ("down", "up", "left"):
            for frame in range(3):
                rows = _body_rows(direction, frame, style["long_hair"], child)
                frames[(direction, frame)] = add_outline(sprite_from_rows(rows, palette))
        for frame in range(3):
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
