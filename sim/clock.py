"""Horloge de simulation : 1 tick = N minutes simulées."""

from __future__ import annotations

DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MINUTES_PER_DAY = 24 * 60


def parse_hhmm(text: str) -> int:
    """'07:30' -> 450 (minutes depuis minuit)."""
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def format_hhmm(minute_of_day: int) -> str:
    minute_of_day %= MINUTES_PER_DAY
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


class SimClock:
    def __init__(self, start_day: int = 0, start_time: str = "06:00", tick_minutes: int = 1):
        self.tick_minutes = tick_minutes
        # Minutes absolues depuis le lundi 00:00 de la semaine 0
        self.total_minutes = start_day * MINUTES_PER_DAY + parse_hhmm(start_time)

    def advance(self) -> None:
        self.total_minutes += self.tick_minutes

    @property
    def day(self) -> int:
        return self.total_minutes // MINUTES_PER_DAY

    @property
    def weekday(self) -> int:
        return self.day % 7

    @property
    def minute_of_day(self) -> int:
        return self.total_minutes % MINUTES_PER_DAY

    @property
    def hhmm(self) -> str:
        return format_hhmm(self.minute_of_day)

    @property
    def day_name(self) -> str:
        return DAY_NAMES[self.weekday]

    def label(self) -> str:
        return f"Jour {self.day + 1} ({self.day_name}) {self.hhmm}"
