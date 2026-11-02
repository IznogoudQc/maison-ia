"""Prompt de la fiche personnage : ce qu'il ressent et ce qu'il pense de chacun, à la première personne."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.prompts import JSON_RULE, mind_block, relations_block, stable_prefix
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent


class OpinionLine(BaseModel):
    name: str
    text: str


class PortraitText(BaseModel):
    ressenti: str = ""
    opinions: list[OpinionLine] = Field(default_factory=list)


def validate_portrait(portrait: PortraitText, names: list[str]) -> PortraitText:
    """Un ressenti obligatoire ; seulement des avis sur des membres connus de la famille."""
    feeling = portrait.ressenti.strip()
    if not feeling:
        raise ValueError("ressenti vide")
    lookup = {n.lower(): n for n in names}
    opinions = [OpinionLine(name=lookup[o.name.strip().lower()], text=o.text.strip()[:220])
                for o in portrait.opinions if o.name.strip().lower() in lookup and o.text.strip()]
    return PortraitText(ressenti=feeling[:280], opinions=opinions)


def build_portrait_request(agent: Agent, others: list[Agent], causes: list[tuple[str, int]], now: int,
                           max_tokens: int) -> LLMRequest:
    system = (
        "Tu prêtes ta voix intérieure à un membre d'une famille québécoise dans une simulation de vie. "
        "Il parle franchement, à la première personne, en français québécois, selon son caractère : "
        "ses qualités ET ses défauts, surtout quand ça va mal. Pas de langue de bois. " + JSON_RULE
    )
    why = "\n".join(f"- {'(+)' if sign > 0 else '(-)' if sign < 0 else '(·)'} {text}" for text, sign in causes)
    people = [o for o in others if o.id != agent.id and not o.dead]
    prompt = (
        f"COMMENT JE VAIS\n{agent.needs.describe()}\nCe qui joue sur mon humeur :\n{why or '- rien de spécial'}\n\n"
        f"EN TÊTE\n{mind_block(agent, now, with_plan=False)}\n\n"
        "SOUVENIRS RÉCENTS\n" + ("\n".join(f"- {m}" for m in agent.memory.recent(8)) or "- (aucun)") + "\n\n"
        f"CE QUE JE RESSENS POUR LES AUTRES\n{relations_block(agent, people, with_profile=True)}\n\n"
        "Écris mon ressenti du moment (1 ou 2 phrases : comment je me sens et POURQUOI), puis, pour chaque "
        "autre personne, une phrase sur ce que je pense vraiment d'elle (ce que j'aime, ce qui m'agace).\n"
        'Format exact : {"ressenti": "<phrase>", "opinions": [{"name": "<prénom>", "text": "<phrase>"}]}'
    )
    meta = {"agent": agent.id, "causes": [{"text": t, "sign": s} for t, s in causes],
            "others": [{"name": o.name, "affection": agent.relation(o.id).affection,
                        "tension": agent.relation(o.id).tension} for o in people]}
    return LLMRequest(kind="portrait", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(agent, [agent, *others]))
