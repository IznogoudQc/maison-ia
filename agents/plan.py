"""Plan de la journée et objectif personnel d'un agent (écrits par le LLM, suivis par le moteur)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from sim.clock import format_hhmm


class PlanItem(BaseModel):
    minute: int                 # minute du jour (0-1439) où l'activité est prévue
    action: str
    target: str | None = None   # id d'agent (jaser) ou None
    note: str = ""              # pourquoi, en quelques mots
    status: str = "todo"        # todo, done, missed

    @property
    def hhmm(self) -> str:
        return format_hhmm(self.minute)


class DayPlan(BaseModel):
    day: int                    # jour de simulation couvert
    intention: str = ""         # fil conducteur de la journée
    items: list[PlanItem] = Field(default_factory=list)
    replans: int = 0

    def due(self, minute_of_day: int) -> PlanItem | None:
        """Première activité prévue dont l'heure est arrivée et pas encore faite."""
        return next((i for i in self.items if i.status == "todo" and i.minute <= minute_of_day), None)

    def expire(self, minute_of_day: int, window: int) -> list[PlanItem]:
        """Marque « manquées » les activités en retard de plus de window minutes."""
        missed = [i for i in self.items if i.status == "todo" and minute_of_day - i.minute > window]
        for item in missed:
            item.status = "missed"
        return missed

    def remaining(self) -> list[PlanItem]:
        return [i for i in self.items if i.status == "todo"]


class Goal(BaseModel):
    """Ce que l'agent s'est promis lors de sa réflexion du soir : l'option correspondante pèse plus."""
    text: str
    action: str
    target: str | None = None
    until: int                  # minute absolue d'expiration

    def matches(self, action: str, target: str | None) -> bool:
        return self.action == action and (self.target is None or self.target == target)
