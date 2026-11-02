"""Fêtes et rumeurs : une invitation qui se passe de bouche à oreille, des racontars qui se déforment.

Fête : certains milieux de semaine (ou à l'approche d'un férié), un membre de la famille organise une
fête (l'IA choisit le titre, l'heure et les invités parmi les voisins et la parenté). Seul l'hôte le sait
au départ ; l'invitation se répand dans les conversations. Le jour venu, les invités arrivent, ceux qui
sont au courant s'y préparent, les autres ont la surprise, et tout le monde s'en souvient.

Rumeur : après une conversation, quelqu'un répète parfois un souvenir marquant sur une personne absente.
De conversation en conversation, la rumeur passe (jamais devant la personne concernée, sauf par accident)
et, comme au téléphone arabe, l'IA la déforme à l'occasion. Celle ou celui qui l'apprend sur son compte
en veut à qui l'a répandue.
"""

from __future__ import annotations

import random
from concurrent.futures import Future
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.gossip_prompts import (PartyIdea, RumorText, build_party_request, build_rumor_request, validate_party,
                                validate_rumor)
from sim.events import Event

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

DAY = 24 * 60
PLAN_HOUR = 9                 # on décide d'organiser une fête le matin
PARTY_CHANCE = 0.5            # mercredi ou jeudi, pour le samedi suivant (ou un férié proche)
PARTY_GAP_DAYS = 6
PARTY_MINUTES = 180
RUMOR_START = 0.12            # chance qu'une conversation lance une rumeur
RUMOR_IMPORTANCE = 6          # seul un souvenir marquant fait jaser
RUMOR_PASS = 0.6              # chance de la répéter à quelqu'un qui ne la connaît pas
RUMOR_DISTORT = 0.35          # chance que l'IA la déforme en la répétant
RUMOR_CAUGHT = 0.15           # la personne visée entend parler d'elle
RUMOR_DAYS = 4                # une rumeur s'éteint après quelques jours
MAX_RUMORS = 3
# Souvenirs qui ne font pas une rumeur : résumés de jasette, promesses, pensées, potins déjà répétés, fêtes
NOT_GOSSIP = ("Jasé avec", "Promis", "Promesse", "Paraît que", "J'ai su qu'on", "Je me suis dit",
              "m'a parlé de", "J'organise", "est venu nous voir", "est reparti", "Surprise", "On a eu bien du fun",
              "La fête", "Une idée me trotte")


class Party(BaseModel):
    host: str
    host_name: str
    title: str
    reason: str = ""
    day: int
    hour: int
    guests: list[str] = Field(default_factory=list)
    known_by: list[str] = Field(default_factory=list)
    status: str = "prevue"       # prevue, en_cours, finie

    @property
    def start(self) -> int:
        return self.day * DAY + self.hour * 60


class Rumor(BaseModel):
    subject: str                 # id de la personne visée
    subject_name: str
    origin: str                  # qui l'a lancée
    minute: int
    versions: dict[str, str] = Field(default_factory=dict)   # qui la connaît -> ce qu'on lui a raconté
    told_by: dict[str, str] = Field(default_factory=dict)    # qui -> de qui il la tient
    distortions: int = 0


class Gossip:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.party: Party | None = None
        self.past_parties: list[Party] = []
        self.rumors: list[Rumor] = []
        self.checked_day = -1
        self.pending_party: Future | None = None
        self._target: tuple[str, int, str] = ("", 0, "")
        self.pending_rumors: list[tuple[Future, Rumor, str, str]] = []   # (future, rumeur, conteur, auditeur)
        self.rng = random.Random(f"potins:{engine.config.sim.seed}")
        engine.bus.subscribe("dialogue", self.on_dialogue)

    # ------------------------------------------------------------------ fêtes

    def update(self) -> None:
        engine = self.engine
        clock = engine.clock
        if clock.minute_of_day >= PLAN_HOUR * 60 and self.checked_day != clock.day:
            self.checked_day = clock.day
            self._maybe_plan(clock.day)
        party = self.party
        if party is None:
            return
        now = clock.total_minutes
        if party.status == "prevue" and now >= party.start:
            self._begin(party)
        elif party.status == "en_cours" and now >= party.start + PARTY_MINUTES:
            self._finish(party)

    def _target_day(self, day: int) -> tuple[int, str] | None:
        calendar = self.engine.calendar
        for ahead in range(1, 4):
            name = calendar.holiday(day + ahead)
            if name:
                return day + ahead, name
        weekday = self.engine.clock.weekday
        if weekday in (2, 3):
            return day + (5 - weekday), ""
        return None

    def _maybe_plan(self, day: int) -> None:
        engine = self.engine
        if self.party is not None or self.pending_party is not None or not engine.visitors.known:
            return
        if self.past_parties and day - self.past_parties[-1].day < PARTY_GAP_DAYS:
            return
        target = self._target_day(day)
        luck = random.Random(f"fete:{engine.house.layout.name}:{day}")
        if target is None or luck.random() >= PARTY_CHANCE:
            return
        hosts = [a for a in engine.agents if a.is_available and a.persona.is_adult]
        if not hosts:
            return
        host = luck.choice(hosts)
        when, occasion = target
        guests = list(engine.visitors.known.values())
        fallback = PartyIdea(title=luck.choice(["BBQ des voisins", "Souper de famille élargi", "Après-midi jeux"]),
                             reason="pour voir du monde", hour=luck.choice([13, 15, 17]),
                             guests=[g.id for g in luck.sample(guests, min(2, len(guests)))])
        self._target = (host.id, when, occasion)
        if engine.llm is None:
            self._create(host, when, occasion, fallback)
            return
        request = build_party_request(host, engine.agents, guests, engine.calendar.label(when), occasion,
                                      engine.dialogue_context([host]), engine.config.llm.max_tokens)
        ids = {g.id for g in guests}
        self.pending_party = engine.llm.try_submit(request, PartyIdea, fallback, lambda p: validate_party(p, ids))
        if self.pending_party is None:
            self._create(host, when, occasion, fallback)

    def _create(self, host: Agent, day: int, occasion: str, idea: PartyIdea) -> None:
        engine = self.engine
        self.party = Party(host=host.id, host_name=host.name, title=idea.title, reason=idea.reason, day=day,
                           hour=idea.hour, guests=idea.guests, known_by=[host.id, *idea.guests])
        when = engine.calendar.label(day)
        engine.remember(host, f"J'organise « {idea.title} » {when} à {idea.hour} h"
                              + (f" ({occasion})" if occasion else "") + " : faut que j'en parle aux autres.", 6)
        engine.publish("fete_prevue", agent=host.id, name=host.name, title=idea.title,
                       text=f"{host.name} organise « {idea.title} » ({when}, {idea.hour} h)")

    def _begin(self, party: Party) -> None:
        engine = self.engine
        party.status = "en_cours"
        visitors = engine.visitors
        for guest_id in party.guests:
            guest = visitors.known.get(guest_id)
            if guest is not None and guest not in visitors.present:
                visitors.arrive(guest, PARTY_MINUTES)
        guests = [visitors.known[g].name for g in party.guests if g in visitors.known]
        engine.publish("fete", agent=party.host, name=party.host_name, title=party.title,
                       text=f"C'est la fête : « {party.title} »" + (f" avec {', '.join(guests)}" if guests else ""))
        for member in engine.agents:
            if not member.is_available:
                continue
            member.needs.apply({"fun": 15, "social": 15})
            if member.id in party.known_by:
                engine.remember(member, f"La fête « {party.title} » commence, enfin !", 4)
            else:
                engine.remember(member, f"Surprise : {party.host_name} a organisé « {party.title} » "
                                        "et personne ne m'avait rien dit !", 6)

    def _finish(self, party: Party) -> None:
        engine = self.engine
        party.status = "finie"
        for member in [*engine.agents, *engine.visitors.present]:
            if member.is_available:
                member.needs.apply({"fun": 10, "social": 20})
                engine.remember(member, f"On a eu bien du fun à « {party.title} » chez {party.host_name}.", 6)
        engine.publish("fin_fete", agent=party.host, name=party.host_name, title=party.title,
                       text=f"Fin de la fête « {party.title} »")
        self.past_parties = [*self.past_parties, party][-5:]
        self.party = None

    # ------------------------------------------------------------------ bouche à oreille

    def on_dialogue(self, event: Event) -> None:
        engine = self.engine
        names = set(event.data.get("participants", []))
        group = [a for a in engine.everyone if a.name in names and not a.dead]
        if len(group) < 2:
            return
        self._spread_party(group)
        self._spread_rumors(group)
        if len(self.rumors) < MAX_RUMORS and self.rng.random() < RUMOR_START:
            self._start_rumor(group)

    def _spread_party(self, group: list[Agent]) -> None:
        party = self.party
        if party is None or party.status != "prevue":
            return
        teller = next((a for a in group if a.id in party.known_by), None)
        if teller is None:
            return
        for listener in group:
            if listener.id not in party.known_by:
                party.known_by.append(listener.id)
                self.engine.remember(listener, f"{teller.name} m'a parlé de « {party.title} » "
                                               f"({self.engine.calendar.label(party.day)}, {party.hour} h).", 4)

    def _start_rumor(self, group: list[Agent]) -> None:
        engine = self.engine
        ids = {a.id for a in group}
        now = engine.clock.total_minutes
        people = [a for a in [*engine.agents, *engine.visitors.known.values()] if a.id not in ids and not a.dead]
        for teller in self.rng.sample(group, len(group)):
            for memory in reversed(teller.memory.events):
                if (now - memory.minute > 2 * DAY or memory.importance < RUMOR_IMPORTANCE or memory.kind != "event"
                        or any(word in memory.text for word in NOT_GOSSIP)):
                    continue
                subject = next((p for p in people if p.name in memory.text), None)
                if subject is None or any(r.subject == subject.id for r in self.rumors):
                    continue
                rumor = Rumor(subject=subject.id, subject_name=subject.name, origin=teller.id, minute=now,
                              versions={teller.id: memory.text})
                self.rumors.append(rumor)
                engine.publish("rumeur", agent=teller.id, name=teller.name, subject=subject.name,
                               text=f"Rumeur : {teller.name} raconte que « {memory.text} »")
                self._spread_rumors(group, only=rumor)
                return

    def _spread_rumors(self, group: list[Agent], only: Rumor | None = None) -> None:
        engine = self.engine
        now = engine.clock.total_minutes
        self.rumors = [r for r in self.rumors if now - r.minute <= RUMOR_DAYS * DAY]
        for rumor in [only] if only else list(self.rumors):
            tellers = [a for a in group if a.id in rumor.versions and a.id != rumor.subject]
            if not tellers:
                continue
            teller = self.rng.choice(tellers)
            heard = rumor.versions[teller.id]
            subject_here = next((a for a in group if a.id == rumor.subject), None)
            if subject_here is not None:
                if self.rng.random() < RUMOR_CAUGHT and subject_here.id not in rumor.versions:
                    self._caught(rumor, subject_here, teller, heard)
                continue   # on ne potine pas devant la personne concernée
            for listener in group:
                if listener.id in rumor.versions or self.rng.random() >= RUMOR_PASS:
                    continue
                if engine.llm is not None and self.rng.random() < RUMOR_DISTORT:
                    request = build_rumor_request(teller, engine.agents, heard, rumor.subject_name, listener.name,
                                                  engine.config.llm.max_tokens)
                    future = engine.llm.try_submit(request, RumorText, None, validate_rumor)
                    if future is not None:
                        rumor.versions[listener.id] = heard   # réservé : la version déformée arrive plus tard
                        self.pending_rumors.append((future, rumor, teller.id, listener.id))
                        continue
                self._hear(rumor, teller, listener, heard)

    def _hear(self, rumor: Rumor, teller: Agent, listener: Agent, text: str) -> None:
        rumor.versions[listener.id] = text
        rumor.told_by[listener.id] = teller.id
        self.engine.remember(listener, f"Paraît que, sur {rumor.subject_name} : « {text} » "
                                       f"(c'est {teller.name} qui me l'a dit).", 4)

    def _caught(self, rumor: Rumor, subject: Agent, teller: Agent, heard: str) -> None:
        engine = self.engine
        rumor.versions[subject.id] = heard
        engine.remember(subject, f"J'ai su qu'on raconte dans mon dos : « {heard} ». C'est {teller.name} qui "
                                 "le répand.", 6)
        subject.relation(teller.id).change(affection=-4, tension=8,
                                           note=f"Il paraît que {teller.name} potine sur mon compte.")
        engine.publish("rumeur_decouverte", agent=subject.id, name=subject.name,
                       text=f"{subject.name} apprend la rumeur qui court sur son compte")

    def poll(self) -> None:
        engine = self.engine
        if self.pending_party is not None and self.pending_party.done():
            future, self.pending_party = self.pending_party, None
            try:
                idea = future.result().value
            except Exception:  # erreur inattendue dans le thread
                idea = None
            host_id, day, occasion = self._target
            host = engine.agent_by_id(host_id)
            if idea is not None and host is not None and self.party is None:
                self._create(host, day, occasion, idea)
        for item in [p for p in self.pending_rumors if p[0].done()]:
            self.pending_rumors.remove(item)
            future, rumor, teller_id, listener_id = item
            try:
                value = future.result().value
            except Exception:  # erreur inattendue dans le thread
                value = None
            teller, listener = engine.agent_by_id(teller_id), engine.agent_by_id(listener_id)
            if teller is None or listener is None:
                continue
            heard = rumor.versions.get(teller_id, "")
            text = value.text if value is not None else heard
            if value is not None and text != heard:
                rumor.distortions += 1
                engine.publish("rumeur", agent=teller.id, name=teller.name, subject=rumor.subject_name,
                               text=f"La rumeur change en passant par {teller.name} : « {text} »")
            self._hear(rumor, teller, listener, text)

    # ------------------------------------------------------------------ prompts, sauvegarde

    def context_lines(self, agents: list[Agent]) -> list[str]:
        """Ce que le groupe sait : la fête qui s'en vient, une rumeur qui court (pas devant la personne visée)."""
        ids = {a.id for a in agents}
        lines = []
        party = self.party
        if party is not None and party.status == "prevue" and ids & set(party.known_by):
            lines.append(f"Fête qui s'en vient : « {party.title} », {self.engine.calendar.label(party.day)} à "
                         f"{party.hour} h, organisée par {party.host_name} (pas tout le monde est au courant).")
        elif party is not None and party.status == "en_cours":
            lines.append(f"C'est la fête en ce moment : « {party.title} ».")
        for rumor in self.rumors:
            knower = next((a for a in agents if a.id in rumor.versions), None)
            if knower is not None and rumor.subject not in ids:
                lines.append(f"{knower.name} a entendu une rumeur sur {rumor.subject_name} (pas forcément vraie) : "
                             f"« {rumor.versions[knower.id]} ».")
                break
        return lines

    def hud_lines(self) -> list[str]:
        party = self.party
        if party is None:
            return []
        when = "en cours" if party.status == "en_cours" else f"{self.engine.calendar.label(party.day)}, {party.hour} h"
        return [f"Fête : {party.title} ({when})"]

    def to_dict(self) -> dict:
        return {"party": self.party.model_dump() if self.party else None,
                "past": [p.model_dump() for p in self.past_parties],
                "rumors": [r.model_dump() for r in self.rumors], "checked_day": self.checked_day}

    def load_dict(self, data: dict | None) -> None:
        data = data or {}
        self.party = Party.model_validate(data["party"]) if data.get("party") else None
        if self.party is not None and self.party.status == "en_cours":
            self.party.status = "prevue"   # les invités ne sont pas sauvegardés : ils reviennent
        self.past_parties = [Party.model_validate(p) for p in data.get("past", [])]
        self.rumors = [Rumor.model_validate(r) for r in data.get("rumors", [])]
        self.checked_day = int(data.get("checked_day", -1))
        self.pending_party, self.pending_rumors = None, []
