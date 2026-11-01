"""Horaire de base : sommeil, déjeuner, départ travail/école, tâches fixes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sim.clock import MINUTES_PER_DAY, SimClock, parse_hhmm

if TYPE_CHECKING:
    from agents.agent import Agent

# Fenêtre de déclenchement : une tâche ratée de plus de 30 min est abandonnée
TRIGGER_WINDOW = 30
BREAKFAST_DELAY = 15


@dataclass
class ScheduledAction:
    key: str
    action: str
    until: int | None = None   # minute absolue de fin (sommeil, retour d'absence)
    target: str | None = None  # libellé d'absence (« travail », « école »)


def is_sleep_time(minute: int, wake: int, sleep: int) -> bool:
    if sleep > wake:   # coucher avant minuit
        return minute >= sleep or minute < wake
    return sleep <= minute < wake  # coucher après minuit


class Scheduler:
    def check(self, agent: Agent, clock: SimClock) -> ScheduledAction | None:
        """Action imposée à démarrer maintenant, ou None. Marque la tâche comme faite."""
        schedule = agent.persona.schedule
        minute, day, weekday = clock.minute_of_day, clock.day, clock.weekday
        day_start = day * MINUTES_PER_DAY
        wake, sleep = parse_hhmm(schedule.wake), parse_hhmm(schedule.sleep)

        if is_sleep_time(minute, wake, sleep):
            if agent.action is not None and agent.action.name == "dormir":
                return None
            until = day_start + wake if minute < wake else day_start + MINUTES_PER_DAY + wake
            return ScheduledAction("dormir", "dormir", until)

        candidates: list[tuple[str, int, str, int | None, str | None]] = []
        away = schedule.away
        laid_off = agent.unemployed_until is not None and clock.total_minutes < agent.unemployed_until
        laid_off = laid_off or (agent.parental_leave_until is not None
                                and clock.total_minutes < agent.parental_leave_until)
        if away is not None and weekday in away.days and not laid_off:
            back = parse_hhmm(away.back)
            if minute < back:
                candidates.append(("away", parse_hhmm(away.leave), "partir", day_start + back, away.label))
        candidates.append(("dejeuner", wake + BREAKFAST_DELAY, "dejeuner", None, None))
        for index, task in enumerate(schedule.tasks):
            if weekday in task.days:
                candidates.append((f"task{index}:{task.action}", parse_hhmm(task.time), task.action, None, None))

        for key, start, action, until, target in candidates:
            if start <= minute < start + TRIGGER_WINDOW and agent.fired.get(key) != day:
                agent.fired[key] = day
                return ScheduledAction(key, action, until, target)
        return None
