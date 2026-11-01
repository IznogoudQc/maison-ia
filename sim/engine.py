"""Orchestration des ticks : besoins, horaire, choix et déroulement des actions."""

from __future__ import annotations

import random

from agents.actions import (
    ACTIONS,
    URGENT_THRESHOLD,
    Option,
    action_label,
    away_phrase,
    is_allowed,
    score_action,
)
from agents.agent import ActiveAction, Agent
from agents.needs import Needs
from agents.scheduler import Scheduler
from sim.clock import SimClock
from sim.config import AppConfig
from sim.events import Event, EventBus
from world.house import House, InteractiveObject
from world.pathfinding import NEIGHBORS, manhattan

Pos = tuple[int, int]


class Engine:
    def __init__(self, config: AppConfig, house: House, agents: list[Agent], clock: SimClock,
                 rng: random.Random, bus: EventBus | None = None) -> None:
        self.config = config
        self.house = house
        self.agents = agents
        self.clock = clock
        self.rng = rng
        self.bus = bus or EventBus()
        self.scheduler = Scheduler()

    # ------------------------------------------------------------------ utilitaires

    def agent_by_id(self, agent_id: str) -> Agent | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def room_of(self, agent: Agent) -> str:
        return self.house.room_at(agent.pos) or agent.last_room or "Couloir"

    def publish(self, kind: str, **data) -> None:
        self.bus.publish(Event(kind, self.clock.total_minutes, data))

    def _occupied(self, exclude: Agent) -> set[Pos]:
        return {a.action.use_pos for a in self.agents
                if a is not exclude and not a.is_away and a.action and a.action.use_pos}

    def _free_spot(self, agent: Agent, obj: InteractiveObject) -> Pos | None:
        occupied = self._occupied(agent)
        free = [p for p in obj.use_positions if p not in occupied]
        return min(free, key=lambda p: manhattan(p, agent.pos)) if free else None

    def _object_spot(self, agent: Agent, kind: str) -> Pos | None:
        if kind == "lit":
            candidates = [self.house.objects[agent.persona.bed]]
        else:
            candidates = self.house.objects_of_kind(kind)
        spots = [s for s in (self._free_spot(agent, o) for o in candidates) if s is not None]
        return min(spots, key=lambda p: manhattan(p, agent.pos)) if spots else None

    def _spot_near(self, agent: Agent, target: Agent) -> Pos | None:
        occupied = self._occupied(agent)
        tx, ty = target.pos
        spots = [(tx + dx, ty + dy) for dx, dy in NEIGHBORS]
        spots = [p for p in spots if self.house.is_walkable(p) and p not in occupied]
        return min(spots, key=lambda p: manhattan(p, agent.pos)) if spots else None

    # ------------------------------------------------------------------ initialisation

    def initialize(self) -> None:
        """Place les agents : au lit s'ils dorment à l'heure de départ, sinon à la cuisine."""
        for agent in self.agents:
            agent.needs = Needs(**{n: self.rng.uniform(55, 85) for n in Needs.model_fields})
            agent.pos = self.house.random_tile(self.rng, "Cuisine")
            scheduled = self.scheduler.check(agent, self.clock)
            if scheduled and scheduled.action == "dormir":
                action = self.make_action(agent, "dormir", forced=True, until=scheduled.until)
                if action and action.use_pos:
                    agent.pos = action.use_pos
                    action.started = True
                    agent.action = action
            agent.last_room = self.house.room_at(agent.pos)

    # ------------------------------------------------------------------ actions

    def make_action(self, agent: Agent, name: str, target: str | None = None, forced: bool = False,
                    until: int | None = None, reason: str = "") -> ActiveAction | None:
        """Construit une action réalisable ou None (objet occupé, cible introuvable)."""
        definition = ACTIONS[name]
        target_name = target
        use_pos: Pos | None = None
        if name == "jaser":
            other = self.agent_by_id(target or "")
            if other is None or not other.is_available:
                return None
            target_name = other.name
            use_pos = self._spot_near(agent, other)
            if use_pos is None:
                return None
        elif name == "flaner":
            use_pos = self.house.random_tile(self.rng, self.room_of(agent))
        elif definition.object_kind is not None:
            use_pos = self._object_spot(agent, definition.object_kind)
            if use_pos is None:
                return None
        return ActiveAction(name=name, target=target, target_name=target_name, use_pos=use_pos,
                            remaining=definition.duration, until_minute=until, forced=forced,
                            reason=reason)

    def start_action(self, agent: Agent, action: ActiveAction) -> bool:
        agent.path = []
        if action.use_pos is not None and action.use_pos != agent.pos:
            if not agent.set_destination(action.use_pos, self.house.is_walkable):
                return False
        agent.action = action
        self.publish("action", agent=agent.id, name=agent.name, action=action.name,
                     label=action.label, forced=action.forced, reason=action.reason)
        return True

    def options_for(self, agent: Agent) -> list[Option]:
        """Actions possibles maintenant, triées par score décroissant."""
        favorites = agent.persona.favorite_actions
        room = self.room_of(agent)
        options: list[Option] = []
        for definition in ACTIONS.values():
            if not definition.selectable or not is_allowed(definition, agent.id, agent.needs):
                continue
            if definition.name == "jaser":
                base = score_action(definition, agent.needs, favorites)
                for other in self.agents:
                    if other is agent or not other.is_available:
                        continue
                    bonus = 1.3 if self.room_of(other) == room else 1.0
                    options.append(Option(action="jaser", target=other.id,
                                          label=action_label("jaser", other.name),
                                          score=round(base * bonus, 2)))
                continue
            if definition.object_kind and self._object_spot(agent, definition.object_kind) is None:
                continue
            score = score_action(definition, agent.needs, favorites)
            if definition.name == "flaner":
                score = max(score, 0.5)
            options.append(Option(action=definition.name, label=definition.label, score=score))
        options.sort(key=lambda o: o.score, reverse=True)
        return options

    def pick_deterministic(self, agent: Agent, options: list[Option]) -> Option:
        """Besoin urgent : meilleure option ; sinon tirage pondéré parmi les 3 meilleures."""
        if agent.needs.lowest()[1] < URGENT_THRESHOLD:
            return options[0]
        top = options[:3]
        weights = [max(o.score, 0.01) for o in top]
        return self.rng.choices(top, weights=weights, k=1)[0]

    def _choose(self, agent: Agent) -> None:
        options = self.options_for(agent)
        if not options:
            return
        # Option retenue d'abord, puis les autres en repli si elle n'est plus réalisable
        for option in [self.pick_deterministic(agent, options), *options]:
            action = self.make_action(agent, option.action, option.target)
            if action and self.start_action(agent, action):
                return

    # ------------------------------------------------------------------ boucle

    def tick(self) -> None:
        self.clock.advance()
        for agent in self.agents:
            self._update_agent(agent)

    def _update_agent(self, agent: Agent) -> None:
        minutes = self.clock.tick_minutes
        now = self.clock.total_minutes

        if agent.is_away:
            agent.needs.decay(minutes, "away")
            if now >= (agent.away_until or 0):
                self._return_home(agent)
            return

        agent.needs.decay(minutes, "sleeping" if agent.is_sleeping else "awake")

        scheduled = self.scheduler.check(agent, self.clock)
        if scheduled is not None:
            action = self.make_action(agent, scheduled.action, scheduled.target, forced=True,
                                      until=scheduled.until)
            if action is not None:
                if scheduled.target:
                    action.target_name = away_phrase(scheduled.target)
                self.start_action(agent, action)

        if agent.action is None:
            self._choose(agent)
        self._progress(agent, now)

    def _progress(self, agent: Agent, now: int) -> None:
        action = agent.action
        if action is None:
            return
        minutes = self.clock.tick_minutes

        if not action.started:
            agent.walk(self.config.sim.move_tiles_per_tick)
            room = self.house.room_at(agent.pos)
            if room is not None:
                agent.last_room = room
            if agent.path:
                return
            if action.use_pos is not None and agent.pos != action.use_pos:
                # Chemin interrompu (case prise entre-temps) : on recalcule ou on abandonne
                if not agent.set_destination(action.use_pos, self.house.is_walkable):
                    agent.action = None
                return
            action.started = True
            if action.name == "partir":
                self._leave(agent, action)
            return

        definition = ACTIONS[action.name]
        if definition.duration > 0:
            agent.needs.apply(definition.effects, minutes / definition.duration)
        action.remaining -= minutes
        if action.until_minute is not None:
            done = now >= action.until_minute
        else:
            done = action.remaining <= 0
        if done:
            agent.action = None

    def _leave(self, agent: Agent, action: ActiveAction) -> None:
        agent.away_until = action.until_minute
        agent.away_label = action.target or "travail"
        agent.action = None
        agent.path = []
        self.publish("depart", agent=agent.id, name=agent.name, label=agent.away_label)

    def _return_home(self, agent: Agent) -> None:
        door = self.house.objects["porte"].use_positions[0]
        agent.pos = door
        agent.last_room = self.house.room_at(door)
        label = agent.away_label
        agent.away_until = None
        agent.away_label = None
        self.publish("retour", agent=agent.id, name=agent.name, label=label)
