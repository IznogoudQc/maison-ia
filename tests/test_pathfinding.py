"""A* sur grilles synthétiques et sur la maison réelle."""

from world.house import House
from world.pathfinding import find_path, manhattan


def open_grid(width: int, height: int, walls: set[tuple[int, int]] = frozenset()):
    def is_walkable(pos):
        x, y = pos
        return 0 <= x < width and 0 <= y < height and pos not in walls
    return is_walkable


def test_chemin_direct_longueur_optimale():
    path = find_path((0, 0), (5, 3), open_grid(10, 10))
    assert path is not None
    assert len(path) == manhattan((0, 0), (5, 3))
    assert path[-1] == (5, 3)
    assert (0, 0) not in path


def test_depart_egal_arrivee():
    assert find_path((2, 2), (2, 2), open_grid(5, 5)) == []


def test_contourne_un_mur():
    # Mur vertical en x=2 avec une seule ouverture en y=4
    walls = {(2, y) for y in range(5)} - {(2, 4)}
    path = find_path((0, 0), (4, 0), open_grid(5, 5, walls))
    assert path is not None
    assert (2, 4) in path
    assert not walls & set(path)
    assert len(path) == 12  # 4 vers le bas, 4 à droite, 4 vers le haut


def test_chaque_pas_est_adjacent():
    path = find_path((0, 0), (7, 6), open_grid(8, 8, {(3, y) for y in range(7)}))
    previous = (0, 0)
    for step in path:
        assert manhattan(previous, step) == 1
        previous = step


def test_but_bloque_ou_enferme():
    walls = {(1, 0), (0, 1), (1, 1)}  # (0, 0) est enfermé
    assert find_path((3, 3), (0, 0), open_grid(4, 4, walls)) is None
    assert find_path((0, 0), (1, 1), open_grid(4, 4, walls)) is None


def test_maison_toutes_les_positions_d_usage_sont_atteignables():
    house = House()
    start = (2, 11)  # couloir
    for obj in house.objects.values():
        for pos in obj.use_positions:
            assert house.is_walkable(pos), f"{obj.id} : {pos} non franchissable"
            path = find_path(start, pos, house.is_walkable)
            assert path is not None, f"{obj.id} : {pos} inatteignable"
            assert all(house.is_walkable(p) for p in path)
