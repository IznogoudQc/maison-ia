"""État d'un agent : position, besoins, action courante, humeur."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from agents.actions import action_label, away_phrase
from agents.aspiration import Aspiration
from agents.memory import Memory
from agents.needs import Needs
from agents.persona import Persona
from agents.plan import DayPlan, Goal
from agents.social import Relation
from sim.career import Career
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
    vehicle: str | None = None       # véhicule prévu pour partir (id de l'objet garé)

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
    away_kind: str | None = None     # travail, ecole, epicerie, heures_sup, hopital
    away_pay: float = 0.0            # paie versée au retour
    drove: bool = False              # parti avec un véhicule de la famille
    vehicle: str | None = None       # id du véhicule utilisé (il n'est plus dans l'entrée)
    health: float = 100.0
    dead: bool = False
    died_minute: int | None = None
    grieving_until: int | None = None  # minute absolue de fin du deuil
    unemployed_until: int | None = None  # mise à pied jusqu'à cette minute absolue
    fired: dict[str, int] = Field(default_factory=dict)  # tâche d'horaire -> dernier jour exécuté
    last_decision_minute: int = -10**9   # dernière décision demandée au LLM
    memory: Memory = Field(default_factory=Memory)
    plan: DayPlan | None = None          # plan de la journée écrit par le LLM
    plan_requested_day: int = -1         # dernier jour où un plan a été demandé
    plan_stale: str | None = None        # raison de refaire le plan (événement imprévu)
    goal: Goal | None = None             # objectif tiré de la réflexion du soir
    reflected_day: int = -1              # dernier jour réfléchi (au coucher)
    relations: dict[str, Relation] = Field(default_factory=dict)  # id d'un autre agent -> ressenti
    bed: str | None = None               # lit attribué en cours de partie (sinon celui de la fiche)
    age_years: float | None = None       # âge précis (scénario terrain : on vieillit d'un an par semaine)
    parental_leave_until: int | None = None  # congé parental : pas de travail, prestations à la place
    sick_until: int | None = None        # malade jusqu'à cette minute : on reste à la maison
    sick_paid: dict[str, int] = Field(default_factory=dict)  # année -> jours de maladie déjà payés
    career: Career | None = None         # emploi, études ou école (sim/career.py)
    aspiration: Aspiration | None = None  # projet de vie (sim/projects.py)
    visitor: bool = False                # voisin ou parent en visite (sim/visitors.py), hors du ménage
    thinking: bool = Field(default=False, exclude=True)  # en attente d'une réponse LLM (« … »)

    @property
    def id(self) -> str:
        return self.persona.id

    @property
    def name(self) -> str:
        return self.persona.name

    @property
    def bed_id(self) -> str:
        return self.bed or self.persona.bed

    def relation(self, other_id: str) -> Relation:
        """Ressenti envers un autre membre (créé à la valeur de base au premier besoin)."""
        if other_id not in self.relations:
            self.relations[other_id] = Relation()
        return self.relations[other_id]

    @property
    def is_away(self) -> bool:
        return self.away_until is not None

    @property
    def is_sleeping(self) -> bool:
        return self.action is not None and self.action.name == "dormir" and self.action.started

    @property
    def is_available(self) -> bool:
        """Vivant, présent, éveillé, en âge de jaser : peut participer à une conversation."""
        return not self.dead and not self.is_away and not self.is_sleeping and self.persona.stage != "bebe"

    @property
    def mood(self) -> str:
        if self.grieving_until is not None:
            return "en deuil"
        return self.needs.mood()

    @property
    def status_label(self) -> str:
        if self.dead:
            return "† repose en paix"
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
