"""Fiche personnage : caractère, humeur et ses causes, ce que chacun pense des autres.

Le moteur calcule les causes de l'humeur (besoins, deuil, argent, relations, souvenirs marquants) et un
avis de base sur chacun (affection, tension, dernière impression). À l'ouverture de la fiche, l'IA y
ajoute un ressenti et une phrase par personne, à la première personne ; gardés REFRESH_MINUTES de jeu.
"""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agents.needs import NEED_LABELS, NEED_LOW_WORDS
from llm.portrait_prompts import PortraitText, build_portrait_request, validate_portrait

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

REFRESH_MINUTES = 180
LOW, HIGH = 35, 85
HIGH_WORDS = {"hunger": "Le ventre plein", "energy": "De l'énergie à revendre", "hygiene": "Frais et propre",
              "social": "Assez de jasette avec du monde", "fun": "Du plaisir aujourd'hui"}
NOTABLE = 5          # importance à partir de laquelle un souvenir récent compte dans l'humeur


@dataclass
class Opinion:
    other: Agent
    affection: float
    tension: float
    label: str       # « proche, petites frictions »
    note: str        # dernière impression marquante
    text: str        # phrase de l'IA, ou avis calculé


class Portraits:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.cache: dict[str, tuple[int, PortraitText]] = {}
        self.pending: dict[str, Future] = {}

    # ------------------------------------------------------------------ calculs

    def causes(self, agent: Agent) -> list[tuple[str, int]]:
        """Ce qui joue sur l'humeur : (texte, +1 bon / -1 mauvais / 0 marquant)."""
        engine = self.engine
        now = engine.clock.total_minutes
        out: list[tuple[str, int]] = []
        if agent.grieving_until is not None and now < agent.grieving_until:
            out.append(("En deuil", -1))
        for name, value in sorted(agent.needs.as_dict().items(), key=lambda kv: kv[1]):
            if value < LOW:
                out.append((f"{NEED_LOW_WORDS[name].capitalize()} ({NEED_LABELS[name].lower()} {value:.0f}/100)", -1))
            elif value >= HIGH:
                out.append((HIGH_WORDS[name], 1))
        eco = engine.economy
        if eco.enabled and agent.persona.is_adult:
            money = eco.household.money
            if money < 0:
                out.append((f"On est dans le rouge ({money:,.0f} $)".replace(",", " "), -1))
            elif money > 2 * eco.reserve(engine.alive_count()):
                out.append(("L'argent va bien", 1))
            if any(loan.missed for loan in eco.household.loans):
                out.append(("Un paiement de prêt en retard", -1))
        for other in engine.agents:
            if other is agent or other.dead:
                continue
            relation = agent.relation(other.id)
            if relation.tension >= 45:
                out.append((f"{relation.mood.capitalize()} avec {other.name}", -1))
            elif relation.affection >= 80:
                out.append((f"Très proche de {other.name}", 1))
        recent = [e for e in agent.memory.since(now - 24 * 60) if e.importance >= NOTABLE]
        for event in sorted(recent, key=lambda e: -e.importance)[:3]:
            out.append((event.text, 0))
        return out

    def opinions(self, agent: Agent) -> list[Opinion]:
        cached = self.cache.get(agent.id)
        voiced = {o.name: o.text for o in cached[1].opinions} if cached else {}
        out = []
        for other in self.engine.agents:
            if other is agent or other.dead:
                continue
            relation = agent.relation(other.id)
            label = f"{relation.closeness}, {relation.mood}"
            out.append(Opinion(other, relation.affection, relation.tension, label, relation.note,
                               voiced.get(other.name) or self._plain_opinion(agent, other)))
        return out

    def _plain_opinion(self, agent: Agent, other: Agent) -> str:
        if agent.persona.stage == "bebe":
            return f"Gazouille quand {other.name} s'approche."
        relation = agent.relation(other.id)
        if relation.tension >= 70:
            return f"En chicane avec {other.name}."
        if relation.tension >= 45:
            return f"{other.name} lui tape sur les nerfs ces temps-ci."
        if relation.affection >= 80:
            return f"Adore {other.name}."
        if relation.affection >= 60:
            return f"S'entend bien avec {other.name}."
        return f"Se sent loin de {other.name}."

    def feeling(self, agent: Agent) -> str | None:
        cached = self.cache.get(agent.id)
        return cached[1].ressenti if cached else None

    def thinking(self, agent: Agent) -> bool:
        return agent.id in self.pending

    # ------------------------------------------------------------------ IA

    def request(self, agent: Agent) -> None:
        """À l'ouverture de la fiche : demande à l'IA le ressenti et les avis, sauf si encore frais."""
        engine = self.engine
        now = engine.clock.total_minutes
        cached = self.cache.get(agent.id)
        if (engine.llm is None or agent.dead or agent.persona.stage == "bebe" or agent.id in self.pending
                or (cached is not None and now - cached[0] < REFRESH_MINUTES)):
            return
        others = [a for a in engine.agents if a is not agent and not a.dead]
        request = build_portrait_request(agent, others, self.causes(agent), now, engine.config.llm.max_tokens)
        names = [a.name for a in others]
        future = engine.llm.try_submit(request, PortraitText, None, lambda p: validate_portrait(p, names))
        if future is not None:
            self.pending[agent.id] = future

    def poll(self) -> None:
        for agent_id, future in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[agent_id]
            try:
                result = future.result()
            except Exception:  # erreur inattendue dans le thread : on garde l'avis calculé
                continue
            if result.value is not None:
                self.cache[agent_id] = (self.engine.clock.total_minutes, result.value)
