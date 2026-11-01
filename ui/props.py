"""Meubles et arbres lisses, dessinés en haute résolution comme les personnages (ui/pawns.py).

Chaque objet reconnu (prop_key) est dessiné suréchantillonné puis réduit, à la taille de l'écran ; le
décor de fond (ui/sprites.py) n'en garde que l'ombre. Le renderer les trie en profondeur avec les
personnages et leur applique la lumière de la pièce. Les autres objets restent en pixel art.
"""

from __future__ import annotations

from functools import lru_cache

import pygame

from ui.sprites import BLANKETS, OUTLINE, TILE, TREE_COLORS, shade
from world.house import InteractiveObject

SUPERSAMPLE = 3
Color = tuple[int, int, int]
WOOD: Color = (150, 106, 68)
TREE_BOUNDS = (-6, -14, 6, 0)        # débord du feuillage autour de la case (x0, y0, x1, y1 en px de base)
BIG_TREE_BOUNDS = (-2, -4, 2, 0)


def prop_key(obj: InteractiveObject) -> tuple | None:
    """Clé de dessin en haute résolution (genre, largeur, hauteur, détails), ou None : reste en pixel art."""
    _x, _y, w, h = obj.rect
    if not w or not h:
        return None
    kind, label = obj.kind, obj.label
    if kind == "arbre":
        return ("arbre", w, h, label if w == 1 and h == 1 else "gros")
    if obj.id == "tente":
        return ("tente", w, h)
    if kind == "lit" and not label.startswith("Lits superposés"):
        return ("lit", w, h, max(1, obj.capacity), BLANKETS.get(obj.id) or _blanket(obj.id), obj.quality < 0.85)
    if kind == "table" and obj.id != "table_pique_nique":
        return ("table", w, h)
    if kind == "frigo" and obj.id != "glaciere":
        return ("frigo", w, h)
    if kind == "cuisiniere" and obj.id != "feu":
        return ("cuisiniere", w, h)
    if kind == "douche" and obj.id != "baril":
        return ("douche", w, h)
    if kind == "tele":
        return ("canape", w, h, (126, 70, 50) if "cuir" in label.lower() else (156, 62, 62))
    if kind == "livres":
        return ("biblio", w, h)
    for prefix, name in (("Télé", "tele"), ("Comptoir", "comptoir"), ("Toilette", "toilette"), ("Commode", "commode")):
        if label.startswith(prefix):
            return (name, w, h)
    return None


def _blanket(seed: str) -> Color:
    palette = [(92, 120, 178), (124, 78, 160), (226, 140, 46), (70, 140, 110), (190, 80, 90)]
    return palette[sum(map(ord, seed)) % len(palette)]


def bounds(key: tuple) -> tuple[int, int, int, int]:
    """Débord de l'image autour du rectangle de l'objet, en px de base."""
    if key[0] != "arbre":
        return (0, 0, 0, 0)
    return BIG_TREE_BOUNDS if key[3] == "gros" else TREE_BOUNDS


class _Pen:
    """Dessin en coordonnées de base (px de la tuile de 16) sur une toile agrandie."""

    def __init__(self, canvas: pygame.Surface, u: float, ox: float, oy: float) -> None:
        self.c, self.u, self.ox, self.oy = canvas, u, ox, oy
        self.line = max(1.0, 1.1 * u)

    def r(self, x: float, y: float, w: float, h: float) -> pygame.Rect:
        u = self.u
        return pygame.Rect(round((x + self.ox) * u), round((y + self.oy) * u), round(w * u), round(h * u))

    def p(self, x: float, y: float) -> tuple[float, float]:
        return (x + self.ox) * self.u, (y + self.oy) * self.u

    def rect(self, color, x, y, w, h, radius: float = 2, outline: bool = True) -> pygame.Rect:
        rect = self.r(x, y, w, h)
        rad = round(radius * self.u)
        if outline:
            pygame.draw.rect(self.c, OUTLINE, rect.inflate(self.line * 2, self.line * 2),
                             border_radius=rad + round(self.line))
        pygame.draw.rect(self.c, color, rect, border_radius=rad)
        return rect

    def circle(self, color, x, y, radius, outline: bool = True) -> None:
        if outline:
            pygame.draw.circle(self.c, OUTLINE, self.p(x, y), radius * self.u + self.line)
        pygame.draw.circle(self.c, color, self.p(x, y), radius * self.u)

    def hline(self, color, x0, x1, y, width: float = 0.8) -> None:
        pygame.draw.line(self.c, color, self.p(x0, y), self.p(x1, y), max(1, round(width * self.u)))

    def vline(self, color, x, y0, y1, width: float = 0.8) -> None:
        pygame.draw.line(self.c, color, self.p(x, y0), self.p(x, y1), max(1, round(width * self.u)))


# ---------------------------------------------------------------------- dessins (W, H en px de base)

def _tree(pen: _Pen, W: float, H: float, species: str) -> None:
    cx, bottom = W / 2, H
    if species == "Sapin":
        pen.rect((96, 66, 42), cx - 1.5, bottom - 5, 3, 5, radius=0.5)
        for i, (half, color) in enumerate(((9, (34, 78, 50)), (7, (42, 94, 58)), (5, (54, 110, 68)))):
            top = bottom - 8 - i * 6
            outline = [pen.p(cx - half - 1, top + 7.6), pen.p(cx + half + 1, top + 7.6), pen.p(cx, top - 5.4)]
            pygame.draw.polygon(pen.c, OUTLINE, outline)
            pygame.draw.polygon(pen.c, color, [pen.p(cx - half, top + 7), pen.p(cx + half, top + 7), pen.p(cx, top - 4)])
        return
    trunk = (226, 222, 210) if species == "Bouleau" else (104, 72, 46)
    pen.rect(trunk, cx - 1.6, bottom - 7, 3.2, 7, radius=1)
    if species == "Bouleau":
        pen.hline((50, 50, 50), cx - 1, cx + 0.5, bottom - 4, 0.7)
    dark, mid, light = TREE_COLORS.get(species, TREE_COLORS["Érable"])
    blobs = [(cx - 4, bottom - 11, 6), (cx + 4, bottom - 11, 6), (cx, bottom - 15, 7.5)]
    for x, y, rad in blobs:  # contour commun, puis les masses de feuillage
        pen.circle(OUTLINE, x, y, rad + 0.1)
    for x, y, rad in blobs:
        pen.circle(dark, x, y, rad, outline=False)
    pen.circle(mid, cx - 1.5, bottom - 15.5, 5.5, outline=False)
    pen.circle(mid, cx + 3.5, bottom - 12, 3.5, outline=False)
    pen.circle(light, cx - 3, bottom - 17.5, 2.2, outline=False)


def _big_tree(pen: _Pen, W: float, H: float) -> None:
    cx, cy = W / 2, H / 2
    pen.rect((104, 72, 46), cx - 2, H - 9, 4, 8, radius=1)
    dark, mid, light = TREE_COLORS["Érable"]
    blobs = [(cx - 6, cy - 1, 9), (cx + 6, cy, 8.5), (cx, cy - 7, 10.5)]
    for x, y, rad in blobs:
        pen.circle(OUTLINE, x, y, rad + 0.1)
    for x, y, rad in blobs:
        pen.circle(dark, x, y, rad, outline=False)
    pen.circle(mid, cx - 1, cy - 6, 7.5, outline=False)
    pen.circle(mid, cx + 6, cy - 1, 5, outline=False)
    pen.circle(light, cx - 4, cy - 10, 3, outline=False)


def _bed(pen: _Pen, W: float, H: float, places: int, blanket: Color, mattress: bool) -> None:
    if mattress:  # un matelas à même le sol
        pen.rect((226, 222, 210), 1, 1, W - 2, H - 2, radius=2.5)
        pen.rect(blanket, 1.5, H * 0.42, W - 3, H * 0.58 - 1.5, radius=2, outline=False)
        pen.rect((246, 244, 238), W / 2 - 4, 2.5, 8, 4, radius=1.8)
        return
    pen.rect(shade(WOOD, -14), 0.5, 0.5, W - 1, H - 1, radius=2)
    pen.rect((240, 236, 228), 2, 2, W - 4, H - 4, radius=1.5, outline=False)
    slot = (W - 4) / places
    for i in range(places):
        pen.rect((252, 250, 246), 2.8 + i * slot, 3, slot - 1.6, 4.2, radius=1.6)
    top = 9 if H > 20 else H * 0.38
    pen.rect(blanket, 2, top, W - 4, H - top - 2, radius=1.5, outline=False)
    pen.hline(shade(blanket, 30), 2.5, W - 2.5, top + 0.6, 1.2)                # le repli du drap
    for i in range(1, 4):
        pen.hline(shade(blanket, -18), 3, W - 3, top + i * (H - top - 2) / 4, 0.5)


def _table(pen: _Pen, W: float, H: float) -> None:
    pen.rect(WOOD, 1, 1, W - 2, H - 2, radius=2)
    pen.hline(shade(WOOD, 24), 2.5, W - 2.5, 2, 0.9)
    for i in range(int(W) // 8):
        pen.vline(shade(WOOD, -14), 4 + i * 8, 2.5, H - 2.5, 0.4)


def _fridge(pen: _Pen, W: float, H: float) -> None:
    pen.rect((232, 236, 242), 1, 1, W - 2, H - 2, radius=1.8)
    pen.vline((180, 188, 198), W / 2, 2, H - 2, 0.6)
    pen.rect((150, 158, 168), W / 2 - 3, H - 5, 2, 2.5, radius=0.6, outline=False)
    pen.rect((150, 158, 168), W / 2 + 1, H - 5, 2, 2.5, radius=0.6, outline=False)
    for dx, color in ((4, (220, 60, 60)), (7, (60, 140, 220)), (W - 6, (240, 190, 40))):
        pen.circle(color, dx, 4, 0.9, outline=False)  # aimants


def _stove(pen: _Pen, W: float, H: float) -> None:
    pen.rect((86, 86, 94), 1, 1, W - 2, H - 2, radius=1.6)
    for cx in (W / 4 + 0.5, 3 * W / 4 - 0.5):
        pen.circle((40, 40, 44), cx, H / 2, 3.6, outline=False)
        pygame.draw.circle(pen.c, (140, 140, 148), pen.p(cx, H / 2), 3.6 * pen.u, max(1, round(0.6 * pen.u)))


def _counter(pen: _Pen, W: float, H: float) -> None:
    pen.rect((214, 206, 190), 0.5, 1, W - 1, H - 2, radius=1)
    sink = pen.rect((176, 186, 196), W / 2 - 4, 3.5, 8, H - 7, radius=1.6)
    pygame.draw.circle(pen.c, (120, 128, 138), sink.center, 0.8 * pen.u)


def _shower(pen: _Pen, W: float, H: float) -> None:
    pen.rect((220, 234, 240), 1, 1, W - 2, H - 2, radius=2)
    pen.rect((196, 214, 224), 3, 3, W - 6, H - 6, radius=1.5, outline=False)
    pen.circle((120, 132, 140), W / 2, H / 2, 1.1, outline=False)
    pen.circle((170, 180, 190), W - 4, 4, 1.4)


def _toilet(pen: _Pen, W: float, H: float) -> None:
    pen.rect((244, 244, 246), W / 2 - 4, 1.5, 8, 4, radius=1.2)
    bowl = pen.r(W / 2 - 3.5, 5, 7, 9)
    pygame.draw.ellipse(pen.c, OUTLINE, bowl.inflate(pen.line * 2, pen.line * 2))
    pygame.draw.ellipse(pen.c, (248, 248, 250), bowl)
    pygame.draw.ellipse(pen.c, (200, 214, 222), bowl.inflate(-3 * pen.u, -3.5 * pen.u))


def _sofa(pen: _Pen, W: float, H: float, color: Color) -> None:
    pen.rect(shade(color, -10), 0.5, 1, W - 1, H - 2, radius=2.5)
    pen.rect(shade(color, -34), 0.5, H - 6, W - 1, 5, radius=2, outline=False)      # dossier (côté sud)
    seats = max(1, round((W - 8) / 14))
    width = (W - 8) / seats
    for i in range(seats):
        pen.rect(shade(color, 8), 4.5 + i * width, 2.5, width - 1, H - 9, radius=1.8, outline=False)
    for x in (0.5, W - 4.5):
        pen.rect(shade(color, -22), x, 1, 4, H - 2, radius=2, outline=False)       # accoudoirs


def _tv(pen: _Pen, W: float, H: float) -> None:
    pen.rect((116, 82, 54), 1, 2.5, W - 2, H - 4.5, radius=1.5)
    pen.rect((26, 26, 32), 6, 2, W - 12, 7, radius=1)


def _dresser(pen: _Pen, W: float, H: float) -> None:
    pen.rect(shade(WOOD, -6), 1, 1.5, W - 2, H - 3, radius=1.5)
    pen.vline(shade(WOOD, -30), W / 2, 2.5, H - 2.5, 0.6)
    for cx in (W / 4, 3 * W / 4):
        pen.circle((224, 196, 120), cx, H / 2, 0.9, outline=False)


def _bookshelf(pen: _Pen, W: float, H: float) -> None:
    pen.rect((112, 76, 48), 0.5, 0.5, W - 1, H - 1, radius=1.2)
    colors = [(190, 60, 60), (60, 110, 180), (220, 190, 70), (80, 150, 90), (230, 230, 220), (140, 80, 160)]
    shelves = max(1, int(H // 5))
    for s in range(shelves):
        y = 1.8 + s * (H - 2.5) / shelves
        height = (H - 2.5) / shelves - 1.2
        x, i = 2.0, s * 3
        while x < W - 2.5:
            pen.rect(colors[i % len(colors)], x, y, 1.6, height, radius=0.3, outline=False)
            x += 2.2
            i += 1


def _tent(pen: _Pen, W: float, H: float) -> None:
    """Tente canadienne vue de dessus : deux pans, la crête, la porte ouverte au sud."""
    pen.rect((52, 120, 84), 1, 1.5, W - 2, H - 3, radius=3)
    pen.rect((40, 100, 70), 1, H / 2, W - 2, H / 2 - 1.5, radius=3, outline=False)
    pen.hline((30, 70, 50), 2, W - 2, H / 2, 1.0)
    door = [pen.p(W / 2 - 3.5, H - 1.5), pen.p(W / 2 + 3.5, H - 1.5), pen.p(W / 2, H / 2 + 1)]
    pygame.draw.polygon(pen.c, (28, 46, 36), door)


DRAWERS = {"table": _table, "frigo": _fridge, "cuisiniere": _stove, "comptoir": _counter, "douche": _shower,
           "toilette": _toilet, "tele": _tv, "commode": _dresser, "biblio": _bookshelf, "tente": _tent}


@lru_cache(maxsize=1024)
def prop_image(key: tuple, scale: float) -> pygame.Surface:
    """Image de l'objet à l'échelle de l'écran (scale = px écran par px de base)."""
    kind, w, h = key[0], key[1], key[2]
    x0, y0, x1, y1 = bounds(key)
    W, H = w * TILE, h * TILE
    size = (max(1, round((W + x1 - x0) * scale)), max(1, round((H + y1 - y0) * scale)))
    canvas = pygame.Surface((size[0] * SUPERSAMPLE, size[1] * SUPERSAMPLE), pygame.SRCALPHA)
    pen = _Pen(canvas, scale * SUPERSAMPLE, -x0, -y0)
    if kind == "arbre":
        if key[3] == "gros":
            _big_tree(pen, W, H)
        else:
            _tree(pen, W, H, key[3])
    elif kind == "lit":
        _bed(pen, W, H, key[3], key[4], key[5])
    elif kind == "canape":
        _sofa(pen, W, H, key[3])
    else:
        DRAWERS[kind](pen, W, H)
    return pygame.transform.smoothscale(canvas, size)
