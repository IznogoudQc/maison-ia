"""Scénario « terrain » : un grand lot boisé avec un étang, une tente et un feu de camp.

La forêt est générée à partir d'une graine : les mêmes arbres reviennent à chaque partie,
ce qui permet de ne sauvegarder que les arbres coupés.
"""

from __future__ import annotations

import math
import random

from world.house import House, InteractiveObject, Layout, Pos

ROOM = "Terrain"
SPECIES = (("Érable", 0.45), ("Sapin", 0.35), ("Bouleau", 0.20))
CLEARING_RADIUS = 9        # pas d'arbre autour du campement
MEADOW_RADIUS = 16         # prairie clairsemée autour de la clairière
FOREST_BLOBS = 16


def tree_id(pos: Pos) -> str:
    return f"arbre_{pos[0]}_{pos[1]}"


def camp_center(width: int, height: int) -> Pos:
    return width // 2, height - 14


def terrain_layout(width: int = 120, height: int = 80, seed: int | None = 42,
                   density: float = 1.0) -> Layout:
    rng = random.Random(seed)
    street_y, sidewalk_y = height - 1, height - 2
    cx, cy = camp_center(width, height)

    # Étang dans le quart nord-ouest
    px, py = rng.randint(width // 6, width // 3), rng.randint(height // 5, height // 3)
    rx, ry = rng.randint(7, 10), rng.randint(4, 6)
    water = {(x, y) for x in range(px - rx, px + rx + 1) for y in range(py - ry, py + ry + 1)
             if ((x - px) / rx) ** 2 + ((y - py) / ry) ** 2 <= 1.0 and 0 <= x < width and 0 <= y < sidewalk_y}

    surfaces: dict[Pos, str] = {(x, sidewalk_y): "concrete" for x in range(width)}
    path = {(cx, y) for y in range(cy + 5, sidewalk_y)}
    camp_ground = {(x, y) for x in range(cx - 4, cx + 5) for y in range(cy - 2, cy + 5)
                   if math.hypot(x - cx, (y - cy) * 1.3) <= 4.2}
    surfaces |= {p: "dirt" for p in path | camp_ground}

    objects = _camp_objects(cx, cy, street_y, sidewalk_y)
    purchase = {  # emplacements réservés aux achats (aucun arbre n'y pousse)
        "auto": InteractiveObject("auto", "auto", "Auto", ROOM, (cx + 4, cy + 7, 2, 3), [(cx + 3, cy + 8)]),
        "bbq": InteractiveObject("bbq", "bbq", "BBQ", ROOM, (cx + 4, cy, 1, 1), [(cx + 4, cy + 1)]),
    }
    occupied = {t for o in [*objects, *purchase.values()] for t in o.tiles}
    occupied |= {p for o in [*objects, *purchase.values()] for p in o.use_positions}

    # Massifs forestiers : probabilité forte au centre d'un massif, faible en prairie
    blobs = [(rng.randrange(width), rng.randrange(sidewalk_y), rng.uniform(7, 16)) for _ in range(FOREST_BLOBS)]
    trees: list[InteractiveObject] = []
    tree_tiles: set[Pos] = set()
    for y in range(sidewalk_y - 1):
        for x in range(width):
            pos = (x, y)
            near_water = any((x + dx, y + dy) in water for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            if pos in occupied or pos in surfaces or near_water:
                continue
            camp = math.hypot(x - cx, y - cy)
            if camp < CLEARING_RADIUS or abs(x - cx) <= 1 and y > cy:
                continue
            chance = 0.05
            for bx, by, radius in blobs:
                d = math.hypot(x - bx, y - by)
                if d < radius:
                    chance = max(chance, 0.15 + 0.6 * (1 - d / radius))
            if camp < MEADOW_RADIUS:
                chance *= 0.25
            if rng.random() < min(0.9, chance * density):
                label = rng.choices([s for s, _ in SPECIES], weights=[w for _, w in SPECIES])[0]
                trees.append(InteractiveObject(tree_id(pos), "arbre", label, ROOM, (x, y, 1, 1)))
                tree_tiles.add(pos)

    walkable = {(x, y) for x in range(width) for y in range(sidewalk_y + 1)} - water - tree_tiles - \
        {t for o in objects for t in o.tiles}
    for tree in trees:
        tree.use_positions = tree_spots(tree.rect[:2], walkable)

    spawn = [(x, y) for x in range(cx - 2, cx + 3) for y in range(cy + 1, cy + 3)]
    return Layout(
        name="terrain", width=width, height=height,
        rooms={ROOM: (0, 0, width - 1, sidewalk_y)}, outdoor_rooms={ROOM}, doors=[],
        street={(x, street_y) for x in range(width)}, surfaces=surfaces, fences=set(),
        objects=objects + trees, purchase_objects=purchase, spawn_tiles=spawn, water=water,
        catalog=("bbq", "scie"), wild=True, labels=False,
    )


def build_house(scenario: str, width: int = 120, height: int = 80, seed: int | None = 42,
                density: float = 1.0) -> House:
    """Le monde du scénario : la maison des Gagnon, ou le terrain boisé à bâtir."""
    if scenario == "terrain":
        return House(terrain_layout(width, height, seed, density))
    return House()


def tree_spots(pos: Pos, walkable: set[Pos]) -> list[Pos]:
    """Cases d'où l'on peut couper l'arbre : ses voisines libres (la forêt se coupe par la lisière)."""
    x, y = pos
    return [p for p in ((x, y + 1), (x - 1, y), (x + 1, y), (x, y - 1)) if p in walkable]


def _camp_objects(cx: int, cy: int, street_y: int, sidewalk_y: int) -> list[InteractiveObject]:
    """Le campement de départ : tout ce qu'un couple a pour vivre en attendant la maison."""
    return [
        InteractiveObject("tente", "lit", "Tente", ROOM, (cx - 5, cy - 3, 3, 2), [(cx - 5, cy - 1), (cx - 3, cy - 1)],
                          quality=0.75),
        InteractiveObject("feu", "cuisiniere", "Feu de camp", ROOM, (cx + 1, cy - 1, 1, 1), [(cx + 1, cy)],
                          quality=0.8),
        # Places autour du feu (objet sans tuile : on s'assoit sur des bûches)
        InteractiveObject("bancs_feu", "feu", "Autour du feu", ROOM, (cx + 1, cy - 1, 0, 0),
                          [(cx, cy - 1), (cx + 2, cy - 1), (cx + 1, cy - 2)]),
        InteractiveObject("glaciere", "frigo", "Glacière", ROOM, (cx - 2, cy, 1, 1), [(cx - 2, cy + 1)]),
        InteractiveObject("table_pique_nique", "table", "Table de pique-nique", ROOM, (cx - 1, cy + 3, 3, 1),
                          [(cx - 1, cy + 2), (cx + 1, cy + 2), (cx - 1, cy + 4), (cx + 1, cy + 4)]),
        InteractiveObject("baril", "douche", "Baril d'eau de pluie", ROOM, (cx - 6, cy + 1, 1, 1),
                          [(cx - 6, cy + 2)], quality=0.55),
        InteractiveObject("becosse", "deco", "Bécosse", ROOM, (cx - 9, cy - 2, 1, 2)),
        InteractiveObject("corde_bois", "deco", "Corde de bois", ROOM, (cx + 3, cy - 3, 2, 1)),
        InteractiveObject("porte", "porte", "Arrêt d'autobus", ROOM, (cx, street_y, 1, 1), [(cx, sidewalk_y)]),
        InteractiveObject("boite_lettres", "deco", "Boîte aux lettres", ROOM, (cx + 2, sidewalk_y, 1, 1)),
    ]
