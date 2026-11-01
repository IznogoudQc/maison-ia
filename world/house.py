"""Maison : grille de tuiles, pièces, murs et objets interactifs."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

Pos = tuple[int, int]

WIDTH, HEIGHT = 37, 24

# Intérieurs des pièces (x0, y0, x1, y1) inclusifs ; tout le reste est mur
ROOMS: dict[str, tuple[int, int, int, int]] = {
    "Chambre parents": (1, 1, 11, 8),
    "Chambre ado": (13, 1, 21, 8),
    "Chambre enfant": (23, 1, 29, 8),
    "Salle de bain": (31, 1, 35, 8),
    "Couloir": (1, 10, 35, 11),
    "Cuisine": (1, 13, 13, 22),
    "Salon": (15, 13, 35, 22),
}

# Ouvertures entre les pièces (tuiles franchissables sans pièce associée)
DOORS: list[Pos] = [(6, 9), (17, 9), (26, 9), (33, 9), (7, 12), (25, 12), (14, 17)]


@dataclass
class InteractiveObject:
    id: str
    kind: str
    label: str
    room: str
    rect: tuple[int, int, int, int]  # x, y, largeur, hauteur (tuiles bloquées)
    use_positions: list[Pos] = field(default_factory=list)

    @property
    def tiles(self) -> list[Pos]:
        x, y, w, h = self.rect
        return [(x + dx, y + dy) for dx in range(w) for dy in range(h)]

    @property
    def capacity(self) -> int:
        return len(self.use_positions)


# Objets : ceux sans use_positions sont décoratifs
OBJECTS: list[InteractiveObject] = [
    InteractiveObject("frigo", "frigo", "Frigo", "Cuisine", (1, 13, 2, 1), [(1, 14)]),
    InteractiveObject("cuisiniere", "cuisiniere", "Cuisinière", "Cuisine", (4, 13, 2, 1), [(4, 14)]),
    InteractiveObject("comptoir", "deco", "Comptoir", "Cuisine", (7, 13, 3, 1)),
    InteractiveObject("table", "table", "Table", "Cuisine", (4, 17, 4, 2),
                      [(3, 17), (8, 17), (5, 16), (6, 19)]),
    InteractiveObject("lit_parents", "lit", "Lit des parents", "Chambre parents", (3, 2, 4, 4),
                      [(2, 3), (7, 3)]),
    InteractiveObject("commode", "deco", "Commode", "Chambre parents", (9, 1, 2, 1)),
    InteractiveObject("lit_ado", "lit", "Lit de l'ado", "Chambre ado", (19, 2, 2, 4), [(18, 3)]),
    InteractiveObject("ordi", "ordi", "Ordi", "Chambre ado", (14, 1, 2, 1), [(14, 2)]),
    InteractiveObject("lit_enfant", "lit", "Lit de l'enfant", "Chambre enfant", (27, 2, 2, 3), [(26, 3)]),
    InteractiveObject("jouets", "jouets", "Coffre à jouets", "Chambre enfant", (23, 7, 2, 1), [(24, 6)]),
    InteractiveObject("douche", "douche", "Douche", "Salle de bain", (34, 1, 2, 2), [(33, 2)]),
    InteractiveObject("toilette", "deco", "Toilette", "Salle de bain", (35, 7, 1, 1)),
    InteractiveObject("tele", "deco", "Télé", "Salon", (28, 13, 4, 1)),
    InteractiveObject("canape", "tele", "Canapé (télé)", "Salon", (27, 17, 6, 1),
                      [(28, 16), (30, 16), (32, 16)]),
    InteractiveObject("biblio", "livres", "Bibliothèque", "Salon", (35, 19, 1, 3), [(34, 20)]),
    InteractiveObject("porte", "porte", "Porte d'entrée", "Salon", (30, 23, 1, 1), [(30, 22)]),
]


class House:
    def __init__(self) -> None:
        self.width = WIDTH
        self.height = HEIGHT
        # Nom de pièce par tuile ; None = mur (ou porte, voir self.doors)
        self.room_grid: list[list[str | None]] = [[None] * WIDTH for _ in range(HEIGHT)]
        self.floor: set[Pos] = set()
        for name, (x0, y0, x1, y1) in ROOMS.items():
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    self.room_grid[y][x] = name
                    self.floor.add((x, y))
        self.doors: set[Pos] = set(DOORS)
        self.floor |= self.doors
        self.objects: dict[str, InteractiveObject] = {o.id: o for o in OBJECTS}
        self.blocked: set[Pos] = {t for o in OBJECTS for t in o.tiles}

    def in_bounds(self, pos: Pos) -> bool:
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, pos: Pos) -> bool:
        return pos in self.floor and pos not in self.blocked

    def is_wall(self, pos: Pos) -> bool:
        return pos not in self.floor

    def room_at(self, pos: Pos) -> str | None:
        if not self.in_bounds(pos):
            return None
        x, y = pos
        return self.room_grid[y][x]

    def objects_of_kind(self, kind: str) -> list[InteractiveObject]:
        return [o for o in self.objects.values() if o.kind == kind]

    def walkable_tiles(self, room: str | None = None) -> list[Pos]:
        tiles = [p for p in self.floor if self.is_walkable(p) and p not in self.doors]
        if room is not None:
            tiles = [p for p in tiles if self.room_at(p) == room]
        return sorted(tiles)

    def random_tile(self, rng: random.Random, room: str | None = None) -> Pos:
        return rng.choice(self.walkable_tiles(room))
