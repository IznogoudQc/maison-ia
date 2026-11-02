"""Voisins et visite : parenté, voisins et amis passent faire un tour (data/voisins.yaml).

Certains jours (plus souvent la fin de semaine), quelqu'un arrive par l'arrêt d'autobus en journée, reste
une heure ou deux, puis repart. Les visiteurs ne font pas partie du ménage : ils ne sont pas dans
engine.agents (couple, carrières, lits, repas les ignorent), mais ils bougent, jasent avec la famille
(dialogues de l'IA) et gardent souvenirs et relations d'une visite à l'autre. Pas de décision par l'IA
pour eux : ils suivent leurs besoins, pour garder le coût bas.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from agents.agent import ActiveAction, Agent
from agents.persona import Persona
from sim.calendrier import SCHOOL_LABELS

if TYPE_CHECKING:
    from sim.engine import Engine

VISITORS_FILE = Path("data/voisins.yaml")
VISIT_HOURS = (10 * 60, 17 * 60)     # heure d'arrivée possible
VISIT_MINUTES = (90, 180)            # durée de la visite
VISIT_CHANCE = (0.25, 0.5)           # jour de semaine, jour de congé (fin de semaine, férié)
LEAVE_GRACE = 90                     # minutes pour rejoindre l'arrêt avant de partir quand même


def load_visitors(scenario: str, path: Path = VISITORS_FILE) -> list[Persona]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Persona.model_validate(raw) for raw in data.get(scenario) or []]


class Visitors:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        personas = load_visitors(engine.house.layout.name)
        self.known: dict[str, Agent] = {p.id: Agent(persona=p, pos=(0, 0), visitor=True) for p in personas}
        self.present: list[Agent] = []
        self.leave_at: dict[str, int] = {}
        self.leaving: set[str] = set()
        self.last_visit: dict[str, int] = {}
        self.planned: tuple[int, str, int] | None = None   # (minute d'arrivée, qui, durée) aujourd'hui
        self.planned_day = -1

    def get(self, agent_id: str) -> Agent | None:
        return next((a for a in self.present if a.id == agent_id), None)

    # ------------------------------------------------------------------ chaque minute

    def update(self) -> None:
        engine = self.engine
        if not self.known:
            return
        day, now = engine.clock.day, engine.clock.total_minutes
        if self.planned_day != day:
            self.planned_day = day
            self.planned = self.plan_day(day)
        if self.planned is not None and now >= self.planned[0] and not self.present:
            _start, who, duration = self.planned
            self.planned = None
            self.arrive(self.known[who], duration)
        talking = engine._talking_ids()
        for visitor in list(self.present):
            if visitor.id not in self.leaving:
                if now >= self.leave_at[visitor.id] and visitor.id not in talking:
                    self._head_out(visitor)
            elif visitor.pos == self.door() or now >= self.leave_at[visitor.id] + LEAVE_GRACE:
                self.depart(visitor)

    def plan_day(self, day: int) -> tuple[int, str, int] | None:
        engine = self.engine
        luck = random.Random(f"visite:{engine.house.layout.name}:{day}")
        weekend = engine.clock.weekday >= 5
        off = weekend or engine.calendar.holiday(day) is not None
        school_off = weekend or engine.calendar.off_reason(SCHOOL_LABELS[0], day) is not None
        if luck.random() >= VISIT_CHANCE[1 if off else 0]:
            return None
        # Un enfant ou un ado ne vient pas un jour d'école ; on revoit d'abord ceux qu'on n'a pas vus depuis longtemps
        candidates = [a for a in self.known.values() if a.persona.is_adult or school_off]
        if not candidates:
            return None
        candidates.sort(key=lambda a: (self.last_visit.get(a.id, -99), luck.random()))
        start = day * 24 * 60 + luck.randint(*VISIT_HOURS)
        return start, candidates[0].id, luck.randint(*VISIT_MINUTES)

    def door(self) -> tuple[int, int]:
        return self.engine.house.objects_of_kind("porte")[0].use_positions[0]

    # ------------------------------------------------------------------ arrivée et départ

    def arrive(self, visitor: Agent, duration: int = 120) -> None:
        engine = self.engine
        visitor.pos, visitor.path, visitor.action, visitor.dead = self.door(), [], None, False
        visitor.away_until = None
        for need in ("hunger", "energy", "hygiene", "fun", "bladder"):
            if hasattr(visitor.needs, need):
                setattr(visitor.needs, need, max(getattr(visitor.needs, need), 75.0))
        visitor.needs.social = min(visitor.needs.social, 40.0)   # on vient pour jaser
        self.present.append(visitor)
        self.leave_at[visitor.id] = engine.clock.total_minutes + duration
        self.last_visit[visitor.id] = engine.clock.day
        role = visitor.persona.role
        engine.publish("visite", agent=visitor.id, name=visitor.name, role=role,
                       text=f"{visitor.name} ({role}) arrive en visite")
        engine.remember(visitor, "Je suis passé faire un tour chez la famille.", 3)
        for member in engine.agents:
            if member.is_available:
                engine.remember(member, f"{visitor.name} ({role}) est venu nous voir.", 4)

    def _head_out(self, visitor: Agent) -> None:
        """La visite est finie : on se dirige vers l'arrêt d'autobus."""
        self.leaving.add(visitor.id)
        action = ActiveAction(name="flaner", use_pos=self.door(), remaining=5, reason="la visite est finie")
        if not self.engine.start_action(visitor, action):
            self.depart(visitor)

    def depart(self, visitor: Agent) -> None:
        engine = self.engine
        if visitor in self.present:
            self.present.remove(visitor)
        self.leaving.discard(visitor.id)
        self.leave_at.pop(visitor.id, None)
        visitor.action, visitor.path = None, []
        engine.publish("fin_visite", agent=visitor.id, name=visitor.name,
                       text=f"{visitor.name} repart après sa visite")
        for member in engine.agents:
            if member.is_available:
                engine.remember(member, f"{visitor.name} est reparti chez lui.", 2)

    # ------------------------------------------------------------------ prompts, sauvegarde

    def context_line(self) -> str:
        if not self.present:
            return ""
        return "En visite en ce moment : " + ", ".join(f"{v.name} ({v.persona.role})" for v in self.present) + "."

    def hud_lines(self) -> list[str]:
        return [f"En visite : {v.name} ({v.persona.role})" for v in self.present]

    def to_dict(self) -> dict:
        return {"known": {i: a.model_dump(mode="json") for i, a in self.known.items()},
                "last_visit": self.last_visit}

    def load_dict(self, data: dict | None) -> None:
        """Souvenirs et relations des visiteurs ; personne n'est en visite au chargement."""
        data = data or {}
        for visitor_id, saved in (data.get("known") or {}).items():
            if visitor_id in self.known:
                agent = Agent.model_validate({**saved, "persona": self.known[visitor_id].persona})
                agent.action, agent.path, agent.visitor = None, [], True
                self.known[visitor_id] = agent
        self.last_visit = {k: int(v) for k, v in (data.get("last_visit") or {}).items()}
        self.present, self.leaving, self.leave_at = [], set(), {}
