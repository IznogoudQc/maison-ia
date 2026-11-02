"""Personnalité qui évolue : à partir des conclusions de fond, l'IA décide si un trait change (lentement)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from agents.personality import MAX_TRAITS
from llm.prompts import JSON_RULE, stable_prefix
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent

CHANGES = ("ajouter", "renforcer", "retirer", "aucun")


class PersonalityChange(BaseModel):
    change: str = "aucun"
    kind: str = "qualite"
    trait: str = ""
    reason: str = ""


def validate_change(change: PersonalityChange, qualites: list[str], defauts: list[str]) -> PersonalityChange:
    """Trait existant pour renforcer ou retirer ; nouveau (et de la place) pour ajouter."""
    kind = "defaut" if change.kind.strip().lower().startswith("d") else "qualite"
    verb = change.change.strip().lower()
    if verb not in CHANGES:
        raise ValueError(f"changement inconnu : {verb}")
    if verb == "aucun":
        return PersonalityChange(change="aucun", kind=kind, reason=change.reason.strip()[:160])
    current = qualites if kind == "qualite" else defauts
    trait = change.trait.strip().lower()[:40]
    match = next((t for t in current if t.lower() == trait), None)
    if verb in ("renforcer", "retirer") and match is None:
        raise ValueError(f"trait absent : {trait}")
    if verb == "ajouter" and (match is not None or not trait or len(current) >= MAX_TRAITS):
        raise ValueError(f"trait déjà là ou plus de place : {trait}")
    return PersonalityChange(change=verb, kind=kind, trait=match or trait, reason=change.reason.strip()[:160])


def build_personality_request(agent: Agent, family: list[Agent], qualites: list[str], defauts: list[str],
                              evidence: list[str], history: list[str], max_tokens: int) -> LLMRequest:
    system = (
        "Tu observes l'évolution d'un personnage d'une famille québécoise dans une simulation. Le caractère change "
        "lentement : un trait ne bouge que si plusieurs conclusions de fond le montrent clairement. Dans le doute, "
        "réponds « aucun ». " + JSON_RULE
    )
    prompt = (
        f"QUALITÉS ACTUELLES : {', '.join(qualites) or '(aucune)'}\n"
        f"DÉFAUTS ACTUELS : {', '.join(defauts) or '(aucun)'}\n"
        + (f"CHANGEMENTS DÉJÀ VÉCUS : {'; '.join(history[-3:])}\n" if history else "")
        + "\nCONCLUSIONS DE FOND RÉCENTES (ce que la personne a compris d'elle-même et de sa vie)\n"
        + "\n".join(f"- {e}" for e in evidence) + "\n\n"
        "Décide UN changement au plus : ajouter une qualité ou un défaut (un ou deux mots), renforcer un trait "
        "existant, retirer un trait qui ne lui ressemble plus, ou aucun. Donne la raison en une phrase.\n"
        'Format exact : {"change": "ajouter|renforcer|retirer|aucun", "kind": "qualite|defaut", '
        '"trait": "<trait>", "reason": "<pourquoi, 25 mots max>"}'
    )
    meta = {"agent": agent.id, "name": agent.name, "qualites": qualites, "defauts": defauts, "evidence": evidence}
    return LLMRequest(kind="personality", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(agent, family))
