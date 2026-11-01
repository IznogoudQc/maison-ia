"""Personnages lisses vus de dessus : grosse tête ronde, corps en capsule, sans jambes.

Dessinés directement à la résolution de l'écran (suréchantillonnés puis réduits, donc sans escaliers),
par-dessus la carte agrandie. Le renderer leur applique la lumière de la pièce (nuit, lampes allumées).
"""

from __future__ import annotations

from functools import lru_cache

import pygame

from agents.persona import Persona
from ui.sprites import OUTLINE, _palette, shade

SUPERSAMPLE = 4
HEIGHT_TILES = 1.3      # hauteur d'un adulte, en cases
CHILD_FACTOR = 0.8
Color = tuple[int, int, int]


def pawn_height(persona: Persona) -> float:
    """Hauteur en cases (un enfant est plus petit)."""
    return HEIGHT_TILES * (CHILD_FACTOR if persona.age < 13 else 1.0)


def _circle(surf: pygame.Surface, color, center, radius, outline: float) -> None:
    pygame.draw.circle(surf, OUTLINE, center, radius + outline)
    pygame.draw.circle(surf, color, center, radius)


@lru_cache(maxsize=512)
def _render(persona_key: tuple, direction: str, sitting: bool, height: int) -> pygame.Surface:
    shirt, pants, skin, hair, eyes, long_hair = persona_key
    width = max(4, round(height * 0.74))
    s = SUPERSAMPLE
    canvas = pygame.Surface((width * s, height * s), pygame.SRCALPHA)
    u = height * s / 100          # une unité = 1 % de la hauteur
    line = 2.4 * u                # épaisseur du contour
    mid = width * s / 2
    side = {"left": -1, "right": 1}.get(direction, 0)

    def p(x: float, y: float) -> tuple[float, float]:
        return mid + x * u, y * u

    # Corps : une capsule (chandail en haut, pantalon en bas), plus basse quand on est assis
    top, bottom = (50, 96) if sitting else (42, 98)
    body = pygame.Rect(0, 0, 54 * u, (bottom - top) * u)
    body.midtop = p(side * 2, top)
    radius = round(22 * u)
    pygame.draw.rect(canvas, OUTLINE, body.inflate(line * 2, line * 2), border_radius=radius + round(line))
    pygame.draw.rect(canvas, shirt, body, border_radius=radius)
    legs = body.copy()
    legs.height = round(body.height * 0.38)
    legs.bottom = body.bottom
    pygame.draw.rect(canvas, pants, legs, border_bottom_left_radius=radius, border_bottom_right_radius=radius)
    pygame.draw.line(canvas, shade(shirt, 28), (body.x + radius, body.y + 3 * u), (body.right - radius, body.y + 3 * u),
                     max(1, round(2 * u)))  # reflet sur les épaules
    # Mains au bout des bras
    hand = 6.5 * u
    hands = [(-27, 70), (27, 70)] if side == 0 else [(side * 22, 70)]
    if sitting:
        hands = [(x, 68) for x, _ in hands]
    for hx, hy in hands:
        _circle(canvas, skin, p(hx, hy), hand, line * 0.8)
    # Tête : cheveux derrière, visage devant (selon la direction)
    head_c = p(side * 3, 26)
    head_r = 21 * u
    if long_hair and direction != "up":
        back = pygame.Rect(0, 0, 46 * u, 40 * u)
        back.midtop = p(side * -3, 18)
        pygame.draw.rect(canvas, OUTLINE, back.inflate(line * 2, line * 2), border_radius=round(14 * u))
        pygame.draw.rect(canvas, hair, back, border_radius=round(14 * u))
    _circle(canvas, hair, head_c, head_r, line)
    if direction == "up":
        if long_hair:
            tail = pygame.Rect(0, 0, 30 * u, 26 * u)
            tail.midtop = p(0, 30)
            pygame.draw.rect(canvas, hair, tail, border_radius=round(12 * u))
    else:
        face_c = p(side * 9, 30) if side else p(0, 31)
        face_r = 16.5 * u if side else 17 * u
        pygame.draw.circle(canvas, skin, face_c, face_r)
        # Frange par-dessus le front
        fringe = pygame.Rect(0, 0, (30 if side == 0 else 26) * u, 11 * u)
        fringe.midtop = p(side * 6, 10)
        pygame.draw.ellipse(canvas, hair, fringe)
        eye = 2.8 * u
        if side == 0:
            for ex in (-7, 7):
                pygame.draw.circle(canvas, eyes, p(ex, 31), eye)
        else:
            pygame.draw.circle(canvas, eyes, p(side * 15, 30), eye)
        pygame.draw.circle(canvas, shade(skin, -18), p(side * 10, 39), 1.6 * u)  # le nez / la bouche
    return pygame.transform.smoothscale(canvas, (width, height))


def pawn_image(persona: Persona, direction: str, sitting: bool, height_px: int) -> pygame.Surface:
    palette, style = _palette(persona)
    key = tuple(tuple(palette[k]) for k in ("T", "P", "S", "H", "E")) + (bool(style["long_hair"]),)
    return _render(key, direction, sitting, max(8, height_px))


def lit(image: pygame.Surface, darkness: float, tint: tuple[int, int, int, int] | None = None) -> pygame.Surface:
    """Copie assombrie (nuit : 0 = plein jour, 1 = noir bleuté) et teintée (lumière dorée)."""
    if darkness <= 0.01 and tint is None:
        return image
    out = image.copy()
    if tint is not None:
        r, g, b, a = tint
        k = a / 255
        out.fill((round(255 - (255 - r) * k), round(255 - (255 - g) * k), round(255 - (255 - b) * k), 255),
                 special_flags=pygame.BLEND_RGBA_MULT)
    if darkness > 0.01:
        f = 1 - darkness
        out.fill((round(255 * f * 0.78), round(255 * f * 0.84), round(255 * min(1.0, f * 1.05)), 255),
                 special_flags=pygame.BLEND_RGBA_MULT)
    return out


@lru_cache(maxsize=256)
def _render_sleeper(persona_key: tuple, blanket: tuple, child: bool, scale: float) -> pygame.Surface:
    _shirt, _pants, skin, hair, eyes, long_hair = persona_key
    w, h = 12, (16 if child else 21)              # en px de base : la tête et la bosse sous la douillette
    s = SUPERSAMPLE
    u = scale * s
    canvas = pygame.Surface((round(w * u), round(h * u)), pygame.SRCALPHA)
    line = 1.0 * u
    body = pygame.Rect(round(1 * u), round(5 * u), round(10 * u), round((h - 5.5) * u))
    pygame.draw.ellipse(canvas, shade(blanket, -40), body.inflate(line, line))
    pygame.draw.ellipse(canvas, shade(blanket, 14), body)
    center = (w / 2 * u, 4.5 * u)
    pygame.draw.circle(canvas, OUTLINE, center, 4.3 * u + line)
    pygame.draw.circle(canvas, hair, center, 4.3 * u)
    pygame.draw.circle(canvas, skin, (center[0], center[1] + 0.9 * u), 3.4 * u)
    if long_hair:
        pygame.draw.ellipse(canvas, hair, (center[0] - 4.8 * u, center[1] - 1 * u, 9.6 * u, 4 * u), max(1, round(u)))
    for dx in (-1.4, 1.4):  # yeux fermés
        pygame.draw.line(canvas, shade(skin, -90), (center[0] + (dx - 0.7) * u, center[1] + 1.2 * u),
                         (center[0] + (dx + 0.7) * u, center[1] + 1.2 * u), max(1, round(0.5 * u)))
    return pygame.transform.smoothscale(canvas, (max(1, round(w * scale)), max(1, round(h * scale))))


def sleeper_image(persona: Persona, blanket: tuple, scale: float) -> pygame.Surface:
    """Dormeur vu de dessus : la tête sur l'oreiller, le corps en bosse sous la douillette."""
    palette, style = _palette(persona)
    key = tuple(tuple(palette[k]) for k in ("T", "P", "S", "H", "E")) + (bool(style["long_hair"]),)
    return _render_sleeper(key, tuple(blanket), persona.age < 13, round(scale, 3))
