"""Besoins d'un agent (0 = critique, 100 = comblé) et leur décroissance."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NEED_NAMES = ("hunger", "energy", "hygiene", "social", "fun")
NEED_LABELS = {
    "hunger": "Satiété",
    "energy": "Énergie",
    "hygiene": "Hygiène",
    "social": "Social",
    "fun": "Loisir",
}
# Mot utilisé quand le besoin est bas (pour l'humeur et les prompts)
NEED_LOW_WORDS = {
    "hunger": "faim",
    "energy": "fatigue",
    "hygiene": "besoin d'une douche",
    "social": "envie de jaser",
    "fun": "ennui",
}

Mode = Literal["awake", "sleeping", "away"]

# Variation par heure simulée selon le mode (négatif = décroissance)
RATES_PER_HOUR: dict[Mode, dict[str, float]] = {
    "awake": {"hunger": -7.0, "energy": -4.0, "hygiene": -4.0, "social": -5.0, "fun": -6.0},
    "sleeping": {"hunger": -2.0, "energy": 12.0, "hygiene": -1.0, "social": 0.0, "fun": 0.0},
    # Au travail ou à l'école : on y dîne et on y voit du monde
    "away": {"hunger": -3.0, "energy": -3.5, "hygiene": -3.0, "social": 4.0, "fun": -3.0},
}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


class Needs(BaseModel):
    hunger: float = 80.0
    energy: float = 80.0
    hygiene: float = 80.0
    social: float = 70.0
    fun: float = 70.0

    def decay(self, minutes: float, mode: Mode = "awake") -> None:
        rates = RATES_PER_HOUR[mode]
        for name in NEED_NAMES:
            setattr(self, name, _clamp(getattr(self, name) + rates[name] * minutes / 60.0))

    def apply(self, effects: dict[str, float], fraction: float = 1.0) -> None:
        """Ajoute une fraction des effets d'une action (effets étalés sur sa durée)."""
        for name, delta in effects.items():
            setattr(self, name, _clamp(getattr(self, name) + delta * fraction))

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in NEED_NAMES}

    def lowest(self) -> tuple[str, float]:
        return min(self.as_dict().items(), key=lambda item: item[1])

    def mood(self) -> str:
        """Qualificatif de l'humeur (« humeur excellente », « humeur maussade (faim) »)."""
        average = sum(self.as_dict().values()) / len(NEED_NAMES)
        name, value = self.lowest()
        if value < 20:
            return f"massacrante ({NEED_LOW_WORDS[name]})"
        if average >= 75:
            return "excellente"
        if average >= 55:
            return "correcte"
        if value < 35:
            return f"maussade ({NEED_LOW_WORDS[name]})"
        return "moyenne"

    def describe(self) -> str:
        """Résumé lisible pour les prompts : 'Satiété 62/100, Énergie 30/100 (fatigue)...'."""
        parts = []
        for name, value in self.as_dict().items():
            text = f"{NEED_LABELS[name]} {value:.0f}/100"
            if value < 35:
                text += f" ({NEED_LOW_WORDS[name]})"
            parts.append(text)
        return ", ".join(parts)
