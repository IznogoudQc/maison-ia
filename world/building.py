"""Construction de la maison sur le terrain : types de pièces, placement, murs, portes, fenêtres, meubles.

L'IA décide du sens (quelles pièces, combien, de quelle taille, à côté de quoi) ; ce module fait la
géométrie : il place chaque pièce sur la grille sans chevauchement, perce les portes entre pièces
voisines et vers l'extérieur, met des fenêtres sur les murs extérieurs et meuble selon le type.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from world.house import House, InteractiveObject, Pos
from world.pathfinding import find_path

Rect = tuple[int, int, int, int]   # x0, y0, x1, y1 inclusifs (intérieur de la pièce)
SIDES = ("nord", "sud", "est", "ouest")
CAMP_MARGIN = 2           # distance minimale entre la maison et le campement
MAX_ROOMS = 8
WINDOW_EVERY = 3          # une fenêtre toutes les N cases de mur extérieur


@dataclass(frozen=True)
class Furniture:
    key: str                      # suffixe de l'id : « lit », « frigo »...
    kind: str                     # type d'objet (actions) : lit, frigo, cuisiniere, table, tele...
    label: str
    size: tuple[int, int]
    capacity: int = 1             # places d'usage voulues (lit double : 2)
    slot: str = "wall"            # wall : contre le mur nord ou un côté ; center : milieu ; facing : face au mur nord


@dataclass(frozen=True)
class RoomType:
    label: str
    width: tuple[int, int]        # bornes de l'intérieur (tuiles)
    height: tuple[int, int]
    furniture: tuple[Furniture, ...] = field(default_factory=tuple)
    floor: str = "wood"           # style de plancher (sprites.FLOOR_STYLES)
    purpose: str = ""


ROOM_TYPES: dict[str, RoomType] = {
    "cuisine": RoomType("Cuisine", (4, 8), (4, 7), (
        Furniture("frigo", "frigo", "Frigo", (1, 1)),
        Furniture("cuisiniere", "cuisiniere", "Cuisinière", (1, 1)),
        Furniture("comptoir", "deco", "Comptoir", (2, 1)),
        Furniture("table", "table", "Table", (2, 1), capacity=4, slot="center"),
    ), "ceramic", "cuisiner et manger au chaud"),
    "salle_de_bain": RoomType("Salle de bain", (2, 4), (2, 4), (
        Furniture("douche", "douche", "Douche", (1, 1)),
        Furniture("toilette", "deco", "Toilette", (1, 1)),
    ), "ceramic", "une vraie douche chaude"),
    "chambre": RoomType("Chambre", (3, 6), (3, 6), (
        Furniture("lit", "lit", "Lit double", (2, 2), capacity=2),
        Furniture("commode", "deco", "Commode", (1, 1)),
    ), "carpet", "dormir dans un vrai lit"),
    "salon": RoomType("Salon", (4, 9), (4, 8), (
        Furniture("tele", "deco", "Télé", (2, 1)),
        Furniture("canape", "tele", "Canapé (télé)", (3, 1), capacity=2, slot="facing"),
        Furniture("biblio", "livres", "Bibliothèque", (1, 1)),
    ), "wood", "relaxer, écouter la télé, lire"),
    "bureau": RoomType("Bureau", (3, 5), (3, 5), (
        Furniture("ordi", "ordi", "Ordi", (1, 1)),
        Furniture("biblio", "livres", "Bibliothèque", (1, 1)),
    ), "wood", "travailler, jouer à l'ordi"),
    "atelier": RoomType("Atelier", (3, 6), (3, 6), (
        Furniture("etabli", "deco", "Établi", (2, 1)),
    ), "wood", "bricoler, ranger les outils"),
}


def room_cost(room_type: str, width: int, height: int) -> tuple[float, int]:
    """Matériaux à acheter ($) et bûches du terrain pour bâtir une pièce (murs + plancher + toit)."""
    perimeter = 2 * (width + height) + 4
    money = 500 + 60 * width * height + (800 if room_type in ("cuisine", "salle_de_bain") else 0)  # plomberie
    wood = perimeter + width * height
    return round(money, -1), wood


WORK_BASE, WORK_PER_TILE = 8.0, 1.2   # heures de travail : fondation + par case de plancher


def work_hours(width: int, height: int) -> float:
    """Heures de travail d'une personne ordinaire pour bâtir la pièce."""
    return round(WORK_BASE + WORK_PER_TILE * width * height, 1)


class PlannedRoom(BaseModel):
    id: str
    type: str
    name: str
    rect: Rect                     # intérieur
    status: str = "plan"           # plan (à défricher), pret (terrain dégagé), chantier, bati
    anchor: str | None = None      # pièce à laquelle elle est collée
    side: str | None = None
    why: str = ""
    progress: float = 0.0          # heures de travail faites
    materials_paid: bool = False   # matériaux achetés au début du chantier
    contractor: bool = False       # un entrepreneur finit le travail
    wood_used: int = 0             # bûches déjà posées

    @property
    def work_needed(self) -> float:
        return work_hours(self.width, self.height)

    @property
    def fraction(self) -> float:
        return min(1.0, self.progress / self.work_needed)

    @property
    def wood_needed(self) -> int:
        return room_cost(self.type, self.width, self.height)[1]

    @property
    def materials_cost(self) -> float:
        return room_cost(self.type, self.width, self.height)[0]

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0] + 1

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1] + 1

    @property
    def area(self) -> int:
        return self.width * self.height

    def outer(self) -> Rect:
        x0, y0, x1, y1 = self.rect
        return x0 - 1, y0 - 1, x1 + 1, y1 + 1

    def interior_tiles(self) -> list[Pos]:
        x0, y0, x1, y1 = self.rect
        return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]

    def outer_tiles(self) -> list[Pos]:
        x0, y0, x1, y1 = self.outer()
        return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]

    def wall_tiles(self) -> list[Pos]:
        inside = set(self.interior_tiles())
        return [p for p in self.outer_tiles() if p not in inside]


class HousePlan(BaseModel):
    vision: str = ""
    rooms: list[PlannedRoom] = Field(default_factory=list)
    doors: list[Pos] = Field(default_factory=list)       # portes entre deux pièces voisines
    front_door: Pos | None = None                         # porte d'entrée, côté campement
    rejected: list[str] = Field(default_factory=list)   # pièces refusées par le moteur (et pourquoi)

    def room(self, room_id: str) -> PlannedRoom | None:
        return next((r for r in self.rooms if r.id == room_id), None)

    def built(self) -> list[PlannedRoom]:
        return [r for r in self.rooms if r.status == "bati"]

    def all_doors(self) -> set[Pos]:
        return set(self.doors) | ({self.front_door} if self.front_door else set())

    def next_room(self) -> PlannedRoom | None:
        """Prochaine pièce à préparer ou à bâtir, dans l'ordre choisi par le couple."""
        return next((r for r in self.rooms if r.status != "bati"), None)


# ---------------------------------------------------------------- placement


def _overlaps(a: Rect, b: Rect) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def placement_problem(house: House, plan: HousePlan, rect: Rect) -> str | None:
    """Raison pour laquelle cette pièce ne peut pas aller là, ou None si c'est possible."""
    x0, y0, x1, y1 = rect
    ox0, oy0, ox1, oy1 = x0 - 1, y0 - 1, x1 + 1, y1 + 1
    if ox0 < 1 or oy0 < 1 or ox1 > house.width - 2 or oy1 > house.height - 4:
        return "sort du terrain"
    outer = {(x, y) for x in range(ox0, ox1 + 1) for y in range(oy0, oy1 + 1)}
    if outer & house.water:
        return "tombe dans l'étang"
    for obj in house.objects.values():
        if obj.kind == "arbre" or obj.id.startswith("maison_"):
            continue  # les arbres se coupent ; les meubles de la maison sont dans leurs pièces
        x, y, w, h = obj.rect
        zone = (x - CAMP_MARGIN, y - CAMP_MARGIN, x + max(w, 1) - 1 + CAMP_MARGIN, y + max(h, 1) - 1 + CAMP_MARGIN)
        if _overlaps((ox0, oy0, ox1, oy1), zone):
            return f"empiète sur {obj.label.lower()}"
    if any(house.surface_at(p) == "concrete" for p in outer):
        return "déborde sur le trottoir"
    for other in plan.rooms:
        if _overlaps(rect, other.outer()) or _overlaps(other.rect, (ox0, oy0, ox1, oy1)):
            return f"chevauche {other.name.lower()}"
    return None


def _candidates_against(anchor: PlannedRoom, side: str, w: int, h: int) -> list[Rect]:
    """Positions collées à anchor du côté demandé (mur commun), de la plus alignée à la plus décalée."""
    ax0, ay0, ax1, ay1 = anchor.rect
    rects = []
    if side in ("est", "ouest"):
        x0 = ax1 + 2 if side == "est" else ax0 - 1 - w
        for shift in _shifts(ay1 - ay0 + 1, h):
            rects.append((x0, ay0 + shift, x0 + w - 1, ay0 + shift + h - 1))
    else:
        y0 = ay1 + 2 if side == "sud" else ay0 - 1 - h
        for shift in _shifts(ax1 - ax0 + 1, w):
            rects.append((ax0 + shift, y0, ax0 + shift + w - 1, y0 + h - 1))
    return rects


def _shifts(anchor_len: int, length: int) -> list[int]:
    """Décalages qui gardent au moins 2 cases de mur commun (pour la porte), alignés d'abord."""
    low, high = -(length - 2), anchor_len - 2
    values = [0] + [v for d in range(1, max(abs(low), high) + 1) for v in (d, -d)]
    return [v for v in values if low <= v <= high]


def _shared_doors(a: Rect, b: Rect) -> list[Pos]:
    """Cases du mur commun à deux pièces voisines où percer une porte, du milieu vers les bouts."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    if bx0 == ax1 + 2 or ax0 == bx1 + 2:            # côte à côte (est/ouest)
        wall_x = ax1 + 1 if bx0 == ax1 + 2 else bx1 + 1
        low, high = max(ay0, by0), min(ay1, by1)
        return sorted(((wall_x, y) for y in range(low, high + 1)), key=lambda p: abs(p[1] - (low + high) / 2))
    if by0 == ay1 + 2 or ay0 == by1 + 2:            # l'une au-dessus de l'autre (nord/sud)
        wall_y = ay1 + 1 if by0 == ay1 + 2 else by1 + 1
        low, high = max(ax0, bx0), min(ax1, bx1)
        return sorted(((x, wall_y) for x in range(low, high + 1)), key=lambda p: abs(p[0] - (low + high) / 2))
    return []


def _shared_door(a: Rect, b: Rect) -> Pos | None:
    doors = _shared_doors(a, b)
    return doors[0] if doors else None


def _open_door(house: House, a: Rect, b: Rect) -> Pos | None:
    """Porte du mur commun dont les deux côtés sont libres (un meuble déjà posé ne doit pas la boucher)."""
    furniture = {t for o in house.objects.values() if o.kind != "arbre" for t in o.tiles}  # les arbres se coupent
    for x, y in _shared_doors(a, b):
        sides = [(x - 1, y), (x + 1, y)] if any(x == r[0] - 1 or x == r[2] + 1 for r in (a, b)) \
            else [(x, y - 1), (x, y + 1)]
        if all(p not in furniture for p in sides):
            return x, y
    return None


def place_rooms(house: House, specs: list[dict], site: Pos, vision: str = "",
                plan: HousePlan | None = None) -> HousePlan:
    """Place les pièces demandées une à une ; celles impossibles sont notées dans plan.rejected.

    specs : dicts {id, type, name, width, height, anchor, side, why} (déjà validés et bornés).
    site : case autour de laquelle poser la première pièce (au nord du campement).
    """
    plan = plan or HousePlan(vision=vision)
    for spec in specs:
        if len(plan.rooms) >= MAX_ROOMS:
            plan.rejected.append(f"{spec['name']} : déjà {MAX_ROOMS} pièces")
            continue
        w, h = spec["width"], spec["height"]
        rect, reason = None, "aucune place"
        anchor = plan.room(spec.get("anchor") or "") if spec.get("anchor") else None
        if anchor is None and plan.rooms:
            anchor = plan.rooms[-1]  # pièce non rattachée : on la colle à la précédente
        if anchor is None:
            sx, sy = site
            for dx, dy in _spiral(12):
                candidate = (sx - w // 2 + dx, sy - h + 1 + dy, sx - w // 2 + dx + w - 1, sy + dy)
                reason = placement_problem(house, plan, candidate) or ""
                if not reason:
                    rect = candidate
                    break
        else:
            # La pièce demandée d'abord ; si rien n'y colle (ou pas de porte libre), une autre pièce du plan
            wanted = spec.get("side") if spec.get("side") in SIDES else "est"
            anchors = [anchor, *(r for r in plan.rooms if r is not anchor)]
            for candidate_anchor in anchors:
                for side in [wanted, *(s for s in SIDES if s != wanted)]:
                    for candidate in _candidates_against(candidate_anchor, side, w, h):
                        problem = placement_problem(house, plan, candidate)
                        if problem is None and _open_door(house, candidate_anchor.rect, candidate) is None:
                            problem = "pas de place pour une porte libre"
                        if problem is None:
                            rect, anchor, spec = candidate, candidate_anchor, {**spec, "side": side}
                            break
                        reason = problem
                    if rect:
                        break
                if rect:
                    break
        if rect is None:
            plan.rejected.append(f"{spec['name']} : {reason}")
            continue
        name, n = spec["name"], 2
        while any(r.name == name for r in plan.rooms):  # les pièces sont repérées par leur nom
            name, n = f"{spec['name']} {n}", n + 1
        room_id, n = spec["id"], 2
        while plan.room(room_id) is not None:
            room_id, n = f"{spec['id']}_{n}", n + 1
        room = PlannedRoom(id=room_id, type=spec["type"], name=name, rect=rect,
                           anchor=anchor.id if anchor else None, side=spec.get("side") if anchor else None,
                           why=spec.get("why", ""))
        if anchor is not None:
            plan.doors.append(_open_door(house, anchor.rect, rect))
        plan.rooms.append(room)
    _front_door(plan)
    return plan


def _spiral(radius: int) -> list[Pos]:
    offsets = [(dx, dy) for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1)]
    return sorted(offsets, key=lambda d: (abs(d[0]) + abs(d[1]), d[1] < 0, d))


def _front_door(plan: HousePlan) -> None:
    """Porte d'entrée sur le mur sud de la pièce la plus au sud, du côté du campement."""
    plan.front_door = None
    inner = {t for r in plan.rooms for t in r.interior_tiles()}
    walls = {t for r in plan.rooms for t in r.wall_tiles()}
    for room in sorted(plan.rooms, key=lambda r: -r.rect[3]):
        x0, _y0, x1, y1 = room.rect
        for x in sorted(range(x0 + 1, x1), key=lambda x: abs(x - (x0 + x1) / 2)) or [x0]:
            if (x, y1 + 2) not in inner and (x, y1 + 2) not in walls:
                plan.front_door = (x, y1 + 1)
                return


# ---------------------------------------------------------------- construction


def trees_in(house: House, room: PlannedRoom) -> list[InteractiveObject]:
    """Arbres à abattre avant de bâtir la pièce (sur ses murs ou à l'intérieur)."""
    outer = set(room.outer_tiles())
    return [house.objects[f"arbre_{x}_{y}"] for x, y in outer if f"arbre_{x}_{y}" in house.objects]


def build_room(house: House, plan: HousePlan, room: PlannedRoom) -> list[InteractiveObject]:
    """Monte les murs, le plancher, les portes et les fenêtres de la pièce, puis la meuble."""
    for tree in trees_in(house, room):
        house.remove_object(tree.id)
    doors = plan.all_doors()
    house.add_room(room.name, room.rect, [t for t in room.wall_tiles() if t not in doors],
                   [t for t in room.wall_tiles() if t in doors], ROOM_TYPES[room.type].floor)
    room.status = "bati"
    furniture = furnish(house, room, doors)
    for obj in furniture:
        house.add_object(obj)
    house.windows = compute_windows(house, plan)
    return furniture


def furnish(house: House, room: PlannedRoom, doors: set[Pos]) -> list[InteractiveObject]:
    """Meubles le long des murs ; un meuble dont la place d'usage serait inaccessible est laissé de côté."""
    x0, y0, x1, y1 = room.rect
    door_inside = {_inside_of(d, room) for d in doors} - {None}
    blocked: set[Pos] = set()
    placed: list[InteractiveObject] = []
    rtype = ROOM_TYPES[room.type]
    for item in rtype.furniture:
        w, h = item.size
        for x, y in _slots(room, item):
            tiles = {(x + dx, y + dy) for dx in range(w) for dy in range(h)}
            if any(not (x0 <= tx <= x1 and y0 <= ty <= y1) for tx, ty in tiles):
                continue
            if tiles & blocked or tiles & door_inside:
                continue
            if item.kind == "deco":
                spots = []  # décoratif : on ne s'en sert pas, il ne doit juste rien bloquer
            else:
                spots = _use_spots(tiles, room, blocked | tiles, door_inside, item.capacity, item.slot)
                if not spots:
                    continue
            trial = blocked | tiles
            entry = next(iter(door_inside), None)
            if entry is not None and not all(_reachable(entry, s, room, trial) for s in spots):
                continue
            if entry is not None and not _room_open(entry, room, trial):
                continue
            if entry is not None and not all(_reachable(entry, s, room, trial)
                                             for o in placed for s in o.use_positions):
                continue
            blocked = trial
            placed.append(InteractiveObject(f"maison_{room.id}_{item.key}", item.kind,
                                            f"{item.label} ({room.name.lower()})", room.name,
                                            (x, y, w, h), spots))
            break
    return placed


def _slots(room: PlannedRoom, item: Furniture) -> list[Pos]:
    """Coins hauts possibles du meuble, selon sa place préférée."""
    x0, y0, x1, y1 = room.rect
    w, h = item.size
    mid_x = (x0 + x1 + 1 - w) // 2
    if item.slot == "center":
        mid_y = (y0 + y1 + 1 - h) // 2
        return sorted({(x, y) for x in range(x0 + 1, x1) for y in range(y0 + 1, y1)},
                      key=lambda p: abs(p[0] - mid_x) + abs(p[1] - mid_y))
    if item.slot == "facing":  # deux rangées sous le mur nord, face à la télé
        row = sorted(((x, y0 + 2) for x in range(x0, x1 + 1)), key=lambda p: abs(p[0] - mid_x))
        return row + [(x, y0 + 3) for x in range(x0, x1 + 1)]
    centered = item.key == "tele"  # la télé au milieu du mur, le reste en partant du coin
    north = sorted(((x, y0) for x in range(x0, x1 + 1)), key=lambda p: abs(p[0] - mid_x) if centered else 0)
    sides = [(x0, y) for y in range(y0 + 1, y1 + 1)] + [(x1, y) for y in range(y0 + 1, y1 + 1)]
    return north + sides


def _room_open(entry: Pos, room: PlannedRoom, blocked: set[Pos]) -> bool:
    """Toutes les cases libres de la pièce restent atteignables depuis la porte (pas de recoin muré)."""
    free = [p for p in room.interior_tiles() if p not in blocked]
    return all(_reachable(entry, p, room, blocked) for p in free)


def _use_spots(tiles: set[Pos], room: PlannedRoom, blocked: set[Pos], avoid: set[Pos],
               capacity: int, slot: str = "wall") -> list[Pos]:
    x0, y0, x1, y1 = room.rect
    around = sorted({(tx + dx, ty + dy) for tx, ty in tiles for dx, dy in ((0, 1), (-1, 0), (1, 0), (0, -1))},
                    key=lambda p: (p[1], p[0]))
    spots = [p for p in around if x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and p not in blocked]
    top, bottom = min(t[1] for t in tiles), max(t[1] for t in tiles)
    preferred = [p for p in spots if (p[1] < top if slot == "facing" else p[1] > bottom)]
    ordered = preferred + [p for p in spots if p not in preferred]
    return ordered[:capacity]


def _inside_of(door: Pos, room: PlannedRoom) -> Pos | None:
    x0, y0, x1, y1 = room.rect
    dx, dy = door
    for nx, ny in ((dx, dy + 1), (dx, dy - 1), (dx + 1, dy), (dx - 1, dy)):
        if x0 <= nx <= x1 and y0 <= ny <= y1:
            return nx, ny
    return None


def _reachable(start: Pos, goal: Pos, room: PlannedRoom, blocked: set[Pos]) -> bool:
    x0, y0, x1, y1 = room.rect
    return find_path(start, goal, lambda p: x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and p not in blocked) is not None


def place_in_room(house: House, name: str, rect: Rect, size: tuple[int, int], capacity: int,
                  deco: bool) -> tuple[tuple[int, int, int, int], list[Pos]] | None:
    """Place un objet acheté dans une pièce déjà meublée : (rect x, y, l, h ; cases d'usage) ou None.

    Les meubles existants, les portes et l'accès à chaque case libre et à chaque meuble sont respectés.
    """
    room = PlannedRoom(id="achat", type="salon", name=name, rect=rect)
    blocked = {t for t in room.interior_tiles() if t in house.blocked}
    door_inside = {_inside_of(d, room) for d in house.doors} - {None}
    others = [o for o in house.objects.values() if o.room == name]
    entry = next(iter(door_inside), None) or next((t for t in room.interior_tiles() if t not in blocked), None)
    if entry is None:
        return None
    item = Furniture("achat", "deco" if deco else "achat", "", size, capacity)
    w, h = size
    for x, y in _slots(room, item) + room.interior_tiles():
        tiles = {(x + dx, y + dy) for dx in range(w) for dy in range(h)}
        if any(not (rect[0] <= tx <= rect[2] and rect[1] <= ty <= rect[3]) for tx, ty in tiles):
            continue
        if tiles & blocked or tiles & door_inside or entry in tiles:
            continue
        trial = blocked | tiles
        spots = [] if deco else _use_spots(tiles, room, trial, door_inside, capacity)
        if not deco and not spots:
            continue
        uses = [s for o in others for s in o.use_positions] + spots
        if not all(_reachable(entry, s, room, trial) for s in uses) or not _room_open(entry, room, trial):
            continue
        return (x, y, w, h), spots
    return None


def place_outside(house: House, size: tuple[int, int], capacity: int, deco: bool, center: Pos,
                  radius: int = 16, allow_surface: bool = False) -> tuple[tuple[int, int, int, int], list[Pos]] | None:
    """Place un objet dehors, près de center, sur des cases libres, sans boucher un passage."""
    w, h = size
    reserved = {p for o in house.objects.values() for p in o.use_positions} | set(house.doors)
    cx, cy = center
    for x, y in sorted(((cx + dx, cy + dy) for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1)),
                       key=lambda p: abs(p[0] - cx) + abs(p[1] - cy)):
        tiles = [(x + dx, y + dy) for dx in range(w) for dy in range(h)]
        ring = {(tx + ex, ty + ey) for tx, ty in tiles for ex in (-1, 0, 1) for ey in (-1, 0, 1)} - set(tiles)
        def bad_surface(t: Pos) -> bool:  # un véhicule se gare sur l'asphalte, jamais sur le trottoir
            surface = house.surface_at(t)
            return bool(surface) and (not allow_surface or surface == "concrete")
        if any(not house.is_walkable(t) or t in reserved or bad_surface(t) for t in tiles):
            continue
        if any(house.is_wall(p) or p in house.doors for p in ring):
            continue  # pas collé à un mur de la maison ni devant une porte
        spots = [] if deco else [p for p in sorted(ring, key=lambda p: (p[1], p[0]))
                                 if house.is_walkable(p) and p not in reserved][:capacity]
        if not deco and not spots:
            continue
        if find_path(center, spots[0] if spots else next(iter(ring)),
                     lambda p: house.is_walkable(p) and p not in tiles, max_nodes=4000) is None:
            continue
        return (x, y, w, h), spots
    return None


def compute_windows(house: House, plan: HousePlan) -> list[tuple[int, int, bool]]:
    """Fenêtres sur les murs extérieurs des pièces bâties (ni coin, ni porte, ni mur commun)."""
    built = plan.built()
    inner = {t for r in built for t in r.interior_tiles()}
    doors = plan.all_doors()
    windows = []
    for room in built:
        x0, y0, x1, y1 = room.rect
        for i, x in enumerate(range(x0, x1 + 1)):
            for y, outside in ((y0 - 1, y0 - 2), (y1 + 1, y1 + 2)):
                if i % WINDOW_EVERY == 1 and (x, y) not in doors and (x, outside) not in inner:
                    windows.append((x, y, False))
        for i, y in enumerate(range(y0, y1 + 1)):
            for x, outside in ((x0 - 1, x0 - 2), (x1 + 1, x1 + 2)):
                if i % WINDOW_EVERY == 1 and (x, y) not in doors and (outside, y) not in inner:
                    windows.append((x, y, True))
    return sorted(set(windows))
