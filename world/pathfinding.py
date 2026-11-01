"""A* 4-connexe sur la grille de la maison."""

from __future__ import annotations

import heapq
from collections.abc import Callable

Pos = tuple[int, int]

NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def find_path(
    start: Pos,
    goal: Pos,
    is_walkable: Callable[[Pos], bool],
    max_nodes: int = 20_000,
) -> list[Pos] | None:
    """Chemin de start (exclu) à goal (inclus), ou None si inatteignable.

    La case de départ n'a pas besoin d'être franchissable (agent coincé, sauvegarde ancienne).
    """
    if start == goal:
        return []
    if not is_walkable(goal):
        return None

    counter = 0  # départage les égalités de f sans comparer les positions
    open_heap: list[tuple[int, int, Pos]] = [(manhattan(start, goal), counter, start)]
    g_score: dict[Pos, int] = {start: 0}
    came_from: dict[Pos, Pos] = {}
    closed: set[Pos] = set()

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == goal:
            path = [current]
            while path[-1] in came_from:
                path.append(came_from[path[-1]])
            path.pop()  # retire start
            path.reverse()
            return path
        if current in closed:
            continue
        closed.add(current)
        if len(closed) > max_nodes:
            return None

        for dx, dy in NEIGHBORS:
            nxt = (current[0] + dx, current[1] + dy)
            if nxt in closed or not is_walkable(nxt):
                continue
            tentative = g_score[current] + 1
            if tentative < g_score.get(nxt, 1 << 30):
                g_score[nxt] = tentative
                came_from[nxt] = current
                counter += 1
                heapq.heappush(open_heap, (tentative + manhattan(nxt, goal), counter, nxt))
    return None
