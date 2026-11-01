"""Fiche personnage chargée depuis data/family.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]


class AwaySchedule(BaseModel):
    """Absence régulière (travail, école)."""

    leave: str
    back: str
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    label: str = "travail"


class FixedTask(BaseModel):
    """Action imposée à heure fixe (souper, cuisiner...)."""

    time: str
    action: str
    days: list[int] = Field(default_factory=lambda: list(ALL_DAYS))


class Schedule(BaseModel):
    wake: str
    sleep: str
    away: AwaySchedule | None = None
    tasks: list[FixedTask] = Field(default_factory=list)


class Persona(BaseModel):
    id: str
    name: str
    age: int
    role: str
    color: tuple[int, int, int]
    traits: list[str]
    interests: list[str] = Field(default_factory=list)
    routines: list[str] = Field(default_factory=list)
    relations: dict[str, str] = Field(default_factory=dict)
    speech_style: str = ""
    bed: str
    favorite_actions: list[str] = Field(default_factory=list)
    salary_per_day: float = 0.0   # paie nette par journée de travail (0 = pas d'emploi)
    schedule: Schedule

    @property
    def is_adult(self) -> bool:
        return self.age >= 18

    def short_description(self) -> str:
        return f"{self.name}, {self.age} ans ({self.role}) : {', '.join(self.traits)}"


def load_family(path: str | Path) -> list[Persona]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    personas = [Persona.model_validate(item) for item in data["family"]]
    ids = {p.id for p in personas}
    if len(ids) != len(personas):
        raise ValueError("Identifiants de persona en double dans le fichier famille")
    return personas
