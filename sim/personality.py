"""Personnalités qui évoluent : les conclusions de fond (réflexions) font bouger qualités et défauts, lentement.

Chaque conclusion de fond est gardée comme indice. Après trois indices, et au moins une semaine après le
dernier changement, l'IA décide si un trait s'ajoute, se renforce ou s'efface (ou rien). Le changement
devient un souvenir marquant, entre dans tous les prompts (fiche « QUI JE SUIS ») et s'affiche dans la
fiche du personnage, avec son historique.
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING

from agents.personality import TraitChange
from llm.personality_prompts import PersonalityChange, build_personality_request, validate_change
from sim.events import Event

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

EVIDENCE_NEEDED = 3
CHANGE_GAP_DAYS = 7
MAX_EVIDENCE = 6


class Personalities:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.pending: dict[str, Future] = {}
        engine.bus.subscribe("reflexion", self.on_reflection)

    def on_reflection(self, event: Event) -> None:
        deep = event.data.get("deep")
        agent = self.engine.agent_by_id(event.data.get("agent", ""))
        if not deep or agent is None or agent.visitor:
            return
        personality = agent.personality
        personality.evidence = [*personality.evidence, deep][-MAX_EVIDENCE:]
        if (len(personality.evidence) >= EVIDENCE_NEEDED
                and self.engine.clock.day - personality.last_change_day >= CHANGE_GAP_DAYS):
            self._request(agent)

    def _request(self, agent: Agent) -> None:
        engine = self.engine
        if engine.llm is None or agent.id in self.pending:
            return
        qualites, defauts = agent.qualites, agent.defauts
        history = [c.label for c in agent.personality.history]
        request = build_personality_request(agent, engine.agents, qualites, defauts, agent.personality.evidence,
                                            history, engine.config.llm.max_tokens)
        future = engine.llm.try_submit(request, PersonalityChange, None,
                                       lambda c: validate_change(c, qualites, defauts))
        if future is not None:
            self.pending[agent.id] = future

    def poll(self) -> None:
        for agent_id, future in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[agent_id]
            try:
                change = future.result().value
            except Exception:  # erreur inattendue dans le thread
                change = None
            agent = self.engine.agent_by_id(agent_id)
            if change is not None and agent is not None and not agent.dead:
                self.apply(agent, change)

    def apply(self, agent: Agent, change: PersonalityChange) -> None:
        engine = self.engine
        personality = agent.personality
        personality.evidence = personality.evidence[-1:]   # on repart presque à zéro
        if change.change == "aucun":
            return
        trait, kind = change.trait, change.kind
        if change.change == "ajouter":
            personality.added.setdefault(kind, []).append(trait)
            if trait in personality.removed:
                personality.removed.remove(trait)
            feeling = f"Je sens que je change : je deviens {trait}."
        elif change.change == "renforcer":
            personality.stronger[trait] = min(2, personality.stronger.get(trait, 0) + 1)
            feeling = f"Je suis de plus en plus {trait}, je le vois bien."
        else:
            personality.removed.append(trait)
            personality.stronger.pop(trait, None)
            feeling = f"Je ne suis plus aussi {trait} qu'avant."
        day = engine.clock.day
        entry = TraitChange(day=day, change=change.change, kind=kind, trait=trait, reason=change.reason)
        personality.history = [*personality.history, entry][-12:]
        personality.last_change_day = day
        engine.remember(agent, feeling + (f" {change.reason}" if change.reason else ""), 7, kind="reflection")
        engine.publish("personnalite", agent=agent.id, name=agent.name, change=change.change, trait=trait,
                       text=f"{agent.name} change : {entry.label}")

    def lines(self, agent: Agent) -> list[str]:
        calendar = self.engine.calendar
        return [f"{calendar.label(c.day)} : {c.label}" + (f" — {c.reason}" if c.reason else "")
                for c in reversed(agent.personality.history[-4:])]
