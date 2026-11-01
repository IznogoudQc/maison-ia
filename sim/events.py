"""Bus d'événements simple (publication / abonnement, synchrone, fil principal)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ALL = "*"


@dataclass
class Event:
    kind: str                 # action, decision, dialogue, depart, retour, memoire...
    minute: int               # minute absolue de simulation
    data: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, kind: str, handler: Handler) -> None:
        """kind = ALL pour recevoir tous les événements."""
        self._handlers[kind].append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._handlers.get(event.kind, []) + self._handlers.get(ALL, []):
            handler(event)
