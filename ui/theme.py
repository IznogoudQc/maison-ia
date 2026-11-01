"""Couleurs et polices partagées par l'interface."""

from __future__ import annotations

from functools import cache

import pygame

BACKGROUND = (32, 32, 38)
WALL = (62, 56, 62)
DOOR = (150, 120, 85)
TEXT = (235, 235, 240)
TEXT_DIM = (160, 160, 172)
TEXT_DARK = (40, 40, 48)
PANEL = (44, 44, 54)
PANEL_BORDER = (80, 80, 96)
ACCENT = (255, 205, 80)

ROOM_COLORS: dict[str, tuple[int, int, int]] = {
    "Chambre parents": (214, 196, 170),
    "Chambre ado": (186, 196, 222),
    "Chambre enfant": (228, 212, 166),
    "Salle de bain": (196, 226, 232),
    "Couloir": (200, 190, 176),
    "Cuisine": (232, 226, 204),
    "Salon": (206, 184, 158),
}

OBJECT_COLORS: dict[str, tuple[int, int, int]] = {
    "frigo": (236, 241, 246),
    "cuisiniere": (88, 88, 96),
    "table": (140, 96, 60),
    "lit": (110, 132, 190),
    "ordi": (58, 68, 92),
    "jouets": (222, 120, 78),
    "douche": (140, 196, 230),
    "tele": (120, 72, 72),
    "livres": (118, 80, 50),
    "porte": (128, 84, 44),
    "deco": (156, 136, 112),
}


@cache
def font(size: int, bold: bool = False) -> pygame.font.Font:
    # Segoe UI couvre les accents sous Windows ; repli sur la police par défaut
    return pygame.font.SysFont("segoeui,arial,dejavusans", size, bold=bold)
