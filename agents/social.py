"""Relations entre membres de la famille et promesses faites en jasant."""

from __future__ import annotations

from pydantic import BaseModel, Field

BASE_AFFECTION = 65.0
BASE_TENSION = 15.0
AFFECTION_RETURN = 0.15   # part de l'écart à la normale effacée chaque jour


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


class Relation(BaseModel):
    """Ce qu'un agent ressent envers un autre (pas forcément réciproque)."""
    affection: float = BASE_AFFECTION
    tension: float = BASE_TENSION
    note: str = ""   # dernière impression marquante, à la première personne

    def change(self, affection: float = 0.0, tension: float = 0.0, note: str = "") -> None:
        self.affection = clamp(self.affection + affection)
        self.tension = clamp(self.tension + tension)
        if note:
            self.note = note[:100]

    def drift(self, days: float, tension_decay: float) -> None:
        """Avec le temps, les chicanes s'estompent et l'affection revient vers la normale."""
        self.tension = clamp(self.tension - tension_decay * days)
        self.affection += (BASE_AFFECTION - self.affection) * min(1.0, AFFECTION_RETURN * days)

    @property
    def closeness(self) -> str:
        if self.affection >= 80:
            return "très proche"
        if self.affection >= 60:
            return "proche"
        if self.affection >= 40:
            return "distant"
        return "froid"

    @property
    def mood(self) -> str:
        if self.tension >= 70:
            return "en chicane"
        if self.tension >= 45:
            return "tendu"
        if self.tension >= 25:
            return "petites frictions"
        return "calme"

    def describe(self) -> str:
        text = f"{self.closeness}, {self.mood}"
        return f"{text} (« {self.note} »)" if self.note else text

    def chat_factor(self) -> float:
        """Envie d'aller jaser : plus d'affection l'augmente, la tension la diminue."""
        return (0.6 + self.affection / 125) * (1 - self.tension / 250)


class Promise(BaseModel):
    """Engagement pris pendant une conversation ; le moteur le fait arriver ou constate l'échec."""
    id: int
    people: list[str]                # ids des personnes qui feront l'activité ensemble
    by: str                          # id de la personne qui a fait la promesse
    action: str
    minute: int                      # minute absolue prévue
    text: str
    status: str = "pending"          # pending, kept, broken
    started: list[str] = Field(default_factory=list)  # ids déjà au rendez-vous
