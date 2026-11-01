"""Vie intérieure des agents : plan de la journée au réveil, réflexion au coucher, objectif.

Le LLM écrit le plan et les réflexions ; le moteur les suit sans appel supplémentaire :
une activité prévue arrivée à échéance est choisie directement, et l'objectif du soir
alourdit le score de l'option visée le lendemain.
"""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents.actions import ACTIONS, DAYTIME_HOURS, URGENT_THRESHOLD, Option, action_label, allowed_for
from agents.memory import MemoryEvent
from agents.plan import DayPlan, Goal, PlanItem
from agents.scheduler import BREAKFAST_DELAY
from llm.mind_prompts import (
    PlanResponse,
    Reflection,
    build_plan_request,
    build_reflection_request,
    plan_items,
    validate_plan,
    validate_reflection,
)
from llm.service import StructuredResult
from sim.clock import MINUTES_PER_DAY, parse_hhmm

if TYPE_CHECKING:
    from agents.agent import ActiveAction, Agent
    from sim.engine import Engine

MIN_SLOT = 20            # plage libre minimale (minutes)
TASK_MINUTES = 45        # durée bloquée par une tâche d'horaire (souper, cuisine)
MIN_REFLECTION_EVENTS = 3
MAX_REFLECTION_EVENTS = 15


@dataclass
class PendingPlan:
    future: Future[StructuredResult[PlanResponse]]
    day: int
    replan: bool


@dataclass
class PendingReflection:
    future: Future[StructuredResult[Reflection]]
    events: list[MemoryEvent]


class Mind:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.pending_plans: dict[str, PendingPlan] = {}
        self.pending_reflections: dict[str, PendingReflection] = {}

    @property
    def config(self):
        return self.engine.config.mind

    def clear(self) -> None:
        self.pending_plans.clear()
        self.pending_reflections.clear()

    def busy(self) -> bool:
        return bool(self.pending_plans or self.pending_reflections)

    # ------------------------------------------------------------------ horaire et catalogue

    def free_slots(self, agent: Agent, day: int, start_from: int = 0) -> list[tuple[int, int]]:
        """Plages libres du jour (minutes du jour), hors déjeuner, travail/école et tâches fixes."""
        schedule = agent.persona.schedule
        wake, sleep = parse_hhmm(schedule.wake), parse_hhmm(schedule.sleep)
        end = sleep if sleep > wake else MINUTES_PER_DAY
        weekday = day % 7
        busy = [(wake + BREAKFAST_DELAY, wake + BREAKFAST_DELAY + 25)]
        away = schedule.away
        laid_off = agent.unemployed_until is not None and day * MINUTES_PER_DAY < agent.unemployed_until
        if away is not None and weekday in away.days and not laid_off:
            busy.append((parse_hhmm(away.leave) - 10, parse_hhmm(away.back)))
        for task in schedule.tasks:
            if weekday in task.days:
                start = parse_hhmm(task.time)
                busy.append((start, start + TASK_MINUTES))
        slots, cursor = [], max(wake, start_from)
        for start, stop in sorted(busy):
            if start - cursor >= MIN_SLOT:
                slots.append((cursor, start))
            cursor = max(cursor, stop)
        if end - cursor >= MIN_SLOT:
            slots.append((cursor, end))
        return slots

    def fixed_schedule(self, agent: Agent, day: int) -> list[str]:
        schedule = agent.persona.schedule
        weekday = day % 7
        fixed = [f"réveil {schedule.wake}", f"coucher {schedule.sleep}"]
        away = schedule.away
        laid_off = agent.unemployed_until is not None and day * MINUTES_PER_DAY < agent.unemployed_until
        if away is not None and weekday in away.days:
            fixed.append("mise à pied : pas de travail" if laid_off
                         else f"{away.label} de {away.leave} à {away.back}")
        for task in schedule.tasks:
            if weekday in task.days:
                fixed.append(f"{ACTIONS[task.action].label} à {task.time}")
        return fixed

    def catalog(self, agent: Agent) -> list[Option]:
        """Activités qu'on peut prévoir (indépendamment des besoins du moment)."""
        engine = self.engine
        options: list[Option] = []
        for definition in ACTIONS.values():
            if not definition.selectable:
                continue
            if not allowed_for(definition, agent.persona.keys):
                continue
            if definition.name == "jaser":
                options += [Option(action="jaser", target=o.id, label=action_label("jaser", o.name), score=0)
                            for o in engine.agents if o is not agent and not o.dead]
                continue
            kind = definition.object_kind
            if kind and kind != "lit" and not engine.house.objects_of_kind(kind):
                continue  # piscine pas encore achetée
            options.append(Option(action=definition.name, label=definition.label, score=0))
        if engine.economy.enabled:
            if engine.house.layout.wild and agent.persona.age >= 16:
                options.append(Option(action="couper", label="coupe un arbre", score=0))
                site = engine.architect.site_room()
                if site is not None and not site.contractor:
                    options.append(Option(action="construire", target=site.id, score=0,
                                          label=f"travaille sur le chantier de la {site.name.lower()}"))
            if not engine.house.layout.wild and agent.persona.age >= 13 and engine.economy.owns("tondeuse"):
                options.append(Option(action="tondre", label="tond la pelouse", score=0))
            if agent.persona.is_adult:
                options.append(Option(action="epicerie", label="va faire l'épicerie", score=0))
        return options

    # ------------------------------------------------------------------ plan de la journée

    def update(self, agent: Agent) -> None:
        """Chaque tick, agent éveillé et présent : plan à demander, activités manquées."""
        engine = self.engine
        clock = engine.clock
        plan = agent.plan
        if plan is not None and plan.day == clock.day:
            for item in plan.expire(clock.minute_of_day, self.config.plan_item_window_minutes):
                engine.remember(agent, f"Pas eu le temps : {self._label(item)} ({item.hhmm}), comme prévu.", 2)
        if engine.llm is None or not self.config.plans_enabled or agent.id in self.pending_plans:
            return
        if agent.plan_requested_day != clock.day:
            if self.free_slots(agent, clock.day, clock.minute_of_day + 10):
                self._request_plan(agent, None)
        elif agent.plan_stale is not None:
            reason, agent.plan_stale = agent.plan_stale, None
            if plan is not None and plan.day == clock.day and plan.replans < self.config.max_replans_per_day:
                self._request_plan(agent, reason)

    def mark_stale(self, reason: str) -> None:
        """Imprévu (nouvelle, décès, hôpital) : chacun refera son plan à la prochaine occasion."""
        for agent in self.engine.agents:
            if not agent.dead:
                agent.plan_stale = reason

    def _request_plan(self, agent: Agent, replan_reason: str | None) -> None:
        engine = self.engine
        clock = engine.clock
        slots = self.free_slots(agent, clock.day, clock.minute_of_day + 10)
        if not slots:
            agent.plan_requested_day = clock.day
            return
        catalog = self.catalog(agent)
        context = engine.family_context([agent])
        memories, summary = engine.memories_for(agent, [context, replan_reason or ""])
        request = build_plan_request(agent, clock.total_minutes, f"{clock.day_name} (jour {clock.day + 1})",
                                     self.fixed_schedule(agent, clock.day), slots, catalog, memories,
                                     summary, engine.config.llm.max_tokens, context, replan_reason,
                                     engine.agents)
        names = {a.id: a.name for a in engine.agents}
        future = engine.llm.try_submit(request, PlanResponse, None,
                                       lambda r: validate_plan(r, catalog, slots, names))
        if future is None:
            return  # limite d'appels atteinte : on réessaiera au prochain tick
        agent.plan_requested_day = clock.day
        self.pending_plans[agent.id] = PendingPlan(future, clock.day, replan_reason is not None)

    def poll(self) -> None:
        engine = self.engine
        for agent_id, pending in list(self.pending_plans.items()):
            if not pending.future.done():
                continue
            del self.pending_plans[agent_id]
            agent = engine.agent_by_id(agent_id)
            result = _result(pending.future)
            if agent is None or agent.dead or result.value is None or pending.day != engine.clock.day:
                continue
            response = result.value
            items = plan_items(response)
            if pending.replan and agent.plan is not None:
                # On garde ce qui est déjà fait ou manqué ; le reste est remplacé
                past = [i for i in agent.plan.items if i.status != "todo"]
                agent.plan = DayPlan(day=pending.day, intention=response.intention or agent.plan.intention,
                                     items=past + items, replans=agent.plan.replans + 1)
            else:
                agent.plan = DayPlan(day=pending.day, intention=response.intention, items=items)
            summary = "; ".join(f"{i.hhmm} {self._label(i)}" for i in items)
            engine.publish("plan", agent=agent.id, name=agent.name, intention=response.intention,
                           items=[i.model_dump() for i in items], replan=pending.replan,
                           attempts=result.attempts)
            what = "Nouveau plan" if pending.replan else "Mon plan aujourd'hui"
            engine.remember(agent, f"{what} : {response.intention or summary}".rstrip(" :"), 2)
        for agent_id, pending in list(self.pending_reflections.items()):
            if pending.future.done():
                del self.pending_reflections[agent_id]
                self._apply_reflection(agent_id, pending)

    def planned_option(self, agent: Agent, options: list[Option]) -> tuple[Option, PlanItem] | None:
        """Activité prévue à faire maintenant, si rien d'urgent ne passe avant."""
        engine = self.engine
        clock = engine.clock
        plan = agent.plan
        if plan is None or plan.day != clock.day:
            return None
        if (options and options[0].urgent) or agent.needs.lowest()[1] < URGENT_THRESHOLD:
            return None
        item = plan.due(clock.minute_of_day)
        if item is None:
            return None
        for option in options:
            if option.action == item.action and option.target == item.target:
                return option, item
        definition = ACTIONS.get(item.action)
        if definition is None or not definition.selectable or item.action == "jaser":
            return None  # économie (heures, argent) ou personne disponible : on attend
        if definition.daytime_only and not DAYTIME_HOURS[0] <= clock.minute_of_day < DAYTIME_HOURS[1]:
            return None
        if engine.economy.enabled and not engine.economy.household.pantry + 1e-9 >= \
                engine.economy.portions_for(item.action):
            return None
        # Prévu même sans besoin pressant (une douche avant de sortir, une sieste par habitude)
        return Option(action=item.action, label=definition.label, score=0), item

    def boost(self, agent: Agent, options: list[Option]) -> None:
        """L'objectif du soir rend l'option visée plus attirante."""
        goal = agent.goal
        if goal is None:
            return
        if self.engine.clock.total_minutes >= goal.until:
            agent.goal = None
            return
        for option in options:
            if goal.matches(option.action, option.target):
                option.score = round(option.score * self.config.goal_boost + 3, 2)

    def on_action_started(self, agent: Agent, action: ActiveAction) -> None:
        goal = agent.goal
        if goal is not None and goal.matches(action.name, action.target):
            agent.goal = None
            self.engine.remember(agent, f"Objectif tenu : {goal.text}", 4)
        if action.name == "dormir":
            self._request_reflection(agent)

    def _label(self, item: PlanItem) -> str:
        target = self.engine.agent_by_id(item.target) if item.target else None
        return action_label(item.action, target.name if target else item.target)

    # ------------------------------------------------------------------ réflexion du soir

    def _agent_day(self, agent: Agent) -> tuple[int, int]:
        """(jour, minute absolue du réveil) de la journée éveillée en cours : après minuit, c'est la veille."""
        clock = self.engine.clock
        wake = parse_hhmm(agent.persona.schedule.wake)
        day = clock.day if clock.minute_of_day >= wake else clock.day - 1
        return day, day * MINUTES_PER_DAY + wake

    def _request_reflection(self, agent: Agent) -> None:
        engine = self.engine
        if engine.llm is None or not self.config.reflections_enabled or agent.id in self.pending_reflections:
            return
        day, since = self._agent_day(agent)
        if agent.reflected_day == day:
            return
        events = [e for e in agent.memory.since(since) if e.kind != "reflection"][-MAX_REFLECTION_EVENTS:]
        if len(events) < MIN_REFLECTION_EVENTS:
            return
        catalog = self.catalog(agent)
        texts = [e.formatted() for e in events]
        request = build_reflection_request(agent, engine.clock.total_minutes, texts, catalog,
                                           engine.config.llm.max_tokens, engine.family_context([agent]),
                                           engine.agents)
        names = {a.id: a.name for a in engine.agents}
        future = engine.llm.try_submit(request, Reflection, None,
                                       lambda r: validate_reflection(r, len(events), catalog, names))
        if future is None:
            return
        agent.reflected_day = day
        self.pending_reflections[agent.id] = PendingReflection(future, events)

    def _apply_reflection(self, agent_id: str, pending: PendingReflection) -> None:
        engine = self.engine
        agent = engine.agent_by_id(agent_id)
        result = _result(pending.future)
        if agent is None or agent.dead or result.value is None:
            return
        reflection = result.value
        now = engine.clock.total_minutes
        mem_cfg = engine.config.memory
        for number in reflection.important:
            event = pending.events[number - 1]
            event.importance = max(event.importance, 7)  # le souvenir ira en mémoire longue
        for insight in reflection.insights:
            agent.memory.add_belief(insight.text, insight.importance, now, mem_cfg.max_beliefs)
            engine.remember(agent, insight.text, insight.importance, kind="reflection")
        goal_text = None
        if reflection.goal is not None:
            spec = reflection.goal
            target = engine.agent_by_id(spec.target) if spec.target else None
            label = action_label(spec.action, target.name if target else spec.target)
            goal_text = f"{label} ({spec.why})" if spec.why else label
            agent.goal = Goal(text=goal_text, action=spec.action, target=spec.target,
                              until=now + MINUTES_PER_DAY)
        engine.publish("reflexion", agent=agent.id, name=agent.name,
                       insights=[i.model_dump() for i in reflection.insights], goal=goal_text,
                       attempts=result.attempts)


def _result(future: Future) -> StructuredResult:
    try:
        return future.result()
    except Exception as exc:  # erreur inattendue dans le thread : rien à appliquer
        return StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
