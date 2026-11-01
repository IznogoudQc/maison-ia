"""Couleurs et polices partagées par l'interface."""

from __future__ import annotations

from functools import cache

import pygame

BACKGROUND = (32, 32, 38)
TEXT = (235, 235, 240)
TEXT_DIM = (160, 160, 172)
TEXT_DARK = (40, 40, 48)
PANEL = (44, 44, 54)
PANEL_BORDER = (80, 80, 96)
ACCENT = (255, 205, 80)

# Couleur de base du sol de chaque pièce (texture : voir sprites.FLOOR_STYLES)
ROOM_COLORS: dict[str, tuple[int, int, int]] = {
    "Chambre parents": (196, 154, 112),
    "Chambre ado": (120, 138, 186),
    "Chambre enfant": (206, 180, 112),
    "Salle de bain": (204, 228, 236),
    "Couloir": (176, 132, 92),
    "Cuisine": (230, 224, 206),
    "Salon": (186, 138, 94),
}


@cache
def font(size: int, bold: bool = False) -> pygame.font.Font:
    # Segoe UI couvre les accents sous Windows ; repli sur la police par défaut
    return pygame.font.SysFont("segoeui,arial,dejavusans", size, bold=bold)
