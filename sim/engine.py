"""Orchestration des ticks : besoins, horaire, choix et déroulement des actions."""

from __future__ import annotations

import json
import random
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path

from agents.actions import (
    ACTIONS,
    AWAY_ACTIONS,
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
from llm.prompts import (
    ActionDecision,
    Dialogue,
    MemorySummary,
    build_decision_request,
    build_dialogue_request,
    build_summary_request,
    validate_decision,
    validate_dialogue,
)
from llm.service import LLMService, StructuredResult
from sim.clock import SimClock, parse_hhmm
from sim.config import AppConfig
from sim.economy import Economy, Household
from sim.events import Event, EventBus
from world.house import House, InteractiveObject
from world.pathfinding import NEIGHBORS, manhattan

Pos = tuple[int, int]


@dataclass
class PendingDecision:
    future: Future[StructuredResult[ActionDecision]]
    options: list[Option]
    fallback: ActionDecision
    requested_minute: int


@dataclass
class PendingDialogue:
    future: Future[StructuredResult[Dialogue]]
    participant_ids: list[str]
    room: str
    minute: int


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


# Actions d'horaire qui laissent un souvenir
MEMORABLE_ACTIONS = {
    "souper": "Souper en famille.",
    "dejeuner": "Déjeuner avant la journée.",
    "cuisiner": "J'ai préparé le souper.",
    "dormir": "Au lit pour la nuit.",
}

SAVE_VERSION = 2
SUPPORTED_SAVE_VERSIONS = {1, 2}  # v1 : avant l'économie (le ménage repart des valeurs de départ)


class Engine:
    def __init__(self, config: AppConfig, house: House, agents: list[Agent], clock: SimClock,
                 rng: random.Random, bus: EventBus | None = None, llm: LLMService | None = None) -> None:
        self.config = config
        self.house = house
        self.agents = agents
        self.clock = clock
        self.rng = rng
        self.bus = bus or EventBus()
        self.llm = llm
        self.scheduler = Scheduler()
        self.pending_decisions: dict[str, PendingDecision] = {}
        self.pending_dialogues: list[PendingDialogue] = []
        self.pair_last_talk: dict[str, int] = {}  # paire -> minute absolue de la dernière conversation
        # agent -> (future du résumé, nombre d'événements couverts)
        self.pending_summaries: dict[str, tuple[Future[StructuredResult[MemorySummary]], int]] = {}
        self.economy = Economy(config.economy)
        self.game_over = False

    # ------------------------------------------------------------------ utilitaires

    def alive_count(self) -> int:
        return sum(not a.dead for a in self.agents)

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
        elif name in AWAY_ACTIONS:
            # La porte est un passage : plusieurs agents peuvent s'y diriger en même temps
            use_pos = self.house.objects_of_kind("porte")[0].use_positions[0]
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
        if action.name in MEMORABLE_ACTIONS:
            self.remember(agent, MEMORABLE_ACTIONS[action.name])
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
            if self.economy.enabled and not self._has_food_for(definition.name):
                continue
            score = score_action(definition, agent.needs, favorites)
            if definition.name == "flaner":
                score = max(score, 0.5)
            options.append(Option(action=definition.name, label=definition.label, score=score))
        options += self._economic_options(agent)
        options.sort(key=lambda o: (o.urgent, o.score), reverse=True)
        return options

    def _has_food_for(self, action: str) -> bool:
        return self.economy.household.pantry + 1e-9 >= self.economy.portions_for(action)

    def _economic_options(self, agent: Agent) -> list[Option]:
        """Épicerie quand le garde-manger baisse, heures sup quand l'argent manque (adultes seulement)."""
        eco = self.economy
        if not eco.enabled or not agent.persona.is_adult:
            return []
        cfg = eco.config
        open_from, open_to = (parse_hhmm(h) for h in cfg.shop_hours)
        minute = self.clock.minute_of_day
        if not open_from <= minute < open_to:
            return []
        options = []
        days = eco.pantry_days(self.alive_count())
        shopper_out = any(a.away_kind == "epicerie" or (a.action and a.action.name == "epicerie")
                          for a in self.agents if a is not agent)
        if days < cfg.low_pantry_days and eco.household.money >= eco.portion_price() and not shopper_out:
            label = (f"va faire l'épicerie (garde-manger : {eco.household.pantry:.0f} portions, "
                     f"{eco.household.money:.0f} $ en banque)")
            options.append(Option(action="epicerie", label=label, score=round(20 + (cfg.low_pantry_days - days) * 20, 2),
                                  urgent=days < 0.5))
        weekday = self.clock.weekday < 5
        if eco.household.money < cfg.overtime_below and agent.persona.salary_per_day > 0 and weekday \
                and minute + cfg.overtime_minutes <= open_to:
            pay = self._overtime_pay(agent)
            label = f"part faire des heures supplémentaires (+{pay:.0f} $, {cfg.overtime_minutes // 60} h)"
            gap = (cfg.overtime_below - eco.household.money) / cfg.overtime_below
            options.append(Option(action="heures_sup", label=label, score=round(10 + gap * 30, 2)))
        return options

    def _overtime_pay(self, agent: Agent) -> float:
        cfg = self.economy.config
        return round(agent.persona.salary_per_day / 8 * cfg.overtime_rate * cfg.overtime_minutes / 60, 2)

    def pick_deterministic(self, agent: Agent, options: list[Option]) -> Option:
        """Option urgente ou besoin urgent : meilleure option ; sinon tirage pondéré parmi les 3 meilleures."""
        if options[0].urgent or agent.needs.lowest()[1] < URGENT_THRESHOLD:
            return options[0]
        top = options[:3]
        weights = [max(o.score, 0.01) for o in top]
        return self.rng.choices(top, weights=weights, k=1)[0]

    def _choose(self, agent: Agent) -> None:
        options = self.options_for(agent)
        if not options:
            return
        pick = self.pick_deterministic(agent, options)
        if self._should_ask_llm(agent, options) and self._request_decision(agent, options, pick):
            return
        self._start_option(agent, pick.action, pick.target, "", options)

    def _start_option(self, agent: Agent, name: str, target: str | None, reason: str,
                      options: list[Option]) -> None:
        """Démarre l'option voulue, ou à défaut la première autre option réalisable."""
        candidates = [(name, target, reason)] + [(o.action, o.target, "") for o in options]
        for cand_name, cand_target, cand_reason in candidates:
            action = self.make_action(agent, cand_name, cand_target, reason=cand_reason)
            if action and self.start_action(agent, action):
                return

    # ------------------------------------------------------------------ décisions LLM

    def memories_for(self, agent: Agent) -> tuple[list[str], str | None]:
        """Souvenirs récents + dernier résumé, pour les prompts."""
        return agent.memory.recent(self.config.memory.recall_count), agent.memory.latest_summary

    # ------------------------------------------------------------------ mémoire

    def remember(self, agent: Agent, text: str) -> None:
        cfg = self.config.memory
        agent.memory.add(self.clock.total_minutes, self.clock.hhmm, text, cfg.short_term_size)
        if agent.memory.since_summary >= cfg.summary_every and agent.id not in self.pending_summaries:
            self._request_summary(agent)

    def _request_summary(self, agent: Agent) -> None:
        if self.llm is None:
            return
        events = agent.memory.pending_for_summary()
        request = build_summary_request(agent, events, agent.memory.latest_summary, self.config.llm.max_tokens)
        # Repli sans LLM : les derniers événements mis bout à bout
        fallback = MemorySummary(summary=" ; ".join(e.split("] ", 1)[-1] for e in events[-3:])[:300])
        future = self.llm.try_submit(request, MemorySummary, fallback)
        if future is not None:
            self.pending_summaries[agent.id] = (future, len(events))

    def _poll_summaries(self) -> None:
        for agent_id, (future, covered) in list(self.pending_summaries.items()):
            if not future.done():
                continue
            del self.pending_summaries[agent_id]
            agent = self.agent_by_id(agent_id)
            try:
                result = future.result()
            except Exception as exc:
                result = StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
            if agent is None or result.value is None:
                continue
            agent.memory.add_summary(result.value.summary.strip(), covered, self.config.memory.max_summaries)
            self.publish("resume", agent=agent.id, name=agent.name, summary=result.value.summary,
                         ok=result.ok, error=result.error)

    def _should_ask_llm(self, agent: Agent, options: list[Option]) -> bool:
        cfg = self.config.llm
        return (self.llm is not None and cfg.decisions_enabled and len(options) >= 2
                and not options[0].urgent
                and agent.needs.lowest()[1] >= URGENT_THRESHOLD
                and self.clock.total_minutes - agent.last_decision_minute >= cfg.decision_cooldown_minutes)

    def _request_decision(self, agent: Agent, options: list[Option], pick: Option) -> bool:
        assert self.llm is not None
        top = options[:6]
        memories, summary = self.memories_for(agent)
        request = build_decision_request(agent, self.room_of(agent), self.clock.label(), top,
                                         memories, summary, self.config.llm.max_tokens)
        names = {a.id: a.name for a in self.agents}
        fallback = ActionDecision(action=pick.action, target=pick.target, reason="")
        future = self.llm.try_submit(request, ActionDecision, fallback,
                                     lambda decision: validate_decision(decision, top, names))
        if future is None:  # limite d'appels par minute atteinte
            return False
        self.pending_decisions[agent.id] = PendingDecision(future, options, fallback, self.clock.total_minutes)
        agent.thinking = True
        agent.last_decision_minute = self.clock.total_minutes
        return True

    def _cancel_decision(self, agent: Agent) -> None:
        self.pending_decisions.pop(agent.id, None)
        agent.thinking = False

    def poll(self) -> None:
        """Appelé à chaque image (fil principal) : applique les réponses LLM arrivées."""
        self._poll_dialogues()
        self._poll_summaries()
        for agent_id, pending in list(self.pending_decisions.items()):
            if not pending.future.done():
                continue
            del self.pending_decisions[agent_id]
            agent = self.agent_by_id(agent_id)
            if agent is None:
                continue
            agent.thinking = False
            try:
                result = pending.future.result()
            except Exception as exc:  # erreur inattendue dans le thread : on se rabat sur le repli
                result = StructuredResult(value=pending.fallback, ok=False, attempts=0, error=str(exc))
            decision = result.value or pending.fallback
            self.publish("decision", agent=agent.id, name=agent.name, action=decision.action,
                         target=decision.target, reason=decision.reason, ok=result.ok,
                         attempts=result.attempts, error=result.error)
            if agent.action is None and not agent.is_away:
                self._start_option(agent, decision.action, decision.target, decision.reason, pending.options)
                if result.ok and decision.reason and agent.action is not None:
                    self.remember(agent, f"J'ai décidé : {agent.action.label} (« {decision.reason} »)")

    def _check_decision_timeout(self, agent: Agent) -> None:
        pending = self.pending_decisions.get(agent.id)
        if pending is None:
            agent.thinking = False
            return
        if self.clock.total_minutes - pending.requested_minute > self.config.llm.decision_max_wait_minutes:
            self._cancel_decision(agent)
            self.publish("decision", agent=agent.id, name=agent.name, action=pending.fallback.action,
                         target=pending.fallback.target, reason="", ok=False, attempts=0,
                         error="attente trop longue")
            self._start_option(agent, pending.fallback.action, pending.fallback.target, "", pending.options)

    # ------------------------------------------------------------------ boucle

    def tick(self) -> None:
        if self.game_over:
            return
        self.clock.advance()
        if self.economy.bills_due(self.clock):
            self._charge_bills()
        for agent in self.agents:
            self._update_agent(agent)
        self._detect_encounters()

    def _charge_bills(self) -> None:
        total = self.economy.charge_bills(self.clock)
        money = self.economy.household.money
        self.publish("factures", amount=-total, money=money,
                     detail=dict(self.economy.config.weekly_bills))
        for agent in self.agents:
            if agent.persona.is_adult:
                warning = " On est dans le rouge." if money < 0 else ""
                self.remember(agent, f"Les factures sont passées : {total:.0f} $ (solde {money:.0f} $).{warning}")

    # ------------------------------------------------------------------ rencontres et dialogues

    def _talking_ids(self) -> set[str]:
        return {agent_id for p in self.pending_dialogues for agent_id in p.participant_ids}

    def _pair_ready(self, a: str, b: str) -> bool:
        last = self.pair_last_talk.get(pair_key(a, b))
        return last is None or self.clock.total_minutes - last >= self.config.dialogue.pair_cooldown_minutes

    def _detect_encounters(self) -> None:
        """Deux agents ou plus dans la même pièce, cooldown écoulé : on demande un dialogue."""
        if self.llm is None:
            return
        busy = self._talking_ids()
        by_room: dict[str, list[Agent]] = {}
        for agent in self.agents:
            room = self.house.room_at(agent.pos)
            if room is not None and agent.is_available and agent.id not in busy:
                by_room.setdefault(room, []).append(agent)

        for room, present in by_room.items():
            if len(present) < 2:
                continue
            candidates = present[:]
            self.rng.shuffle(candidates)
            for first in candidates:
                group = [first]
                for other in candidates:
                    if other is first or len(group) >= self.config.dialogue.max_participants:
                        continue
                    if all(self._pair_ready(other.id, member.id) for member in group):
                        group.append(other)
                if len(group) >= 2:
                    self._request_dialogue(group, room)
                    break

    def _request_dialogue(self, group: list[Agent], room: str) -> bool:
        assert self.llm is not None
        memories, summaries = {}, {}
        for agent in group:
            memories[agent.id], summaries[agent.id] = self.memories_for(agent)
        request = build_dialogue_request(group, room, self.clock.label(), memories, summaries,
                                         self.config.llm.max_tokens)
        names = {a.id: a.name for a in group}
        future = self.llm.try_submit(request, Dialogue, None, lambda d: validate_dialogue(d, names))
        if future is None:
            return False
        now = self.clock.total_minutes
        # Le cooldown démarre à la demande : évite de relancer la même paire pendant l'attente
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                self.pair_last_talk[pair_key(a.id, b.id)] = now
        self.pending_dialogues.append(PendingDialogue(future, [a.id for a in group], room, now))
        return True

    def _poll_dialogues(self) -> None:
        for pending in [p for p in self.pending_dialogues if p.future.done()]:
            self.pending_dialogues.remove(pending)
            names = [a.name for a in (self.agent_by_id(i) for i in pending.participant_ids) if a]
            try:
                result = pending.future.result()
            except Exception as exc:
                result = StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
            if not result.ok or result.value is None:
                self.publish("dialogue_echec", room=pending.room, participants=names, error=result.error)
                continue
            lines = [line.model_dump() for line in result.value.lines]
            transcript = " / ".join(f"{l['speaker']} : « {l['text']} »" for l in lines)
            for agent_id in pending.participant_ids:
                agent = self.agent_by_id(agent_id)
                if agent is not None:
                    agent.needs.apply({"social": self.config.dialogue.social_gain})
                    others = ", ".join(n for n in names if n != agent.name)
                    self.remember(agent, f"Jasé avec {others} ({pending.room}) : {transcript}"[:400])
            self.publish("dialogue", room=pending.room, participants=names, lines=lines,
                         time=self.clock.hhmm, attempts=result.attempts)

    def _update_agent(self, agent: Agent) -> None:
        if agent.dead:
            return
        minutes = self.clock.tick_minutes
        now = self.clock.total_minutes
        if agent.grieving_until is not None and now >= agent.grieving_until:
            agent.grieving_until = None
        if self._update_health(agent, minutes):
            return  # vient de mourir ou d'être hospitalisé

        if agent.is_away:
            agent.needs.decay(minutes, "away")
            if now >= (agent.away_until or 0):
                self._return_home(agent)
            return

        agent.needs.decay(minutes, "sleeping" if agent.is_sleeping else "awake")
        if self.economy.in_debt and agent.persona.is_adult and not agent.is_sleeping:
            # Les dettes gâchent le moral des parents
            agent.needs.apply({"fun": -self.economy.config.debt_fun_penalty_per_hour * minutes / 60})

        scheduled = self.scheduler.check(agent, self.clock)
        if scheduled is not None:
            action = self.make_action(agent, scheduled.action, scheduled.target, forced=True,
                                      until=scheduled.until)
            started = False
            if action is not None:
                if scheduled.target:
                    action.target_name = away_phrase(scheduled.target)
                started = self.start_action(agent, action)
            if started:
                self._cancel_decision(agent)
            else:
                # Objet occupé ou chemin bloqué : on retentera au prochain tick (dans la fenêtre)
                agent.fired.pop(scheduled.key, None)

        if agent.thinking:
            self._check_decision_timeout(agent)
        if agent.action is None and not agent.thinking:
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
            if action.name in AWAY_ACTIONS:
                self._leave(agent, action)
            elif not self._eat(agent, action.name):
                agent.action = None
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

    # ------------------------------------------------------------------ santé et mort

    def _update_health(self, agent: Agent, minutes: int) -> bool:
        """Faim ou épuisement à 0 : la santé baisse ; sinon elle remonte. True si la santé a lâché."""
        cfg = self.config.health
        if agent.away_kind == "hopital":
            return False
        damage = 0.0
        if agent.needs.hunger <= 0:
            damage += cfg.starvation_per_hour
        if agent.needs.energy <= 0:
            damage += cfg.exhaustion_per_hour
        if damage:
            agent.health = max(0.0, agent.health - damage * minutes / 60)
        elif agent.needs.hunger > 30 and agent.needs.energy > 20:
            agent.health = min(100.0, agent.health + cfg.regen_per_hour * minutes / 60)
        if agent.health > 0:
            return False
        if cfg.mortality:
            self._die(agent)
        else:
            self._hospitalize(agent)
        return True

    def _die(self, agent: Agent) -> None:
        now = self.clock.total_minutes
        cause = "de faim" if agent.needs.hunger <= 0 else "d'épuisement"
        self._cancel_decision(agent)
        agent.dead, agent.died_minute = True, now
        agent.action, agent.path = None, []
        agent.away_until = agent.away_label = agent.away_kind = None
        agent.grieving_until = None
        self.publish("deces", agent=agent.id, name=agent.name, cause=cause, day=self.clock.day + 1)
        grief_end = now + self.config.health.grief_days * 24 * 60
        for other in self.agents:
            if other.dead:
                continue
            other.grieving_until = grief_end
            other.needs.apply({"fun": -40, "social": -30})
            self.remember(other, f"{agent.name} nous a quittés ({cause}). Tout le monde a le cœur gros.")
        if self.alive_count() == 0:
            self.game_over = True
            self.publish("fin", day=self.clock.day + 1, label=self.clock.label())

    def _hospitalize(self, agent: Agent) -> None:
        """Mode sans mortalité : quelques jours à l'hôpital (gratuit, merci la RAMQ), puis retour."""
        self._cancel_decision(agent)
        agent.action, agent.path = None, []
        agent.away_until = self.clock.total_minutes + self.config.health.hospital_days * 24 * 60
        agent.away_label, agent.away_kind, agent.away_pay = "hôpital", "hopital", 0.0
        agent.health = 50.0
        agent.needs.hunger = max(agent.needs.hunger, 70.0)
        agent.needs.energy = max(agent.needs.energy, 70.0)
        self.publish("hopital", agent=agent.id, name=agent.name)
        self.remember(agent, "J'ai perdu connaissance : direction l'hôpital.")
        for other in self.agents:
            if other is not agent and not other.dead:
                self.remember(other, f"{agent.name} est à l'hôpital pour quelques jours.")

    def _eat(self, agent: Agent, action_name: str) -> bool:
        """Prend la nourriture du garde-manger au début d'un repas ; False si le frigo est vide."""
        portions = self.economy.portions_for(action_name)
        if self.economy.consume(portions):
            return True
        self.publish("frigo_vide", agent=agent.id, name=agent.name, action=action_name)
        self.remember(agent, "Le frigo est vide, rien à manger.")
        return False

    def _leave(self, agent: Agent, action: ActiveAction) -> None:
        now = self.clock.total_minutes
        cfg = self.economy.config
        if action.name == "epicerie":
            agent.away_until, agent.away_label, agent.away_kind = now + cfg.grocery_minutes, "épicerie", "epicerie"
            agent.away_pay = 0.0
        elif action.name == "heures_sup":
            agent.away_until = now + cfg.overtime_minutes
            agent.away_label, agent.away_kind = "travail (heures sup)", "heures_sup"
            agent.away_pay = self._overtime_pay(agent)
        else:
            salary = agent.persona.salary_per_day
            agent.away_until = action.until_minute
            agent.away_label = action.target or "travail"
            agent.away_kind = "travail" if salary > 0 else "ecole"
            agent.away_pay = salary
            # Le lunch vient du garde-manger ; sans lunch, on rentre affamé
            if self.economy.enabled and not self.economy.consume(self.economy.config.meal_portions):
                agent.needs.apply({"hunger": -25})
                self.remember(agent, "Parti sans lunch : le frigo était vide.")
        agent.action = None
        agent.path = []
        self.publish("depart", agent=agent.id, name=agent.name, label=agent.away_label)
        self.remember(agent, f"Je pars {away_phrase(agent.away_label)}.")

    def _return_home(self, agent: Agent) -> None:
        door = self.house.objects["porte"].use_positions[0]
        agent.pos = door
        agent.last_room = self.house.room_at(door)
        label, kind, pay = agent.away_label, agent.away_kind, agent.away_pay
        agent.away_until = None
        agent.away_label = None
        agent.away_kind = None
        agent.away_pay = 0.0
        self.publish("retour", agent=agent.id, name=agent.name, label=label)
        place = label or "travail"
        origin = f"de l'{place}" if away_phrase(place).startswith("à l'") else f"du {place}"
        self.remember(agent, f"De retour {origin}.")
        if not self.economy.enabled:
            return
        now = self.clock.total_minutes
        if pay > 0:
            what = "Heures sup" if kind == "heures_sup" else "Paie"
            self.economy.transaction(now, f"{what} de {agent.name}", pay)
            self.publish("paie", agent=agent.id, name=agent.name, amount=pay, source=kind,
                         money=self.economy.household.money)
        if kind == "epicerie":
            bought, cost = self.economy.buy_groceries(now, self.alive_count(), agent.name)
            self.publish("epicerie", agent=agent.id, name=agent.name, portions=bought, amount=-cost,
                         money=self.economy.household.money)
            if bought:
                self.remember(agent, f"Épicerie faite : {bought} portions pour {cost:.0f} $.")
            else:
                self.remember(agent, "Pas assez d'argent pour faire l'épicerie...")

    # ------------------------------------------------------------------ sauvegarde

    def save_state(self, path: str | Path) -> None:
        """Écrit l'état complet (horloge, agents, cooldowns, compteurs LLM) en JSON."""
        data: dict = {
            "version": SAVE_VERSION,
            "total_minutes": self.clock.total_minutes,
            "agents": {a.id: a.model_dump(mode="json") for a in self.agents},
            "pair_last_talk": self.pair_last_talk,
            "household": self.economy.household.model_dump(mode="json"),
        }
        if self.llm is not None:
            stats = self.llm.stats
            data["llm_stats"] = {"calls": stats.calls, "input_tokens": stats.input_tokens,
                                 "output_tokens": stats.output_tokens}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def load_state(self, path: str | Path) -> None:
        """Restaure une sauvegarde ; les agents absents du fichier gardent leur état initial."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") not in SUPPORTED_SAVE_VERSIONS:
            raise ValueError(f"Version de sauvegarde non prise en charge : {data.get('version')}")
        self.clock.total_minutes = data["total_minutes"]
        self.pair_last_talk = dict(data.get("pair_last_talk", {}))
        if "household" in data:
            self.economy.household = Household.model_validate(data["household"])
        saved = data.get("agents", {})
        for index, agent in enumerate(self.agents):
            if agent.id in saved:
                # Remplacement en place : le moteur, le rendu et les bulles partagent cette liste
                self.agents[index] = Agent.model_validate({**saved[agent.id], "persona": agent.persona})
        self.pending_decisions.clear()
        self.pending_dialogues.clear()
        self.pending_summaries.clear()
        self.game_over = self.alive_count() == 0
        if self.llm is not None and "llm_stats" in data:
            for key, value in data["llm_stats"].items():
                setattr(self.llm.stats, key, value)
