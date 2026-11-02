"""Petits éléments animés en haute résolution : chien, bébé, nageur, objets tenus, flammes, vapeur, ruban.

Chaque fonction dessine directement sur l'écran (pos en px écran, scale = px écran par px de base) sur une
petite toile suréchantillonnée, refaite à chaque image puisque tout bouge. light = (obscurité, teinte).
"""

from __future__ import annotations

import math

import pygame

from agents.persona import Persona
from ui.pawns import lit
from ui.sprites import OUTLINE, _palette, shade

SUPERSAMPLE = 3
LEGO = [(230, 60, 60), (60, 120, 230), (250, 210, 50), (70, 180, 90), (240, 240, 240)]


class _Toile:
    """Petite toile de w x h px de base, agrandie à l'échelle de l'écran puis suréchantillonnée."""

    def __init__(self, w: float, h: float, scale: float) -> None:
        self.scale, self.u = scale, scale * SUPERSAMPLE
        self.size = (max(1, round(w * scale)), max(1, round(h * scale)))
        self.c = pygame.Surface((self.size[0] * SUPERSAMPLE, self.size[1] * SUPERSAMPLE), pygame.SRCALPHA)
        self.line = max(1.0, 0.9 * self.u)

    def p(self, x: float, y: float) -> tuple[float, float]:
        return x * self.u, y * self.u

    def circle(self, color, x, y, r, outline: bool = True) -> None:
        if outline:
            pygame.draw.circle(self.c, OUTLINE, self.p(x, y), r * self.u + self.line)
        pygame.draw.circle(self.c, color, self.p(x, y), r * self.u)

    def ellipse(self, color, x, y, w, h, outline: bool = True) -> None:
        rect = pygame.Rect(round(x * self.u), round(y * self.u), round(w * self.u), round(h * self.u))
        if outline:
            pygame.draw.ellipse(self.c, OUTLINE, rect.inflate(self.line * 2, self.line * 2))
        pygame.draw.ellipse(self.c, color, rect)

    def rect(self, color, x, y, w, h, radius: float = 0.8, outline: bool = True) -> None:
        rect = pygame.Rect(round(x * self.u), round(y * self.u), round(w * self.u), round(h * self.u))
        if outline:
            pygame.draw.rect(self.c, OUTLINE, rect.inflate(self.line * 2, self.line * 2),
                             border_radius=round(radius * self.u + self.line))
        pygame.draw.rect(self.c, color, rect, border_radius=round(radius * self.u))

    def segment(self, color, a, b, width: float = 0.8) -> None:
        pygame.draw.line(self.c, color, self.p(*a), self.p(*b), max(1, round(width * self.u)))

    def translucent(self, draw) -> None:
        """Dessin avec transparence (ombre, ronds dans l'eau, vapeur) mélangé à la toile."""
        layer = pygame.Surface(self.c.get_size(), pygame.SRCALPHA)
        draw(layer)
        self.c.blit(layer, (0, 0))

    def blit(self, surface: pygame.Surface, topleft: tuple[float, float], light=None) -> None:
        image = pygame.transform.smoothscale(self.c, self.size)
        if light is not None:
            image = lit(image, *light)
        surface.blit(image, (round(topleft[0]), round(topleft[1])))


def draw_dog(surface: pygame.Surface, pos: tuple[float, float], scale: float, t: float, facing: int,
             light=None) -> None:
    """Petit chien brun vu de côté, la queue qui bat ; pos = sous les pattes."""
    toile = _Toile(16, 10, scale)
    u = toile.u
    body = (150, 100, 56)
    toile.translucent(lambda s: pygame.draw.ellipse(s, (20, 16, 18, 70), (3 * u, 7.5 * u, 10 * u, 2.5 * u)))
    f, cx = facing, 8
    for dx in (-3, 2.2):
        toile.rect(shade(body, -30), cx + dx * f - 0.6, 5.5, 1.3, 3, radius=0.4, outline=False)   # pattes
    wag = math.sin(t * 16) * 1.2
    toile.segment(OUTLINE, (cx - 4.6 * f, 4.4), (cx - 7 * f, 2.2 + wag), 1.6)
    toile.segment(body, (cx - 4.6 * f, 4.4), (cx - 7 * f, 2.2 + wag), 0.9)                  # la queue
    toile.ellipse(body, cx - 4.5, 2.6, 9, 4.4)
    toile.circle(body, cx + 4.6 * f, 2.6, 2.4)
    toile.ellipse(shade(body, -40), cx + 3.2 * f - 1, 0.8, 2, 2.6, outline=False)            # l'oreille
    toile.circle((30, 24, 20), cx + 5.6 * f, 2.2, 0.5, outline=False)
    toile.circle((30, 24, 20), cx + 6.9 * f, 3.0, 0.45, outline=False)                       # la truffe
    toile.blit(surface, (pos[0] - 8 * scale, pos[1] - 9 * scale), light)


def draw_baby(surface: pygame.Surface, persona: Persona, center: tuple[float, float], scale: float,
              sleeping: bool, light=None) -> None:
    """Bébé emmailloté dans son berceau : couverture à la couleur de sa fiche, petite tête."""
    palette, _style = _palette(persona)
    toile = _Toile(12, 12, scale)
    toile.ellipse(shade(tuple(persona.color), 10), 2, 4.5, 8, 6.5)
    toile.circle(tuple(palette["S"]), 6, 3.8, 2.8)
    toile.ellipse(tuple(palette["H"]), 4, 0.9, 4, 1.8, outline=False)
    for dx in (-1, 1):
        if sleeping:
            toile.segment(shade(tuple(palette["S"]), -90), (6 + dx - 0.5, 4.2), (6 + dx + 0.5, 4.2), 0.4)
        else:
            toile.circle(tuple(palette["E"]), 6 + dx, 4.0, 0.45, outline=False)
    toile.blit(surface, (center[0] - 6 * scale, center[1] - 7 * scale), light)


def draw_swimmer(surface: pygame.Surface, persona: Persona, center: tuple[float, float], scale: float,
                 t: float, light=None) -> None:
    """Tête qui dépasse de l'eau, avec des ronds dans l'eau autour."""
    palette, style = _palette(persona)
    toile = _Toile(18, 14, scale)
    u = toile.u
    phase = (t * 0.8) % 1.0
    for k in (0.0, 0.5):
        grow = (phase + k) % 1.0
        w, h = (8 + grow * 9) * u, (3 + grow * 4) * u

        def ring(s, w=w, h=h, grow=grow):
            pygame.draw.ellipse(s, (200, 236, 255, round(200 * (1 - grow))), (9 * u - w / 2, 9.5 * u - h / 2, w, h),
                                max(1, round(0.6 * u)))
        toile.translucent(ring)
    bob = math.sin(t * 3) * 0.6
    toile.circle(tuple(palette["H"]), 9, 6.5 + bob, 4.2)
    toile.circle(tuple(palette["S"]), 9, 7.4 + bob, 3.3, outline=False)
    if style["long_hair"]:
        toile.ellipse(tuple(palette["H"]), 4.6, 5.6 + bob, 8.8, 2.5, outline=False)
    for dx in (-1.3, 1.3):
        toile.circle(tuple(palette["E"]), 9 + dx, 7.4 + bob, 0.5, outline=False)
    toile.blit(surface, (center[0] - 9 * scale, center[1] - 9 * scale), light)


def draw_tool(surface: pygame.Surface, name: str, pos: tuple[float, float], scale: float, t: float,
              chainsaw: bool = False) -> None:
    """Objet tenu ou posé ; pos = la main (ou le centre pour les Lego et la tasse)."""
    toile = _Toile(16, 16, scale)
    cx, cy = 8, 8
    if name == "telephone":
        toile.rect((30, 30, 36), cx - 1.4, cy - 2, 2.8, 4, radius=0.5)
        glow = (120, 200, 255) if int(t * 3) % 4 else (200, 240, 255)
        toile.rect(glow, cx - 0.8, cy - 1.4, 1.6, 2.6, radius=0.3, outline=False)
    elif name == "livre":
        toile.rect((246, 244, 236), cx - 3.5, cy - 1, 7, 4, radius=0.4)
        toile.segment((150, 60, 50), (cx, cy - 1), (cx, cy + 3), 0.6)
        toile.segment((180, 180, 180), (cx - 2.6, cy + 0.5), (cx - 0.8, cy + 0.5), 0.3)
    elif name == "lego":
        for i, (dx, dy) in enumerate(((-6, 1), (5, 3), (-3, 5), (6, -2), (1, 6), (-7, -3))):
            toile.rect(LEGO[i % len(LEGO)], cx + dx * 0.9, cy + dy * 0.9, 2.4, 1.6, radius=0.3)
    elif name == "tondeuse":
        toile.rect((200, 50, 40), cx - 2.5, cy - 1, 6, 5, radius=1)
        toile.circle((30, 30, 30), cx - 2.5, cy + 4, 0.9, outline=False)
        toile.circle((30, 30, 30), cx + 3.5, cy + 4, 0.9, outline=False)
        toile.segment((60, 60, 60), (cx + 0.5, cy - 1), (cx + 0.5, cy - 5), 0.6)
    elif name == "marteau":
        swing = abs(math.sin(t * 7))
        tip = (cx + 3, cy - 1 - swing * 4)
        toile.segment((120, 84, 50), (cx, cy), tip, 0.8)
        toile.rect((90, 90, 96), tip[0] - 1.4, tip[1] - 1, 2.8, 2, radius=0.3)
    elif name == "hache":
        _axe(surface, pos, scale, t, chainsaw)
        return
    elif name == "tasse":
        toile.rect((240, 240, 236), cx - 1.5, cy - 1.5, 3, 3, radius=0.6)
        toile.circle((110, 70, 40), cx, cy, 0.8, outline=False)
    toile.blit(surface, (pos[0] - 8 * scale, pos[1] - 8 * scale))


CHOPS_PER_SECOND = 1.4
IMPACT = 0.82          # moment du coup dans la cadence (0 -> 1)


def chop_phase(t: float) -> float:
    """Cadence des coups de hache : 0 -> 1 ; le coup porte à partir d'IMPACT."""
    return (t * CHOPS_PER_SECOND) % 1.0


def _axe(surface: pygame.Surface, pos: tuple[float, float], scale: float, t: float, chainsaw: bool) -> None:
    """Grosse hache levée puis abattue en cadence (ou scie à chaîne qui vibre), avec des copeaux au coup."""
    toile = _Toile(28, 28, scale)
    cx, cy = 14, 16
    phase = chop_phase(t)
    if chainsaw:
        jitter = 0.6 if int(t * 30) % 2 else 0
        toile.rect((230, 120, 30), cx - 2, cy - 2 + jitter, 6, 4.5, radius=1)
        toile.rect((190, 190, 196), cx + 4, cy - 0.5 + jitter, 8, 2, radius=0.9)
        chips, burst = True, (t * 3) % 1.0
    else:
        # Levée lente, coup sec : l'angle passe de 110° (levée) à -20° (sur le tronc)
        if phase < IMPACT:
            lift = phase / IMPACT
        else:
            lift = (1 - (phase - IMPACT) / (1 - IMPACT)) ** 3
        angle = math.radians(-20 + 130 * lift)
        tip = (cx + 9 * math.cos(angle), cy - 9 * math.sin(angle))
        toile.segment(OUTLINE, (cx, cy), tip, 2.0)
        toile.segment((150, 104, 62), (cx, cy), tip, 1.2)                     # le manche
        ux, uy = math.cos(angle), -math.sin(angle)
        head = [toile.p(tip[0] - uy * 2.6 + ux * 0.8, tip[1] + ux * 2.6 + uy * 0.8),
                toile.p(tip[0] + uy * 2.6 + ux * 0.8, tip[1] - ux * 2.6 + uy * 0.8),
                toile.p(tip[0] + uy * 1.6 - ux * 1.6, tip[1] - ux * 1.6 - uy * 1.6),
                toile.p(tip[0] - uy * 1.6 - ux * 1.6, tip[1] + ux * 1.6 - uy * 1.6)]
        pygame.draw.polygon(toile.c, OUTLINE, head, max(1, round(toile.line)))
        pygame.draw.polygon(toile.c, (196, 202, 212), head)                    # le fer
        chips, burst = phase >= IMPACT, (phase - IMPACT) / (1 - IMPACT)
    if chips:  # copeaux projetés au coup
        for k in range(5):
            a = k * 1.3 + 0.4
            d = 2 + burst * 7
            toile.circle((226, 196, 140), cx + 8 + math.cos(a) * d, cy + 1 - math.sin(a) * d * 0.7 + burst * 2,
                         0.7, outline=False)
    toile.blit(surface, (pos[0] - 14 * scale, pos[1] - 16 * scale))


def draw_stump(surface: pygame.Surface, pos: tuple[float, float], scale: float, light=None) -> None:
    """Souche laissée par un arbre abattu ; pos = centre de la case."""
    toile = _Toile(12, 10, scale)
    u = toile.u
    toile.translucent(lambda s: pygame.draw.ellipse(s, (20, 16, 18, 60), (2.5 * u, 4.5 * u, 9 * u, 4.5 * u)))
    toile.ellipse((110, 76, 48), 2.5, 3, 7, 5)
    toile.ellipse((206, 170, 118), 3.3, 3.5, 5.4, 3.4, outline=False)
    toile.ellipse((176, 136, 90), 4.6, 4.3, 2.8, 1.8, outline=False)          # les cernes
    toile.blit(surface, (pos[0] - 6 * scale, pos[1] - 6 * scale), light)


def draw_flames(surface: pygame.Surface, center: tuple[float, float], scale: float, t: float) -> None:
    """Flammes du feu de camp : trois langues qui dansent, plus une lueur."""
    toile = _Toile(16, 18, scale)
    u = toile.u
    toile.translucent(lambda s: pygame.draw.circle(s, (255, 170, 80, 60), (8 * u, 12 * u), 7 * u))
    for i, (color, height, half) in enumerate((((236, 96, 40), 10, 4.5), ((250, 170, 50), 7, 3.2),
                                                ((255, 236, 140), 4, 1.8))):
        flicker = math.sin(t * 9 + i * 1.7) * 1.4
        sway = math.sin(t * 5 + i) * 0.8
        points = [toile.p(8 - half, 13), toile.p(8 - half * 0.6, 10), toile.p(8 + sway, 13 - height - flicker),
                  toile.p(8 + half * 0.6, 10), toile.p(8 + half, 13)]
        pygame.draw.polygon(toile.c, color, points)
    toile.blit(surface, (center[0] - 8 * scale, center[1] - 13 * scale))


def draw_steam(surface: pygame.Surface, pos: tuple[float, float], scale: float, t: float,
               count: int = 3, height: float = 10) -> None:
    """Bouffées de vapeur qui montent en ondulant puis s'estompent ; pos = point de départ."""
    toile = _Toile(8, height + 6, scale)
    u = toile.u
    for i in range(count):
        phase = (t * 0.7 + i / count) % 1.0
        px, py = 4 + math.sin(phase * 6.3 + i) * 1.6, height + 3 - phase * height

        def puff(s, px=px, py=py, phase=phase):
            pygame.draw.circle(s, (245, 245, 250, round(200 * (1 - phase))), (px * u, py * u), (1.6 + phase * 1.4) * u)
        toile.translucent(puff)
    toile.blit(surface, (pos[0] - 4 * scale, pos[1] - (height + 3) * scale))


def draw_ribbon(surface: pygame.Surface, pos: tuple[float, float], scale: float) -> None:
    """Ruban rouge noué sur le tronc d'un arbre à couper ; pos = milieu du ruban."""
    toile = _Toile(8, 5, scale)
    toile.rect((220, 40, 40), 1.4, 1.6, 5.2, 1.8, radius=0.5)
    toile.segment((220, 40, 40), (6.2, 2.4), (7.4, 4.4), 0.7)
    toile.blit(surface, (pos[0] - 4 * scale, pos[1] - 2.5 * scale))
