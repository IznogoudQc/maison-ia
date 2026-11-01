"""État d'un agent : position, besoins, action courante, humeur."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import action_label, away_phrase
from agents.memory import Memory
from agents.needs import Needs
from agents.persona import Persona
from world.pathfinding import find_path

Pos = tuple[int, int]


class ActiveAction(BaseModel):
    name: str
    target: str | None = None        # id d'agent (jaser) ou libellé d'absence (partir)
    target_name: str | None = None   # nom affiché de la cible
    use_pos: Pos | None = None       # case où l'action se déroule (None = sur place)
    remaining: int = 0               # minutes restantes une fois sur place
    until_minute: int | None = None  # fin absolue (sommeil, absence)
    forced: bool = False             # imposée par l'horaire
    started: bool = False            # arrivé sur place, action en cours
    reason: str = ""

    @property
    def label(self) -> str:
        return action_label(self.name, self.target_name)


class Agent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    persona: Persona = Field(exclude=True)
    pos: Pos
    path: list[Pos] = Field(default_factory=list)
    last_room: str | None = None
    needs: Needs = Field(default_factory=Needs)
    action: ActiveAction | None = None
    away_until: int | None = None    # minute absolue de retour si absent
    away_label: str | None = None
    away_kind: str | None = None     # travail, ecole, epicerie, heures_sup
    away_pay: float = 0.0            # paie versée au retour
    fired: dict[str, int] = Field(default_factory=dict)  # tâche d'horaire -> dernier jour exécuté
    last_decision_minute: int = -10**9   # dernière décision demandée au LLM
    memory: Memory = Field(default_factory=Memory)
    thinking: bool = Field(default=False, exclude=True)  # en attente d'une réponse LLM (« … »)

    @property
    def id(self) -> str:
        return self.persona.id

    @property
    def name(self) -> str:
        return self.persona.name

    @property
    def is_away(self) -> bool:
        return self.away_until is not None

    @property
    def is_sleeping(self) -> bool:
        return self.action is not None and self.action.name == "dormir" and self.action.started

    @property
    def is_available(self) -> bool:
        """Présent, éveillé : peut participer à une conversation."""
        return not self.is_away and not self.is_sleeping

    @property
    def mood(self) -> str:
        return self.needs.mood()

    @property
    def status_label(self) -> str:
        if self.is_away:
            return away_phrase(self.away_label or "travail")
        if self.action is None:
            return "réfléchit…" if self.thinking else "hésite"
        if not self.action.started and self.action.use_pos is not None:
            return f"se dirige pour : {self.action.label}"
        return self.action.label

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
