"""Personnalité qui évolue : qualités et défauts gagnés, renforcés ou perdus au fil des conclusions de fond."""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_TRAITS = 5     # qualités (ou défauts) au plus


class TraitChange(BaseModel):
    day: int
    change: str        # ajouter, renforcer, retirer
    kind: str          # qualite, defaut
    trait: str
    reason: str = ""

    @property
    def label(self) -> str:
        sign = {"ajouter": "+", "renforcer": "↑", "retirer": "−"}[self.change]
        noun = "qualité" if self.kind == "qualite" else "défaut"
        verb = {"ajouter": "nouveau trait", "renforcer": "plus marqué", "retirer": "s'efface"}[self.change]
        return f"{sign} {self.trait} ({noun}, {verb})"


class Personality(BaseModel):
    added: dict[str, list[str]] = Field(default_factory=lambda: {"qualite": [], "defaut": []})
    removed: list[str] = Field(default_factory=list)
    stronger: dict[str, int] = Field(default_factory=dict)   # trait -> niveau (1 à 2)
    evidence: list[str] = Field(default_factory=list)        # conclusions de fond depuis le dernier changement
    history: list[TraitChange] = Field(default_factory=list)
    last_change_day: int = -100

    def effective(self, base: list[str], kind: str) -> list[str]:
        """Les traits de la fiche, moins ceux qui se sont effacés, plus ceux acquis en cours de partie."""
        kept = [t for t in base if t not in self.removed]
        return kept + [t for t in self.added.get(kind, []) if t not in kept and t not in self.removed]

    def describe(self, trait: str) -> str:
        """« patiente (de plus en plus) » pour les prompts."""
        return f"{trait} (de plus en plus)" if self.stronger.get(trait) else trait
