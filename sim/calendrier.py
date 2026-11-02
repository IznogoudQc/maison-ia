"""Calendrier québécois : vraie date du jour de jeu, fériés, école, vacances de la construction.

Le jour 0 de la partie est un lundi (voir sim/clock.py) : la date de départ est ramenée au lundi qui la
précède. Les fériés sont payés et chômés ; l'école ferme l'été, aux Fêtes, à la relâche, le lundi de
Pâques et lors des journées pédagogiques ; les travailleurs prennent les vacances de la construction.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.agent import Agent

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
SCHOOL_LABELS = ("école",)


def easter(year: int) -> date:
    """Dimanche de Pâques (calcul grégorien anonyme)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    weekday = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday) // 451
    month = (h + weekday - 7 * m + 114) // 31
    day = (h + weekday - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_monday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))


def holidays(year: int) -> dict[date, str]:
    """Jours fériés chômés au Québec (la Fête nationale et la fête du Canada reportées au lundi si dimanche)."""
    may_25 = date(year, 5, 25)
    days = {
        date(year, 1, 1): "Jour de l'An",
        easter(year) - timedelta(days=2): "Vendredi saint",
        may_25 - timedelta(days=may_25.weekday() or 7): "Journée nationale des patriotes",
        date(year, 6, 24): "Fête nationale",
        date(year, 7, 1): "fête du Canada",
        _nth_monday(year, 9, 1): "fête du Travail",
        _nth_monday(year, 10, 2): "Action de grâce",
        date(year, 12, 25): "Noël",
    }
    for day, name in list(days.items()):
        if name in ("Fête nationale", "fête du Canada") and day.weekday() == 6:
            days[day + timedelta(days=1)] = f"{name} (reportée)"
    return days


def construction_holiday(year: int) -> tuple[date, date]:
    """Vacances de la construction : les deux dernières semaines complètes de juillet (lundi -> vendredi)."""
    last = date(year, 7, 31)
    last_friday = last - timedelta(days=(last.weekday() - 4) % 7)
    return last_friday - timedelta(days=11), last_friday


def school_break(day: date) -> str | None:
    """Raison pour laquelle l'école est fermée ce jour-là (en plus des fins de semaine et des fériés)."""
    year = day.year
    if date(year, 6, 23) <= day <= date(year, 8, 26):
        return "vacances d'été"
    if day >= date(year, 12, 22) or day <= date(year, 1, 5):
        return "congé des Fêtes"
    relache = _nth_monday(year, 3, 1)
    if relache <= day <= relache + timedelta(days=4):
        return "semaine de relâche"
    if day == easter(year) + timedelta(days=1):
        return "lundi de Pâques"
    if day.weekday() == 4 and day.day <= 7:  # le premier vendredi de chaque mois d'école
        return "journée pédagogique"
    return None


class Calendar:
    def __init__(self, start: date, vacation_weeks: int = 2) -> None:
        self.start = start - timedelta(days=start.weekday())  # le jour 0 est un lundi
        self.vacation_weeks = vacation_weeks
        self._holidays: dict[int, dict[date, str]] = {}

    def date(self, day: int) -> date:
        return self.start + timedelta(days=day)

    def holiday(self, day: int) -> str | None:
        when = self.date(day)
        if when.year not in self._holidays:
            self._holidays[when.year] = holidays(when.year)
        return self._holidays[when.year].get(when)

    def vacation(self, day: int) -> bool:
        """Vacances de la construction pour tous les travailleurs (vacation_weeks = 0 : pas de vacances)."""
        if self.vacation_weeks <= 0:
            return False
        when = self.date(day)
        start, end = construction_holiday(when.year)
        return start <= when <= min(end, start + timedelta(days=7 * self.vacation_weeks - 3))

    def off_reason(self, label: str, day: int) -> str | None:
        """Pourquoi on ne va pas au travail, à l'école ou à la garderie ce jour-là (None : on y va)."""
        name = self.holiday(day)
        if name:
            return name
        if label in SCHOOL_LABELS:
            return school_break(self.date(day))
        if label == "travail" and self.vacation(day):
            return "vacances de la construction"
        return None

    def agent_off(self, agent: Agent, day: int) -> str | None:
        """Congé du jour pour cette personne : malade, férié, vacances, école fermée (None : on y va)."""
        if agent.sick_until is not None and day * 24 * 60 < agent.sick_until:
            return "malade"
        away = agent.persona.schedule.away
        return self.off_reason(away.label, day) if away is not None else None

    def label(self, day: int) -> str:
        """« mercredi 24 juin 2026 »."""
        when = self.date(day)
        return f"{WEEKDAYS[when.weekday()]} {when.day} {MONTHS[when.month - 1]} {when.year}"

    def short_label(self, day: int) -> str:
        """« 24 juin 2026 · Fête nationale » pour le panneau."""
        when = self.date(day)
        text = f"{when.day} {MONTHS[when.month - 1]} {when.year}"
        name = self.holiday(day)
        return f"{text} · {name}" if name else text

    def upcoming(self, day: int, horizon: int = 7) -> list[tuple[int, str]]:
        """Fériés des prochains jours : (jour de jeu, nom)."""
        return [(d, name) for d in range(day + 1, day + horizon + 1) if (name := self.holiday(d))]
