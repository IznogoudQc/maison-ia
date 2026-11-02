"""Entrevue : le joueur pose une question à un personnage, ou lui souffle une idée (touche T).

Une question ne laisse pas de souvenir : on observe sans déranger, comme les chercheurs de « Generative
Agents » qui interrogeaient leurs agents. Une idée soufflée, elle, devient un souvenir marquant et pousse
la personne à refaire son plan : à elle (et à l'IA) de décider si elle y donne suite.
"""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from llm.interview_prompts import InterviewAnswer, build_interview_request, validate_answer

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

WHISPER_IMPORTANCE = 6


@dataclass
class Exchange:
    text: str
    whisper: bool
    answer: str | None = None          # None : en attente de l'IA
    future: Future | None = field(default=None, repr=False)


class Interviews:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.exchanges: dict[str, list[Exchange]] = {}   # agent -> échanges de la partie en cours

    def history(self, agent_id: str) -> list[Exchange]:
        return self.exchanges.get(agent_id, [])

    def busy(self, agent_id: str) -> bool:
        return any(e.answer is None for e in self.history(agent_id))

    def ask(self, agent: Agent, text: str, whisper: bool = False) -> Exchange | None:
        """Envoie la question (ou l'idée) ; la réponse arrive plus tard (poll)."""
        engine = self.engine
        text = text.strip()
        if not text or agent.dead or self.busy(agent.id):
            return None
        exchange = Exchange(text, whisper)
        self.exchanges.setdefault(agent.id, []).append(exchange)
        if whisper:
            # L'idée reste en tête : souvenir marquant, et le plan du jour sera revu en tenant compte
            engine.remember(agent, f"Une idée me trotte dans la tête : {text}", WHISPER_IMPORTANCE)
            agent.plan_stale = f"une idée en tête : {text}"
        if engine.llm is None:
            exchange.answer = "(Pas d'IA branchée : la question reste sans réponse.)"
            self._publish(agent, exchange)
            return exchange
        memories, summary = engine.memories_for(agent, [text])
        earlier = [(e.text, e.answer) for e in self.history(agent.id)[:-1] if e.answer and not e.whisper]
        request = build_interview_request(agent, engine.agents, text, whisper, memories, summary,
                                          engine.clock.total_minutes, engine.dialogue_context([agent]), earlier,
                                          engine.config.llm.max_tokens)
        exchange.future = engine.llm.try_submit(request, InterviewAnswer, None, validate_answer)
        if exchange.future is None:
            exchange.answer = "(Trop de demandes à l'IA en ce moment : réessaie dans une minute.)"
        return exchange

    def poll(self) -> None:
        for agent_id, exchanges in self.exchanges.items():
            for exchange in exchanges:
                if exchange.answer is not None or exchange.future is None or not exchange.future.done():
                    continue
                try:
                    value = exchange.future.result().value
                except Exception:  # erreur inattendue dans le thread
                    value = None
                exchange.answer = value.answer if value else "(…pas de réponse, la personne a l'air ailleurs.)"
                agent = self.engine.agent_by_id(agent_id)
                if agent is not None:
                    if exchange.whisper and value is not None:
                        self.engine.remember(agent, f"Je me suis dit : « {exchange.answer} »", 4, kind="thought")
                    self._publish(agent, exchange)

    def _publish(self, agent: Agent, exchange: Exchange) -> None:
        self.engine.publish("souffle" if exchange.whisper else "entrevue", agent=agent.id, name=agent.name,
                            text=exchange.text, answer=exchange.answer)
