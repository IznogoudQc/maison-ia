"""Meubles et arbres lisses, dessinés en haute résolution comme les personnages (ui/pawns.py).

Chaque objet reconnu (prop_key) est dessiné suréchantillonné puis réduit, à la taille de l'écran ; le
décor de fond (ui/sprites.py) n'en garde que l'ombre. Le renderer les trie en profondeur avec les
personnages et leur applique la lumière de la pièce. Les autres objets restent en pixel art.
"""

from __future__ import annotations

import math
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
    if obj.id in ID_KEYS:
        return (ID_KEYS[obj.id], w, h)
    if kind == "lit" and label.startswith("Lits superposés"):
        return ("superpose", w, h)
    if kind == "lit":
        return ("lit", w, h, max(1, obj.capacity), BLANKETS.get(obj.id) or _blanket(obj.id), obj.quality < 0.85)
    if kind == "vehicule":
        model = obj.id.split("_")[1] if obj.id.count("_") >= 2 else "compacte"
        return ("vehicule", w, h, model)
    if kind in KIND_KEYS:
        return (KIND_KEYS[kind], w, h)
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
    for prefix, name in LABEL_KEYS:
        if label.startswith(prefix):
            return (name, w, h)
    return None


# Objets reconnus par identifiant, par type ou par le début du nom (les autres restent en pixel art)
ID_KEYS = {"glaciere": "glaciere", "baril": "baril", "becosse": "becosse", "table_pique_nique": "pique_nique",
           "feu": "feu_camp", "cabanon": "cabanon", "boite_lettres": "boite_lettres"}
KIND_KEYS = {k: k for k in ("console", "piano", "trampoline", "hamac", "spa", "potager", "poulailler", "balancoire",
                            "cafe", "foyer", "exercice", "etude", "billard", "babyfoot", "pingpong", "cinema",
                            "aquarium", "ruche", "erabliere", "kayak", "chien", "berceau", "ordi", "jouets", "bbq",
                            "patio", "piscine", "porte")}
LABEL_KEYS = (("Télé", "tele"), ("Comptoir", "comptoir"), ("Toilette", "toilette"), ("Commode", "commode"),
              ("Panneaux", "solaire"), ("Congélateur", "congelateur"), ("Établi", "etabli"),
              ("Poêle à bois", "poele"), ("Laveuse", "laveuse"), ("Puits", "puits"))


def _blanket(seed: str) -> Color:
    palette = [(92, 120, 178), (124, 78, 160), (226, 140, 46), (70, 140, 110), (190, 80, 90)]
    return palette[sum(map(ord, seed)) % len(palette)]


def bounds(key: tuple) -> tuple[int, int, int, int]:
    """Débord de l'image autour du rectangle de l'objet, en px de base."""
    if key[0] == "arbre":
        return BIG_TREE_BOUNDS if key[3] == "gros" else TREE_BOUNDS
    return OVERFLOW.get(key[0], (0, 0, 0, 0))


# Débords : panneau d'autobus au-dessus du poteau, ombre intégrée des objets qui bougent
OVERFLOW = {"porte": (0, -7, 0, 0), "vehicule": (0, 0, 3, 3), "bois": (0, -6, 3, 3), "boite_lettres": (0, -2, 0, 0)}


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
    elif kind == "vehicule":
        _vehicle(pen, W, H, key[3])
    elif kind == "bois":
        _woodpile(pen, W, H, key[3])
    else:
        DRAWERS[kind](pen, W, H)
    return pygame.transform.smoothscale(canvas, size)



# ====================================================================== cour, catalogue et campement

def _shadow(pen: _Pen, x, y, w, h, alpha: int = 70) -> None:
    """Ombre intégrée (objets qui bougent : véhicules, corde de bois)."""
    rect = pen.r(x, y, w, h)
    shadow = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(shadow, (20, 16, 18, alpha), shadow.get_rect(), border_radius=round(3 * pen.u))
    pen.c.blit(shadow, rect.topleft)


def _ellipse(pen: _Pen, color, x, y, w, h, outline: bool = True) -> None:
    rect = pen.r(x, y, w, h)
    if outline:
        pygame.draw.ellipse(pen.c, OUTLINE, rect.inflate(pen.line * 2, pen.line * 2))
    pygame.draw.ellipse(pen.c, color, rect)


def _console(pen, W, H):
    pen.rect((44, 44, 52), 3, 6, 10, 5, radius=1.2)
    pen.circle((80, 200, 120), 5.5, 8.5, 0.8, outline=False)
    pen.rect((230, 230, 236), 8.5, 11.5, 5, 3, radius=1.2)                   # manette


def _piano(pen, W, H):
    pen.rect((40, 28, 26), 1, 1.5, W - 2, H - 4, radius=1.5)
    pen.rect((246, 244, 238), 2, H - 7, W - 4, 3.5, radius=0.5, outline=False)
    for i in range(int(W - 6) // 2):
        if i % 7 not in (2, 6):
            pygame.draw.rect(pen.c, (24, 24, 24), pen.r(3.2 + i * 2, H - 7, 1, 2.2))


def _trampoline(pen, W, H):
    _ellipse(pen, (40, 110, 200), 1, 1, W - 2, H - 2)
    _ellipse(pen, (28, 28, 34), 3.5, 3.5, W - 7, H - 7, outline=False)
    _ellipse(pen, (44, 44, 52), 6, 6, W - 12, H - 12, outline=False)


def _hammock(pen, W, H):
    for x in (1, W - 3):
        pen.rect((110, 80, 50), x, 2, 2, H - 4, radius=0.6)
    _ellipse(pen, (210, 80, 60), 3, 3, W - 6, H - 6)
    for i in range(1, 4):
        pen.vline((240, 220, 200), 3 + i * (W - 6) / 4, 4.5, H - 4.5, 0.5)


def _spa(pen, W, H):
    pen.rect((150, 110, 80), 1, 1, W - 2, H - 2, radius=4)
    pen.rect((90, 180, 220), 3.5, 3.5, W - 7, H - 7, radius=3, outline=False)
    for x, y in ((W / 2 - 3, H / 2 - 2), (W / 2 + 3, H / 2 + 2), (W / 2 + 2, H / 2 - 4)):
        pen.circle((200, 236, 250), x, y, 1.0, outline=False)                  # bulles


def _garden(pen, W, H):
    pen.rect((112, 82, 54), 1, 1, W - 2, H - 2, radius=1.5)
    for row in range(3):
        y = 5 + row * (H - 8) / 2.6
        for col in range(4):
            x = 5 + col * (W - 9) / 3
            pen.circle((70, 150, 70), x, y, 2.4, outline=False)
            pen.circle((220, 60, 50) if (row + col) % 2 else (240, 180, 60), x + 1, y - 1, 0.9, outline=False)


def _coop(pen, W, H):
    pen.rect((170, 64, 50), 2, 2, W - 4, H / 2, radius=1.5)
    pen.hline((120, 40, 32), 2.5, W - 2.5, 2 + H / 4, 1.0)                     # faîte du toit
    pen.rect((214, 204, 186), 2, H / 2 + 1, W - 4, H / 2 - 3, radius=1)
    for x in (8, 16, 23):
        pen.circle((250, 248, 240), x, H - 6, 2.2)
        pen.circle((220, 60, 50), x + 1.2, H - 7.4, 0.6, outline=False)


def _swing(pen, W, H):
    pen.rect((110, 80, 50), 1, 1, 2.2, H - 2, radius=0.8)
    pen.rect((110, 80, 50), W - 3.2, 1, 2.2, H - 2, radius=0.8)
    pen.rect((110, 80, 50), 1, 2, W - 2, 2, radius=0.6)
    for x in (W / 2 - 3, W / 2 + 3):
        pen.vline((90, 90, 90), x, 4, 9.5, 0.5)
    pen.rect((200, 60, 60), W / 2 - 4, 9, 8, 3, radius=1)


def _espresso(pen, W, H):
    pen.rect((60, 60, 66), 4, 3, 8, 10, radius=1.5)
    pen.rect((40, 40, 46), 5.5, 4.5, 5, 3, radius=0.8, outline=False)
    pen.rect((240, 240, 236), 6.5, 10, 3, 3, radius=0.8)


def _stone_ring(pen, cx, cy, radius, stones, size):
    for i in range(stones):
        a = i / stones * math.tau
        pen.circle((140, 138, 134), cx + math.cos(a) * radius, cy + math.sin(a) * radius, size)


def _fire_pit(pen, W, H):
    _stone_ring(pen, W / 2, H / 2, W / 2 - 4, 10, 2.4)
    pen.circle((58, 46, 40), W / 2, H / 2, W / 2 - 6, outline=False)
    pen.hline((150, 104, 62), W / 2 - 4, W / 2 + 4, H / 2 + 1, 1.8)
    pen.hline((130, 90, 54), W / 2 - 3, W / 2 + 3, H / 2 - 1.5, 1.8)


def _campfire(pen, W, H):
    _stone_ring(pen, W / 2, H / 2, 5, 8, 1.8)
    pen.hline((120, 84, 50), W / 2 - 3.5, W / 2 + 3.5, H / 2 + 1, 1.6)
    pen.hline((100, 70, 44), W / 2 - 3, W / 2 + 3, H / 2 - 1, 1.6)


def _exercise_bike(pen, W, H):
    pen.rect((60, 60, 66), 3, H - 5, W - 6, 2, radius=0.8)
    pen.circle((200, 60, 50), W - 5, H / 2 + 1, 3)
    pen.rect((60, 60, 66), 4.5, 4, 2, H - 8, radius=0.6)
    pen.rect((30, 30, 34), 3, 3, 5, 2, radius=0.8)                             # la selle


def _desk(pen, W, H):
    pen.rect((170, 128, 84), 1, 3, W - 2, H - 6, radius=1.2)
    pen.rect((246, 244, 238), 3.5, 5, 5, 4, radius=0.4)                         # un cahier
    pen.vline((60, 60, 160), 10, 5, 9, 0.6)                                     # un crayon


def _bunk(pen, W, H):
    pen.rect((150, 108, 66), 0.5, 0.5, W - 1, H - 1, radius=1.5)
    half = (H - 3) / 2
    for y in (1.5, 2 + half):
        pen.rect((90, 130, 200), 2.5, y, W - 5, half - 1, radius=1, outline=False)
        pen.rect((250, 250, 246), 3.5, y + 0.8, W - 7, 2.6, radius=1, outline=False)
    pen.vline((110, 80, 50), W - 2.5, 2, H - 2, 0.8)                            # l'échelle


def _pool_table(pen, W, H):
    pen.rect((110, 70, 40), 1, 1.5, W - 2, H - 3, radius=2)
    pen.rect((40, 130, 70), 3.5, 4, W - 7, H - 8, radius=1, outline=False)
    for color, dx, dy in (((250, 248, 240), 10, 0), ((220, 40, 40), 22, -2), ((240, 200, 40), 26, 2),
                          ((40, 40, 40), 30, 0)):
        pen.circle(color, dx, H / 2 + dy, 1.2, outline=False)
    for x, y in ((3.5, 4), (W - 3.5, 4), (3.5, H - 4), (W - 3.5, H - 4), (W / 2, 4), (W / 2, H - 4)):
        pen.circle((20, 20, 20), x, y, 1.1, outline=False)                      # les poches


def _foosball(pen, W, H):
    pen.rect((70, 120, 70), 1, 2, W - 2, H - 4, radius=1.5)
    for i, x in enumerate(range(5, int(W) - 3, 6)):
        pen.vline((200, 200, 206), x, 0.5, H - 0.5, 0.6)
        pen.circle((220, 50, 50) if i % 2 else (50, 90, 200), x, H / 2, 1.2, outline=False)


def _ping_pong(pen, W, H):
    pen.rect((30, 80, 150), 1, 2, W - 2, H - 4, radius=1)
    pen.vline((250, 250, 250), W / 2, 2.5, H - 2.5, 0.9)
    pen.hline((250, 250, 250), 1.5, W - 1.5, H / 2, 0.4)


def _home_theater(pen, W, H):
    pen.rect((24, 24, 30), 3, 1.5, W - 6, H - 5, radius=1.2)
    pen.rect((70, 110, 190), 4.5, 3, W - 9, H - 8, radius=0.8, outline=False)
    for x in (0.5, W - 3):
        pen.rect((50, 50, 56), x, H - 7, 2.5, 5, radius=0.8)                    # haut-parleurs


def _aquarium(pen, W, H):
    pen.rect((70, 70, 76), 1.5, 3, W - 3, H - 6, radius=1)
    pen.rect((90, 170, 220), 2.8, 4.2, W - 5.6, H - 8.4, radius=0.6, outline=False)
    pen.circle((250, 140, 40), 6, H / 2, 1.1, outline=False)
    pen.circle((250, 220, 60), 10.5, H / 2 + 1.5, 0.9, outline=False)
    pen.vline((60, 150, 80), 4, H - 5, H / 2 + 1, 0.6)


def _beehive(pen, W, H):
    for i in range(4):
        pen.rect((240, 200, 60) if i % 2 else (220, 170, 40), 3.5, 3 + i * 2.6, 9, 2.8, radius=1, outline=i == 0)
    pen.rect((80, 60, 40), 7, 12.5, 2, 1.2, radius=0.4, outline=False)        # l'entrée
    pen.circle((40, 30, 20), 12.5, 4, 0.6, outline=False)                      # une abeille


def _sugar_shack(pen, W, H):
    pen.rect((130, 86, 52), 3, 8, W - 6, H - 10, radius=1)
    pygame.draw.polygon(pen.c, OUTLINE, [pen.p(0, 9.7), pen.p(W, 9.7), pen.p(W / 2, 0.5)])
    pygame.draw.polygon(pen.c, (170, 50, 40), [pen.p(1, 9), pen.p(W - 1, 9), pen.p(W / 2, 1.5)])
    pen.rect((90, 60, 40), W / 2 - 2, H - 8, 4, 6, radius=0.6)
    pen.rect((210, 210, 216), W - 7, 1, 2, 5, radius=0.6)                      # cheminée de vapeur


def _kayak(pen, W, H):
    _ellipse(pen, (230, 120, 30), 3, 1, W - 6, H - 2)
    _ellipse(pen, (40, 40, 46), W / 2 - 2, H / 2 - 3.5, 4, 7, outline=False)
    pen.vline((200, 200, 200), 2, 4, H - 4, 0.6)                               # la pagaie


def _doghouse(pen, W, H):
    pen.rect((170, 120, 70), 2, 6, W - 4, H - 7, radius=1)
    pygame.draw.polygon(pen.c, OUTLINE, [pen.p(0.5, 6.8), pen.p(W - 0.5, 6.8), pen.p(W / 2, 0.3)])
    pygame.draw.polygon(pen.c, (150, 50, 40), [pen.p(1.5, 6.2), pen.p(W - 1.5, 6.2), pen.p(W / 2, 1.4)])
    _ellipse(pen, (40, 30, 24), W / 2 - 3, H - 6.5, 6, 6, outline=False)


def _crib(pen, W, H):
    pen.rect((230, 214, 186), 1, 1, W - 2, H - 2, radius=1.5)
    pen.rect((250, 248, 240), 2.6, 2.6, W - 5.2, H - 5.2, radius=1, outline=False)
    for x in range(3, int(W) - 2, 3):
        pen.vline((180, 150, 110), x, 1.2, 3, 0.6)


def _computer(pen, W, H):
    pen.rect((110, 80, 56), 1, 4, W - 2, H - 6, radius=1)                      # le bureau
    pen.rect((36, 36, 44), W / 2 - 5, 1.5, 10, 6, radius=1)                    # l'écran
    pen.rect((30, 60, 90), W / 2 - 4, 2.5, 8, 4, radius=0.5, outline=False)
    pen.rect((220, 220, 226), W / 2 - 4, 9, 8, 2.4, radius=0.6)                # le clavier


def _toys(pen, W, H):
    pen.rect((200, 90, 70), 1, 4, W - 2, H - 6, radius=1.2)
    pen.hline((160, 60, 50), 1.5, W - 1.5, 6.5, 0.8)
    for i, color in enumerate(((220, 60, 50), (60, 120, 220), (240, 200, 50), (70, 170, 90))):
        pen.rect(color, 3 + i * (W - 6) / 4, 2, 2.5, 2.5, radius=0.4)          # des blocs Lego


def _bbq(pen, W, H):
    pen.circle((34, 34, 38), W / 2, H / 2, 6)
    for d in (-3, 0, 3):
        pen.hline((110, 110, 116), W / 2 - 4.5, W / 2 + 4.5, H / 2 + d, 0.5)
    pen.rect((60, 60, 66), W / 2 + 5, H / 2 - 1, 3, 2, radius=0.6, outline=False)


def _patio(pen, W, H):
    _ellipse(pen, (236, 236, 230), 4, 4, W - 8, H - 8)
    for i in range(8):  # parasol rayé vu de haut
        a0 = i / 8 * math.tau
        points = [pen.p(W / 2, H / 2)] + [pen.p(W / 2 + math.cos(a0 + math.tau / 8 * k / 4) * 7,
                                                 H / 2 + math.sin(a0 + math.tau / 8 * k / 4) * 7) for k in range(5)]
        pygame.draw.polygon(pen.c, (230, 90, 70) if i % 2 else (250, 240, 230), points)
    for x, y in ((2.5, H / 2), (W - 2.5, H / 2), (W / 2, 2.5), (W / 2, H - 2.5)):
        pen.circle((120, 90, 60), x, y, 1.6)                                    # chaises


def _pool(pen, W, H):
    pen.rect((214, 216, 222), 0.5, 0.5, W - 1, H - 1, radius=2)
    water = pen.rect((70, 160, 220), 2.5, 2.5, W - 5, H - 5, radius=1.5, outline=False)
    pygame.draw.rect(pen.c, (110, 190, 236), water, max(1, round(0.8 * pen.u)), border_radius=round(1.5 * pen.u))
    pen.rect((236, 236, 240), W - 3.5, H / 2 - 3, 1.6, 6, radius=0.5, outline=False)   # l'échelle


def _bus_stop(pen, W, H):
    pen.vline((120, 120, 128), W / 2, 1, H - 1, 1.2)
    pen.rect((40, 110, 200), W / 2 - 5, -6, 10, 8, radius=1.2)
    pen.rect((250, 250, 250), W / 2 - 3, -4, 6, 4, radius=0.6, outline=False)


def _shed(pen, W, H):
    pen.rect((150, 70, 56), 0.5, 0.5, W - 1, H - 1, radius=1.5)
    for y in range(4, int(H) - 1, 4):
        pen.hline((120, 52, 42), 1.5, W - 1.5, y, 0.6)
    pen.vline((90, 40, 32), W / 2, 1, H - 1, 1.2)                               # faîte du toit
    pen.rect((196, 180, 150), W / 2 - 4, H - 9, 8, 8, radius=0.8)


def _mailbox(pen, W, H):
    pen.vline((110, 80, 50), W / 2, 6, H - 1, 1.6)
    pen.rect((50, 50, 60), W / 2 - 4.5, -1, 9, 6, radius=2)
    pen.rect((220, 50, 50), W / 2 + 3.5, -1.5, 1.2, 3, radius=0.3, outline=False)       # drapeau


def _solar(pen, W, H):
    pen.rect((40, 60, 110), 1, 2, W - 2, H - 4, radius=0.8)
    for x in range(5, int(W) - 1, 5):
        pen.vline((120, 150, 210), x, 2.5, H - 2.5, 0.5)
    pen.hline((120, 150, 210), 1.5, W - 1.5, H / 2, 0.5)


def _freezer(pen, W, H):
    pen.rect((232, 236, 240), 1, 2.5, W - 2, H - 5, radius=1.5)
    pen.hline((160, 170, 180), 3, W - 3, H / 2, 0.8)


def _workbench(pen, W, H):
    pen.rect((150, 108, 66), 1, 2.5, W - 2, H - 5, radius=1)
    pen.hline((90, 90, 96), 4, 10, H / 2 - 1, 1.6)                              # marteau
    pen.rect((200, 60, 50), W - 9, H / 2 - 2, 5, 3, radius=0.6)                 # coffre à outils


def _wood_stove(pen, W, H):
    pen.rect((44, 40, 40), 2, 2.5, W - 4, H - 5, radius=2)
    pen.rect((230, 120, 40), 5, 8, 6, 4, radius=1, outline=False)
    pen.rect((70, 66, 66), W / 2 - 1.5, 0.5, 3, 3, radius=0.6)


def _washer(pen, W, H):
    pen.rect((236, 238, 242), 1.5, 1.5, W - 3, H - 3, radius=1.5)
    pen.circle((110, 150, 200), W / 2, H / 2 + 0.5, 4)
    pen.circle((160, 196, 230), W / 2 - 1, H / 2 - 0.5, 1.4, outline=False)


def _well(pen, W, H):
    pen.circle((140, 140, 146), W / 2, H / 2, 6)
    pen.circle((40, 70, 110), W / 2, H / 2, 4, outline=False)
    pen.rect((110, 80, 50), 1.5, 1.5, W - 3, 1.8, radius=0.5)


def _cooler(pen, W, H):
    pen.rect((210, 40, 40), 2, 4, W - 4, H - 7, radius=1.5)
    pen.rect((246, 246, 246), 2, 4, W - 4, 3, radius=1.2, outline=False)


def _barrel(pen, W, H):
    pen.circle((70, 100, 160), W / 2, H / 2, 6)
    pen.circle((100, 150, 210), W / 2, H / 2, 4, outline=False)
    pygame.draw.circle(pen.c, (60, 80, 120), pen.p(W / 2, H / 2), 6 * pen.u, max(1, round(0.7 * pen.u)))


def _outhouse(pen, W, H):
    pen.rect((138, 98, 60), 2, 3, W - 4, H - 4, radius=1)
    pygame.draw.polygon(pen.c, (90, 60, 40), [pen.p(0.8, 4), pen.p(W - 0.8, 4), pen.p(W / 2, -0.5)])
    pen.circle((40, 30, 20), W / 2, 10, 1.6, outline=False)                    # la lune dans la porte


def _picnic(pen, W, H):
    pen.rect((150, 108, 66), 1, 4, W - 2, H - 8, radius=1)
    for y in (1, H - 3):
        pen.rect((130, 92, 56), 2, y, W - 4, 2, radius=0.6)                     # les bancs
    for x in range(6, int(W) - 3, 6):
        pen.vline((120, 84, 50), x, 4.5, H - 4.5, 0.4)


def _vehicle(pen, W, H, model):
    colors = {"compacte": (200, 60, 50), "vus": (40, 70, 110), "pickup": (90, 110, 70), "moto": (30, 30, 34),
              "vtt": (200, 120, 30), "velo": (40, 140, 200)}
    color = colors.get(model, (200, 60, 50))
    if model == "velo":
        _shadow(pen, W / 2 - 2, 2, 5, H - 3, 60)
        for y in (3.5, H - 4):
            pygame.draw.circle(pen.c, (30, 30, 30), pen.p(W / 2, y), 3 * pen.u, max(1, round(0.8 * pen.u)))
        pen.vline(color, W / 2, 3.5, H - 4, 1.4)
        pen.hline((60, 60, 60), W / 2 - 3, W / 2 + 3, 5, 0.8)
        return
    if model in ("moto", "vtt"):
        body_w = W - (6 if model == "moto" else 2)
        x0 = (W - body_w) / 2
        _shadow(pen, x0 + 2, 3, body_w, H - 4)
        for y in (1.5, H - 5.5):
            pen.rect((25, 25, 25), x0 - 1, y, body_w + 2, 4, radius=1.2)
        pen.rect(color, x0, 5, body_w, H - 10, radius=2)
        pen.hline((200, 200, 205), x0 - 2, x0 + body_w + 2, 6.5, 0.8)            # guidon
        return
    _shadow(pen, 4, 4, W - 4, H - 3)
    for wx in (0.8, W - 3.2):
        for wy in (3.5, H - 8):
            pen.rect((22, 22, 22), wx, wy, 2.4, 5, radius=0.8)
    pen.rect(color, 1.5, 1, W - 3, H - 2, radius=4)
    pen.rect((170, 200, 220), 3, 5, W - 6, 6, radius=1.5, outline=False)         # pare-brise
    if model == "pickup":
        pen.rect((60, 70, 50), 3, H / 2 + 2, W - 6, H / 2 - 4, radius=1, outline=False)
        for i in range(3):  # des planches dans la boîte
            pen.hline((214, 178, 120), 4, W - 4, H / 2 + 5 + i * 3, 0.9)
    else:
        pen.rect(shade(color, 18), 3, 12, W - 6, H - 22, radius=2, outline=False)   # le toit
        pen.rect((170, 200, 220), 3, H - 9, W - 6, 4.5, radius=1.2, outline=False)  # lunette arrière
    pen.circle((255, 240, 180), 3.5, 1.8, 0.9, outline=False)
    pen.circle((255, 240, 180), W - 3.5, 1.8, 0.9, outline=False)                 # phares


def _woodpile(pen, W, H, logs):
    rows = min(5, (logs + 9) // 10)
    if rows:
        _shadow(pen, 2, H - 2 - rows * 3, min(W, logs * 3), rows * 3 + 2, 60)
    for row in range(rows):
        count = min(10, logs - row * 10)
        for i in range(min(count, int(W // 3))):
            cx, cy = 2 + i * 3 + (row % 2), H - 2 - row * 3
            pen.circle((150, 104, 62), cx, cy, 1.6)
            pen.circle((206, 170, 118), cx, cy, 0.7, outline=False)              # cerne du bois


DRAWERS.update({
    "console": _console, "piano": _piano, "trampoline": _trampoline, "hamac": _hammock, "spa": _spa,
    "potager": _garden, "poulailler": _coop, "balancoire": _swing, "cafe": _espresso, "foyer": _fire_pit,
    "exercice": _exercise_bike, "etude": _desk, "superpose": _bunk, "billard": _pool_table, "babyfoot": _foosball,
    "pingpong": _ping_pong, "cinema": _home_theater, "aquarium": _aquarium, "ruche": _beehive,
    "erabliere": _sugar_shack, "kayak": _kayak, "chien": _doghouse, "berceau": _crib, "ordi": _computer,
    "jouets": _toys, "bbq": _bbq, "patio": _patio, "piscine": _pool, "porte": _bus_stop, "cabanon": _shed,
    "boite_lettres": _mailbox, "solaire": _solar, "congelateur": _freezer, "etabli": _workbench,
    "poele": _wood_stove, "laveuse": _washer, "puits": _well, "glaciere": _cooler, "baril": _barrel,
    "becosse": _outhouse, "pique_nique": _picnic, "feu_camp": _campfire,
})
