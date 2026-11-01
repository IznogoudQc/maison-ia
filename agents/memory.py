"""Mémoire d'un agent : N derniers événements + résumés périodiques."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryEvent(BaseModel):
    minute: int   # minute absolue de simulation
    time: str     # « HH:MM » pour l'affichage et les prompts
    text: str

    def formatted(self) -> str:
        return f"[{self.time}] {self.text}"


class Memory(BaseModel):
    events: list[MemoryEvent] = Field(default_factory=list)
    summaries: list[str] = Field(default_factory=list)
    since_summary: int = 0   # événements ajoutés depuis le dernier résumé

    def add(self, minute: int, time: str, text: str, max_events: int = 30) -> None:
        self.events.append(MemoryEvent(minute=minute, time=time, text=text))
        if len(self.events) > max_events:
            del self.events[: len(self.events) - max_events]
        self.since_summary += 1

    def recent(self, count: int = 5) -> list[str]:
        return [event.formatted() for event in self.events[-count:]] if count > 0 else []

    def pending_for_summary(self) -> list[str]:
        """Événements pas encore couverts par un résumé (bornés par la mémoire courte)."""
        return self.recent(min(self.since_summary, len(self.events)))

    @property
    def latest_summary(self) -> str | None:
        return self.summaries[-1] if self.summaries else None

    def add_summary(self, text: str, covered: int, max_summaries: int = 5) -> None:
        self.summaries.append(text)
        if len(self.summaries) > max_summaries:
            del self.summaries[: len(self.summaries) - max_summaries]
        self.since_summary = max(0, self.since_summary - covered)
