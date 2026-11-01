"""État d'un agent : position, chemin courant."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from agents.persona import Persona
from world.pathfinding import find_path

Pos = tuple[int, int]


class Agent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    persona: Persona = Field(exclude=True)
    pos: Pos
    path: list[Pos] = Field(default_factory=list)
    last_room: str | None = None

    @property
    def id(self) -> str:
        return self.persona.id

    @property
    def name(self) -> str:
        return self.persona.name

    def set_destination(self, goal: Pos, is_walkable: Callable[[Pos], bool]) -> bool:
        path = find_path(self.pos, goal, is_walkable)
        if path is None:
            self.path = []
            return False
        self.path = path
        return True

    def walk(self, steps: int) -> None:
        for _ in range(min(steps, len(self.path))):
            self.pos = self.path.pop(0)

    @property
    def is_walking(self) -> bool:
        return bool(self.path)
