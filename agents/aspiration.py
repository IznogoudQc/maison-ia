"""Projet de vie d'un personnage : une aspiration découpée en objectif du mois, étapes de la semaine et geste du jour."""

from __future__ import annotations

from pydantic import BaseModel, Field

WEEKS_PER_MONTH = 4


class Aspiration(BaseModel):
    text: str                          # « Apprendre à jouer du piano »
    why: str = ""
    action: str                        # action du jeu qui fait avancer le projet (data : agents/actions.py)
    started_day: int
    phase: int = 1                     # mois en cours (1, 2, ...)
    phase_day: int = 0                 # premier jour du mois en cours
    month_goal: str = ""
    weeks: list[str] = Field(default_factory=list)   # 4 étapes, une par semaine
    week_index: int = 0
    progress: float = 0.0              # projet complet (0-100)
    month_progress: float = 0.0        # objectif du mois (0-100)
    credited: dict[int, int] = Field(default_factory=dict)   # jour -> fois comptées (2 au plus par jour)
    history: list[str] = Field(default_factory=list)         # étapes marquantes, pour la fiche
    done: bool = False
    done_day: int | None = None

    @property
    def week_step(self) -> str:
        return self.weeks[self.week_index] if self.week_index < len(self.weeks) else ""

    def did_today(self, day: int) -> bool:
        return self.credited.get(day, 0) > 0
