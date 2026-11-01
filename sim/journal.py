"""Journal JSONL des dialogues, décisions et événements marquants."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TextIO

from sim.clock import SimClock
from sim.events import Event, EventBus

LOGGED_KINDS = ("dialogue", "decision", "depart", "retour", "resume", "dialogue_echec",
                "paie", "factures", "epicerie", "frigo_vide")


class JsonlJournal:
    def __init__(self, log_dir: str | Path, clock: SimClock) -> None:
        self.clock = clock
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"sim_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
        self._file: TextIO | None = self.path.open("a", encoding="utf-8", buffering=1)

    def attach(self, bus: EventBus) -> None:
        for kind in LOGGED_KINDS:
            bus.subscribe(kind, self.write)

    def write(self, event: Event) -> None:
        if self._file is None:
            return
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "minute": event.minute,
            "sim": self._label(event.minute),
            "type": event.kind,
            **event.data,
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _label(self, minute: int) -> str:
        clock = SimClock(tick_minutes=self.clock.tick_minutes)
        clock.total_minutes = minute
        return clock.label()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
