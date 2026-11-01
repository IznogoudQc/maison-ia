"""Monde en tuiles : pièces, cours, murs, clôtures, eau et objets interactifs.

House est générique : elle se construit à partir d'un Layout. house_layout() décrit la maison
de la famille Gagnon (scénario « maison ») ; world/terrain.py génère le terrain boisé du
scénario « terrain ».
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

Pos = tuple[int, int]

WIDTH, HEIGHT = 49, 33

# Intérieurs des pièces et des cours (x0, y0, x1, y1) inclusifs ; le reste est mur, clôture ou rue
ROOMS: dict[str, tuple[int, int, int, int]] = {
    "Chambre parents": (1, 1, 11, 8),
    "Chambre ado": (13, 1, 21, 8),
    "Chambre enfant": (23, 1, 29, 8),
    "Salle de bain": (31, 1, 35, 8),
    "Couloir": (1, 10, 35, 11),
    "Cuisine": (1, 13, 13, 22),
    "Salon": (15, 13, 35, 22),
    "Cour arrière": (37, 1, 47, 23),
    "Cour avant": (0, 24, 47, 31),
}
OUTDOOR_ROOMS = {"Cour arrière", "Cour avant"}

# Ouvertures (tuiles franchissables sans pièce associée) : portes intérieures, porte d'entrée, porte-patio
DOORS: list[Pos] = [(6, 9), (17, 9), (26, 9), (33, 9), (7, 12), (25, 12), (14, 17), (30, 23), (36, 18)]

STREET_Y = HEIGHT - 1
# Revêtements particuliers dans la cour avant (le reste des cours est en gazon)
DRIVEWAY = {(x, y) for x in range(40, 44) for y in range(24, 32)}
WALKWAY = {(30, y) for y in range(24, 31)}
SIDEWALK = {(x, 31) for x in range(WIDTH - 1)}

# Fenêtres sur les murs extérieurs : (x, y, verticale)
WINDOWS: list[tuple[int, int, bool]] = [
    (3, 0, False), (8, 0, False), (16, 0, False), (19, 0, False), (25, 0, False), (33, 0, False),
    (4, 23, False), (9, 23, False), (19, 23, False), (24, 23, False), (34, 23, False),
    (0, 4, True), (0, 17, True), (0, 20, True), (36, 5, True), (36, 16, True), (36, 20, True),
]
# Cases de mur (face peinte visible) du salon où accrocher les cadres commémoratifs
MEMORIAL_TILES = [(17, 12), (19, 12), (21, 12), (23, 12)]


@dataclass
class InteractiveObject:
    id: str
    kind: str
    label: str
    room: str
    rect: tuple[int, int, int, int]  # x, y, largeur, hauteur (tuiles bloquées)
    use_positions: list[Pos] = field(default_factory=list)
    quality: float = 1.0             # multiplie les effets des actions faites ici (baril < douche)

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
    # Extérieur
    InteractiveObject("porte", "porte", "Arrêt d'autobus", "Cour avant", (30, STREET_Y, 1, 1), [(30, 31)]),
    InteractiveObject("cabanon", "deco", "Cabanon", "Cour arrière", (44, 2, 3, 3)),
    InteractiveObject("patio", "patio", "Table de patio", "Cour arrière", (39, 6, 2, 2),
                      [(38, 6), (41, 7), (39, 8)]),
    InteractiveObject("balancoire", "balancoire", "Balançoire", "Cour arrière", (45, 18, 2, 1), [(45, 19)]),
    InteractiveObject("arbre_1", "arbre", "Érable", "Cour arrière", (45, 9, 2, 2)),
    InteractiveObject("arbre_2", "arbre", "Érable", "Cour avant", (3, 26, 2, 2)),
    InteractiveObject("arbre_3", "arbre", "Érable", "Cour avant", (15, 27, 2, 2)),
    InteractiveObject("arbre_4", "arbre", "Érable", "Cour avant", (24, 26, 2, 2)),
    InteractiveObject("boite_lettres", "deco", "Boîte aux lettres", "Cour avant", (32, 30, 1, 1)),
]

# Objets qui n'apparaissent qu'une fois achetés (voir sim/economy.py, CATALOG)
PURCHASE_OBJECTS: dict[str, InteractiveObject] = {
    "auto": InteractiveObject("auto", "auto", "Auto", "Cour avant", (41, 25, 2, 3), [(40, 26)]),
    "piscine": InteractiveObject("piscine", "piscine", "Piscine", "Cour arrière", (40, 12, 5, 4),
                                 [(39, 13), (39, 14), (45, 13), (45, 14)]),
    "bbq": InteractiveObject("bbq", "bbq", "BBQ", "Cour arrière", (39, 20, 1, 1), [(39, 19)]),
}


@dataclass
class Layout:
    """Description complète d'une carte ; House en tire la grille et les objets."""
    name: str
    width: int
    height: int
    rooms: dict[str, tuple[int, int, int, int]]
    outdoor_rooms: set[str]
    doors: list[Pos]
    street: set[Pos]
    surfaces: dict[Pos, str]                 # revêtements : asphalt, pavers, concrete, dirt
    fences: set[Pos]
    objects: list[InteractiveObject]
    purchase_objects: dict[str, InteractiveObject]
    spawn_room: str | None = None            # pièce de départ des agents (None = spawn_tiles)
    spawn_tiles: list[Pos] = field(default_factory=list)
    water: set[Pos] = field(default_factory=set)
    windows: list[tuple[int, int, bool]] = field(default_factory=list)
    memorial_tiles: list[Pos] = field(default_factory=list)
    catalog: tuple[str, ...] | None = None   # achats possibles (None = tout le CATALOG)
    wild: bool = False                       # terrain sauvage : pas de pelouse à tondre ni d'amende
    labels: bool = True                      # noms des pièces affichés sur la carte


def house_layout() -> Layout:
    """La maison de banlieue de la famille Gagnon, avec ses deux cours."""
    floor = {(x, y) for x0, y0, x1, y1 in ROOMS.values()
             for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)} | set(DOORS)
    street = {(x, STREET_Y) for x in range(WIDTH)}
    # Clôture : tout ce qui n'est ni sol, ni rue, ni la maison elle-même
    fences = {(x, y) for x in range(WIDTH) for y in range(HEIGHT)
              if (x, y) not in floor and (x, y) not in street and not (x <= 36 and y <= 23)}
    surfaces = {p: "asphalt" for p in DRIVEWAY}
    surfaces |= {p: "pavers" for p in WALKWAY}
    surfaces |= {p: "concrete" for p in SIDEWALK}
    return Layout("maison", WIDTH, HEIGHT, dict(ROOMS), set(OUTDOOR_ROOMS), list(DOORS), street,
                  surfaces, fences, list(OBJECTS), dict(PURCHASE_OBJECTS), spawn_room="Cuisine",
                  windows=list(WINDOWS), memorial_tiles=list(MEMORIAL_TILES),
                  catalog=("tondeuse", "bbq", "piscine", "auto"))


class House:
    def __init__(self, layout: Layout | None = None) -> None:
        layout = layout or house_layout()
        self.layout = layout
        self.width = layout.width
        self.height = layout.height
        self.rooms = layout.rooms
        self.outdoor_rooms = layout.outdoor_rooms
        self.purchase_objects = layout.purchase_objects
        # Nom de pièce par tuile ; None = mur, clôture, rue, eau (ou porte, voir self.doors)
        self.room_grid: list[list[str | None]] = [[None] * layout.width for _ in range(layout.height)]
        self.floor: set[Pos] = set()
        for name, (x0, y0, x1, y1) in layout.rooms.items():
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    if (x, y) in layout.water:
                        continue
                    self.room_grid[y][x] = name
                    self.floor.add((x, y))
        self.doors: set[Pos] = set(layout.doors)
        self.floor |= self.doors
        self.street: set[Pos] = set(layout.street)
        self.fences: set[Pos] = set(layout.fences)
        self.water: set[Pos] = set(layout.water)
        self.objects: dict[str, InteractiveObject] = {}
        self.blocked: set[Pos] = set()
        self._spots: dict[Pos, InteractiveObject] = {}
        for obj in layout.objects:
            self._place(obj)
        self.removed: set[str] = set()  # objets de départ retirés (arbres coupés) : sauvegardés
        self.revision = 0      # incrémenté à chaque changement de la carte (le rendu se met à jour)
        self.dirty: set[Pos] = set()   # tuiles à redessiner depuis le dernier rendu
        self._walkable_cache: tuple[int, list[Pos]] | None = None

    # ------------------------------------------------------------------ objets

    def _place(self, obj: InteractiveObject) -> None:
        self.objects[obj.id] = obj
        self.blocked |= set(obj.tiles)
        for pos in obj.use_positions:
            self._spots[pos] = obj

    def add_object(self, obj: InteractiveObject) -> None:
        if obj.id in self.objects:
            return
        self._place(obj)
        self.dirty |= set(obj.tiles)
        self.revision += 1

    def remove_object(self, obj_id: str) -> InteractiveObject | None:
        """Retire un objet (arbre coupé, meuble remplacé) et libère ses tuiles."""
        obj = self.objects.pop(obj_id, None)
        if obj is None:
            return None
        if any(o.id == obj_id for o in self.layout.objects):
            self.removed.add(obj_id)
        tiles = set(obj.tiles)
        self.blocked -= tiles
        self.blocked |= {t for o in self.objects.values() for t in o.tiles if t in tiles}  # chevauchements
        for pos in obj.use_positions:
            if self._spots.get(pos) is obj:
                del self._spots[pos]
        self.dirty |= tiles
        self.revision += 1
        return obj

    def set_use_positions(self, obj: InteractiveObject, positions: list[Pos]) -> None:
        """Nouvelles cases d'usage (un arbre voisin a été coupé : on l'atteint par un autre côté)."""
        for pos in obj.use_positions:
            if self._spots.get(pos) is obj:
                del self._spots[pos]
        obj.use_positions = positions
        for pos in positions:
            self._spots.setdefault(pos, obj)

    def object_at_spot(self, pos: Pos) -> InteractiveObject | None:
        """Objet dont pos est une case d'usage (pour la qualité et l'orientation)."""
        return self._spots.get(pos)

    # ------------------------------------------------------------------ tuiles

    def in_bounds(self, pos: Pos) -> bool:
        x, y = pos
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, pos: Pos) -> bool:
        return pos in self.floor and pos not in self.blocked

    def is_wall(self, pos: Pos) -> bool:
        return pos not in self.floor

    def is_outdoor(self, pos: Pos) -> bool:
        return self.room_at(pos) in self.outdoor_rooms

    def surface_at(self, pos: Pos) -> str | None:
        """Revêtement extérieur particulier (entrée, allée, trottoir, chemin), sinon None."""
        return self.layout.surfaces.get(pos)

    def room_at(self, pos: Pos) -> str | None:
        if not self.in_bounds(pos):
            return None
        x, y = pos
        return self.room_grid[y][x]

    def objects_of_kind(self, kind: str) -> list[InteractiveObject]:
        return [o for o in self.objects.values() if o.kind == kind]

    def walkable_tiles(self, room: str | None = None) -> list[Pos]:
        if self._walkable_cache is None or self._walkable_cache[0] != self.revision:
            tiles = sorted(p for p in self.floor if self.is_walkable(p) and p not in self.doors)
            self._walkable_cache = (self.revision, tiles)
        tiles = self._walkable_cache[1]
        if room is not None:
            tiles = [p for p in tiles if self.room_at(p) == room]
        return tiles

    def lawn_tiles(self) -> list[Pos]:
        """Cases de gazon franchissables (pour tondre)."""
        return [p for p in self.walkable_tiles() if self.is_outdoor(p) and self.surface_at(p) is None]

    def random_tile(self, rng: random.Random, room: str | None = None) -> Pos:
        return rng.choice(self.walkable_tiles(room))

    def spawn_tile(self, rng: random.Random) -> Pos:
        """Case de départ d'un agent : dans la pièce de départ, ou parmi les cases prévues."""
        if self.layout.spawn_room is not None:
            return self.random_tile(rng, self.layout.spawn_room)
        tiles = [p for p in self.layout.spawn_tiles if self.is_walkable(p)]
        return rng.choice(tiles or self.walkable_tiles())
