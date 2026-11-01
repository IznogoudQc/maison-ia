"""Vie sociale : conversations tour par tour, bilan, relations et promesses.

En mode « tour_par_tour », chaque réplique est un appel LLM séparé, écrit avec la mémoire et le
point de vue de la personne qui parle seulement. Un bilan (un appel) relève ensuite l'importance
de l'échange et les promesses faites ; le moteur fait arriver les promesses ou constate l'échec.
"""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from agents.actions import ACTIONS, DAYTIME_HOURS, URGENT_THRESHOLD
from agents.social import Promise
from llm.mind_prompts import in_slots
from llm.service import StructuredResult
from llm.social_prompts import (
    MAX_DELTA,
    MAX_PROMISES,
    Debrief,
    Line,
    build_debrief_request,
    build_line_request,
    validate_line,
)
from sim.clock import DAY_NAMES, MINUTES_PER_DAY, format_hhmm, parse_hhmm

if TYPE_CHECKING:
    from agents.agent import ActiveAction, Agent
    from sim.engine import Engine

# Activités qu'on peut se promettre de faire ensemble (ou corvées qu'on promet de faire)
PROMISABLE = ("tele", "lire", "jouer", "jaser", "baignade", "jardin", "balancoire", "tondre", "epicerie")
TENSE_PAIR = 70.0          # au-delà, la paire se reparle moins souvent
NOTE_FROM = 2.0            # variation de ressenti qui laisse une impression (note)
KEPT_AFFECTION = 4.0
BROKEN_AFFECTION, BROKEN_TENSION = -6.0, 10.0
TODAY = ("aujourd'hui", "aujourdhui", "ce soir", "ce matin", "cet après-midi", "tantôt", "tantot", "")
TOMORROW = ("demain", "demain soir", "demain matin", "demain après-midi")


@dataclass
class Conversation:
    id: int
    participant_ids: list[str]
    room: str
    started: int
    next_speaker: str
    lines: list[tuple[str, str]] = field(default_factory=list)   # (prénom, réplique)
    speakers: list[str] = field(default_factory=list)            # id de chaque locuteur
    thoughts: dict[str, list[str]] = field(default_factory=dict)  # pensées non dites, par id
    future: Future[StructuredResult[Line]] | None = None


@dataclass
class PendingDebrief:
    future: Future[StructuredResult[Debrief]] | None
    participant_ids: list[str]
    room: str
    lines: list[tuple[str, str]]
    thoughts: dict[str, list[str]]
    with_feelings: bool


class Social:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.conversations: list[Conversation] = []
        self.pending_debriefs: list[PendingDebrief] = []
        self.promises: list[Promise] = []
        self.next_id = 1
        self.last_drift_day = -1

    @property
    def config(self):
        return self.engine.config.dialogue

    def clear(self) -> None:
        self.conversations.clear()
        self.pending_debriefs.clear()

    def busy(self) -> bool:
        return bool(self.conversations or self.pending_debriefs)

    def talking_ids(self) -> set[str]:
        return {i for c in self.conversations for i in c.participant_ids}

    # ------------------------------------------------------------------ relations

    def pair_cooldown(self, a: str, b: str) -> float:
        """Cooldown de conversation d'une paire, allongé si l'un des deux est en chicane avec l'autre."""
        base = self.config.pair_cooldown_minutes
        first, second = self.engine.agent_by_id(a), self.engine.agent_by_id(b)
        if first and second and max(first.relation(b).tension, second.relation(a).tension) >= TENSE_PAIR:
            return base * self.config.tense_cooldown_factor
        return base

    def _daily_drift(self) -> None:
        clock = self.engine.clock
        if clock.minute_of_day < 6 * 60 or self.last_drift_day == clock.day:
            return
        days = 1 if self.last_drift_day >= 0 else 0
        self.last_drift_day = clock.day
        for agent in self.engine.agents:
            for relation in agent.relations.values():
                relation.drift(days, self.config.tension_decay_per_day)

    # ------------------------------------------------------------------ conversations tour par tour

    def start(self, group: list[Agent], room: str) -> bool:
        """Lance une conversation ; la personne la plus en manque de contacts parle en premier."""
        initiator = min(group, key=lambda a: a.needs.social)
        conv = Conversation(self.next_id, [a.id for a in group], room, self.engine.clock.total_minutes,
                            initiator.id)
        if not self._request_line(conv):
            return False
        self.next_id += 1
        self.conversations.append(conv)
        return True

    def _request_line(self, conv: Conversation) -> bool:
        engine = self.engine
        speaker = engine.agent_by_id(conv.next_speaker)
        listeners = [a for a in (engine.agent_by_id(i) for i in conv.participant_ids) if a and a is not speaker]
        if speaker is None or not listeners:
            return False
        about = [conv.room, *(a.name for a in listeners), *(text for _, text in conv.lines[-2:])]
        memories, summary = engine.memories_for(speaker, about)
        request = build_line_request(speaker, listeners, conv.room, engine.clock.label(), conv.lines,
                                     memories, summary, engine.config.llm.max_tokens,
                                     engine.clock.total_minutes, len(conv.lines), self.config.max_turns,
                                     engine.family_context([speaker, *listeners]), engine._prompt_meta())
        names = {a.id: a.name for a in listeners}
        future = engine.llm.try_submit(request, Line, None, lambda line: validate_line(line, speaker.name, names))
        if future is None:
            return False  # limite d'appels : on réessaiera au prochain poll
        conv.future = future
        return True

    def _still_possible(self, conv: Conversation) -> bool:
        engine = self.engine
        if engine.clock.total_minutes - conv.started > self.config.max_minutes:
            return False
        people = [engine.agent_by_id(i) for i in conv.participant_ids]
        if any(a is None or not a.is_available for a in people):
            return False
        speaker = engine.agent_by_id(conv.next_speaker)
        return speaker is not None and (engine.house.room_at(speaker.pos) == conv.room or speaker.is_walking)

    def _poll_conversations(self) -> None:
        for conv in list(self.conversations):
            if conv.future is None:
                if not self._still_possible(conv):
                    self._finish(conv)
                elif not self._request_line(conv) and \
                        self.engine.clock.total_minutes - conv.started > self.config.max_minutes:
                    self._finish(conv)
                continue
            if not conv.future.done():
                continue
            result = _result(conv.future)
            conv.future = None
            self._handle_line(conv, result)

    def _handle_line(self, conv: Conversation, result: StructuredResult) -> None:
        engine = self.engine
        speaker = engine.agent_by_id(conv.next_speaker)
        if result.value is None or speaker is None:
            self._finish(conv)
            return
        line: Line = result.value
        conv.lines.append((speaker.name, line.text))
        conv.speakers.append(speaker.id)
        if line.thought:
            conv.thoughts.setdefault(speaker.id, []).append(line.thought)
        listeners = [i for i in conv.participant_ids if i != speaker.id]
        if line.to in listeners:
            to = line.to
        elif len(conv.speakers) >= 2 and conv.speakers[-2] in listeners:
            to = conv.speakers[-2]  # on répond à la personne qui vient de parler
        else:
            to = engine.rng.choice(listeners)
        if line.affection or line.tension:
            strong = max(abs(line.affection), abs(line.tension)) >= NOTE_FROM
            speaker.relation(to).change(line.affection, line.tension, line.thought if strong else "")
        listener = engine.agent_by_id(to)
        engine.publish("replique", conv=conv.id, agent=speaker.id, speaker=speaker.name, text=line.text,
                       to=listener.name if listener else None, room=conv.room, time=engine.clock.hhmm,
                       attempts=result.attempts)
        if (line.end and len(conv.lines) >= 2) or len(conv.lines) >= self.config.max_turns:
            self._finish(conv)
            return
        conv.next_speaker = to
        if not self._still_possible(conv):
            self._finish(conv)
        else:
            self._request_line(conv)  # sinon réessayé au prochain poll

    def _finish(self, conv: Conversation) -> None:
        engine = self.engine
        if conv in self.conversations:
            self.conversations.remove(conv)
        names = [a.name for a in (engine.agent_by_id(i) for i in conv.participant_ids) if a]
        if not conv.lines:
            engine.publish("dialogue_echec", room=conv.room, participants=names, error="aucune réplique")
            return
        lines = [{"speaker": s, "text": t} for s, t in conv.lines]
        # live : les répliques ont déjà été affichées une à une ; l'événement sert à l'historique et au journal
        engine.publish("dialogue", room=conv.room, participants=names, lines=lines, time=engine.clock.hhmm,
                       attempts=len(conv.lines), live=True, mode="tour_par_tour")
        for agent_id in set(conv.speakers):
            agent = engine.agent_by_id(agent_id)
            if agent is not None:
                agent.needs.apply({"social": self.config.social_gain})
        listeners_only = set(conv.participant_ids) - set(conv.speakers)
        for agent_id in listeners_only:  # a écouté sans répondre : un peu de social quand même
            agent = engine.agent_by_id(agent_id)
            if agent is not None:
                agent.needs.apply({"social": self.config.social_gain / 2})
        self.request_debrief(conv.participant_ids, conv.room, conv.lines, conv.thoughts, with_feelings=False)

    # ------------------------------------------------------------------ bilan

    def request_debrief(self, participant_ids: list[str], room: str, lines: list[tuple[str, str]],
                        thoughts: dict[str, list[str]] | None = None, with_feelings: bool = False) -> None:
        """Après une conversation (tour par tour ou scène) : importance, résumé, promesses."""
        engine = self.engine
        people = [a for a in (engine.agent_by_id(i) for i in participant_ids) if a]
        clock = engine.clock
        activities = [(a, ACTIONS[a].label) for a in PROMISABLE]
        request = build_debrief_request(people, room, clock.label(), clock.day_name, lines, activities,
                                        engine.config.llm.max_tokens, with_feelings)
        fallback = Debrief(importance=3)
        future = engine.llm.try_submit(request, Debrief, fallback) if engine.llm else None
        pending = PendingDebrief(future, participant_ids, room, lines, thoughts or {}, with_feelings)
        if future is None:  # limite d'appels : souvenir sans bilan, tout de suite
            self._apply_debrief(pending, StructuredResult(value=fallback, ok=False, attempts=0))
        else:
            self.pending_debriefs.append(pending)

    def _poll_debriefs(self) -> None:
        for pending in [p for p in self.pending_debriefs if p.future is not None and p.future.done()]:
            self.pending_debriefs.remove(pending)
            result = _result(pending.future)
            self._apply_debrief(pending, result if result.value is not None else
                                StructuredResult(value=Debrief(importance=3), ok=False, attempts=result.attempts))

    def _apply_debrief(self, pending: PendingDebrief, result: StructuredResult) -> None:
        engine = self.engine
        debrief: Debrief = result.value
        importance = max(1, min(10, debrief.importance))
        people = {a.id: a for a in (engine.agent_by_id(i) for i in pending.participant_ids) if a and not a.dead}
        transcript = " / ".join(f"{s} : « {t} »" for s, t in pending.lines)
        content = debrief.summary.strip() or transcript
        for agent in people.values():
            others = ", ".join(a.name for a in people.values() if a is not agent)
            text = f"Jasé avec {others} ({pending.room}) : {content}"
            thoughts = pending.thoughts.get(agent.id)
            if thoughts:
                text += f" Je me suis dit : « {thoughts[-1]} »"
            engine.remember(agent, text[:400], max(2, importance))
        if pending.with_feelings:
            by_name = {a.name.lower(): a for a in people.values()}
            for feeling in debrief.feelings:
                source = by_name.get(feeling.source.strip().lower())
                target = by_name.get(feeling.to.strip().lower())
                if source and target and source is not target:
                    source.relation(target.id).change(_clamp(feeling.affection), _clamp(feeling.tension))
        promises = [p for p in (self._make_promise(spec, people) for spec in debrief.promises[:MAX_PROMISES]) if p]
        for promise in promises:
            self.promises.append(promise)
            when = self.when_label(promise.minute)
            engine.publish("promesse", id=promise.id, text=promise.text, when=when,
                           people=[people[i].name for i in promise.people])
            for agent_id in promise.people:
                engine.remember(people[agent_id], f"Promis : {promise.text} ({when}).", 5)
            for agent in people.values():
                if agent.id not in promise.people:
                    engine.remember(agent, f"Promesse entendue : {promise.text} ({when}).", 3)
        engine.publish("bilan", room=pending.room, participants=[a.name for a in people.values()],
                       importance=importance, summary=debrief.summary, promises=len(promises), ok=result.ok)

    # ------------------------------------------------------------------ promesses

    def _promise_minute(self, day_text: str, time_text: str) -> int | None:
        clock = self.engine.clock
        try:
            minute_of_day = parse_hhmm(time_text.strip())
        except (ValueError, IndexError):
            return None
        if not 0 <= minute_of_day < MINUTES_PER_DAY:
            return None
        day_text = day_text.strip().lower()
        if day_text in TODAY:
            day = clock.day
        elif day_text in TOMORROW:
            day = clock.day + 1
        else:
            weekday = next((i for i, name in enumerate(DAY_NAMES) if day_text.startswith(name)), None)
            if weekday is None:
                return None
            delta = (weekday - clock.weekday) % 7
            if delta == 0 and minute_of_day <= clock.minute_of_day:
                delta = 7
            day = clock.day + delta
        minute = day * MINUTES_PER_DAY + minute_of_day
        now = clock.total_minutes
        if not now + 10 <= minute <= now + self.config.promise_max_days * MINUTES_PER_DAY:
            return None
        return minute

    def _make_promise(self, spec, people: dict[str, Agent]) -> Promise | None:
        """Promesse réaliste seulement : activité connue, personnes présentes et libres à ce moment."""
        engine = self.engine
        by_name = {a.name.lower(): a for a in people.values()} | {a.id: a for a in people.values()}
        who = []
        for name in spec.who:
            agent = by_name.get(name.strip().lower())
            if agent is not None and agent.id not in who:
                who.append(agent.id)
        action = spec.action.strip().lower()
        minute = self._promise_minute(spec.day, spec.time)
        if not who or action not in PROMISABLE or minute is None:
            return None
        if action == "jaser" and len(who) < 2:
            return None
        day, minute_of_day = divmod(minute, MINUTES_PER_DAY)
        if any(not in_slots(minute_of_day, engine.mind.free_slots(people[i], day)) for i in who):
            return None  # au travail, à l'école, au lit ou à table à cette heure-là
        definition = ACTIONS[action]
        if definition.daytime_only and not DAYTIME_HOURS[0] <= minute_of_day < DAYTIME_HOURS[1]:
            return None
        if definition.object_kind and definition.object_kind != "porte" \
                and not engine.house.objects_of_kind(definition.object_kind):
            return None  # pas de piscine
        if action == "tondre" and not engine.economy.owns("tondeuse"):
            return None
        if action == "epicerie":
            open_from, open_to = (parse_hhmm(h) for h in engine.economy.config.shop_hours)
            if not any(people[i].persona.is_adult for i in who) or not open_from <= minute_of_day < open_to:
                return None
        if not any(self._allowed(people[i], action) for i in who):
            return None
        if any(p.status == "pending" and abs(p.minute - minute) < 90 and set(p.people) & set(who)
               for p in self.promises):
            return None  # déjà pris à ce moment-là (ou déjà promis)
        by = by_name.get(spec.by.strip().lower())
        text = spec.text.strip()[:140] or self._default_text(who, action, people)
        promise = Promise(id=self.next_id, people=who, by=by.id if by else who[0], action=action,
                          minute=minute, text=text)
        self.next_id += 1
        return promise

    def _default_text(self, who: list[str], action: str, people: dict[str, Agent]) -> str:
        names = " et ".join(people[i].name for i in who)
        return f"{names} : {ACTIONS[action].label}"

    @staticmethod
    def _allowed(agent: Agent, action: str) -> bool:
        definition = ACTIONS[action]
        if action in ("tondre",):
            return agent.persona.age >= 13
        if action == "epicerie":
            return agent.persona.is_adult
        return not ((definition.allowed and agent.id not in definition.allowed) or agent.id in definition.excluded)

    def when_label(self, minute: int) -> str:
        clock = self.engine.clock
        day = minute // MINUTES_PER_DAY
        if day == clock.day:
            prefix = "aujourd'hui"
        elif day == clock.day + 1:
            prefix = "demain"
        else:
            prefix = DAY_NAMES[day % 7]
        return f"{prefix} {format_hhmm(minute)}"

    def pending_for(self, agent_ids: set[str]) -> list[Promise]:
        return [p for p in self.promises if p.status == "pending" and agent_ids & set(p.people)]

    def _promise_action(self, agent: Agent, promise: Promise) -> ActiveAction | None:
        engine = self.engine
        partners = [i for i in promise.people if i != agent.id]
        reason = f"Promesse : {promise.text}"
        if promise.action != "jaser" and self._allowed(agent, promise.action):
            action = engine.make_action(agent, promise.action, forced=False, reason=reason)
            if action is not None:
                return action
        # Activité réservée à l'autre (les Lego de Félix) : on va la faire à côté en jasant
        for partner in partners:
            action = engine.make_action(agent, "jaser", partner, reason=reason)
            if action is not None:
                return action
        return None

    def _update_promises(self) -> None:
        engine = self.engine
        now = engine.clock.total_minutes
        for promise in [p for p in self.promises if p.status == "pending" and now >= p.minute]:
            if now > promise.minute + self.config.promise_window_minutes:
                self._break(promise)
                continue
            for agent_id in promise.people:
                if agent_id in promise.started:
                    continue
                agent = engine.agent_by_id(agent_id)
                if agent is None or not agent.is_available or agent.needs.lowest()[1] < URGENT_THRESHOLD:
                    continue
                if agent.action is not None and agent.action.forced:
                    continue  # l'horaire (souper, départ) passe avant ; on réessaiera
                action = self._promise_action(agent, promise)
                if action is not None and engine.start_action(agent, action):
                    engine._cancel_decision(agent)
                    promise.started.append(agent_id)
            alive = [i for i in promise.people if (a := engine.agent_by_id(i)) and not a.dead]
            if alive and all(i in promise.started for i in alive):
                self._keep(promise)
        self.promises = [p for p in self.promises if p.status == "pending" or now - p.minute < MINUTES_PER_DAY]

    def _keep(self, promise: Promise) -> None:
        engine = self.engine
        promise.status = "kept"
        people = [a for a in (engine.agent_by_id(i) for i in promise.people) if a and not a.dead]
        for agent in people:
            engine.remember(agent, f"Promesse tenue : {promise.text}.", 5)
            for other in people:
                if other is not agent:
                    agent.relation(other.id).change(KEPT_AFFECTION)
        engine.publish("promesse_tenue", id=promise.id, text=promise.text, people=[a.name for a in people])

    def _break(self, promise: Promise) -> None:
        engine = self.engine
        promise.status = "broken"
        people = [a for a in (engine.agent_by_id(i) for i in promise.people) if a and not a.dead]
        missing = [a for a in people if a.id not in promise.started]
        present = [a for a in people if a.id in promise.started]
        if not present:
            for agent in people:
                engine.remember(agent, f"On n'a pas pu faire ce qu'on s'était promis : {promise.text}.", 4)
        else:
            for agent in missing:
                engine.remember(agent, f"Je n'ai pas tenu ma promesse : {promise.text}.", 5)
                for other in present:
                    engine.remember(other, f"{agent.name} n'a pas tenu sa promesse : {promise.text}.", 6)
                    other.relation(agent.id).change(BROKEN_AFFECTION, BROKEN_TENSION,
                                                    f"{agent.name} n'a pas tenu sa promesse")
        engine.publish("promesse_brisee", id=promise.id, text=promise.text,
                       missing=[a.name for a in missing], people=[a.name for a in people])

    # ------------------------------------------------------------------ boucle

    def update(self) -> None:
        """Chaque tick : promesses à tenir, dérive quotidienne des relations."""
        self._daily_drift()
        self._update_promises()

    def poll(self) -> None:
        """Chaque image : répliques et bilans arrivés."""
        self._poll_conversations()
        self._poll_debriefs()

    # ------------------------------------------------------------------ sauvegarde

    def to_dict(self) -> dict:
        return {"promises": [p.model_dump(mode="json") for p in self.promises],
                "next_id": self.next_id, "last_drift_day": self.last_drift_day}

    def load_dict(self, data: dict) -> None:
        self.promises = [Promise.model_validate(p) for p in data.get("promises", [])]
        self.next_id = data.get("next_id", 1)
        self.last_drift_day = data.get("last_drift_day", -1)


def _clamp(value: float) -> float:
    return max(-MAX_DELTA, min(MAX_DELTA, value))


def _result(future: Future) -> StructuredResult:
    try:
        return future.result()
    except Exception as exc:  # erreur inattendue dans le thread
        return StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
