"""Fêtes et rumeurs : l'IA imagine la fête qu'organise un personnage, et déforme une rumeur qui circule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.prompts import JSON_RULE, stable_prefix
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent

PARTY_HOURS = (11, 20)
MAX_RUMOR = 220


class PartyIdea(BaseModel):
    title: str
    reason: str = ""
    hour: int = 15
    guests: list[str] = Field(default_factory=list)   # ids des invités (voisins, parenté, amis)


class RumorText(BaseModel):
    text: str


def validate_party(idea: PartyIdea, guest_ids: set[str]) -> PartyIdea:
    title = idea.title.strip()
    if not title:
        raise ValueError("fête sans titre")
    hour = min(max(int(idea.hour), PARTY_HOURS[0]), PARTY_HOURS[1])
    guests = [g for g in dict.fromkeys(idea.guests) if g in guest_ids][:3]
    return PartyIdea(title=title[:60], reason=idea.reason.strip()[:160], hour=hour, guests=guests)


def validate_rumor(rumor: RumorText) -> RumorText:
    text = rumor.text.strip()
    if not text:
        raise ValueError("rumeur vide")
    return RumorText(text=text[:MAX_RUMOR])


def build_party_request(host: Agent, family: list[Agent], guests: list[Agent], when: str, occasion: str,
                        context: str, max_tokens: int) -> LLMRequest:
    system = (
        "Tu incarnes un membre d'une famille québécoise dans une simulation. Tu organises une petite fête à la "
        "maison selon ton caractère, tes goûts et ce que la famille vit (budget compris). " + JSON_RULE
    )
    people = "\n".join(f"- {g.id} : {g.name}, {g.persona.role}" for g in guests) or "(personne)"
    prompt = (
        f"QUAND : {when}" + (f" ({occasion})" if occasion else "") + "\n\n"
        + (f"FAMILLE\n{context}\n\n" if context else "")
        + f"GENS QU'ON PEUT INVITER (en plus de la famille)\n{people}\n\n"
        "Donne la fête : un titre court et concret (« BBQ des voisins », « Soirée tire sur la neige »), "
        f"pourquoi tu la fais, l'heure (entre {PARTY_HOURS[0]} et {PARTY_HOURS[1]}) et 0 à 3 invités (leurs ids).\n"
        'Format exact : {"title": "<titre>", "reason": "<pourquoi, 20 mots max>", "hour": 15, "guests": ["id"]}'
    )
    meta = {"host": host.id, "name": host.name, "guests": [g.id for g in guests], "occasion": occasion}
    return LLMRequest(kind="party", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(host, family))


def build_rumor_request(teller: Agent, family: list[Agent], heard: str, subject: str, listener: str,
                        max_tokens: int) -> LLMRequest:
    system = (
        "Tu incarnes un membre d'une famille québécoise dans une simulation. Tu répètes une rumeur que tu as "
        "entendue, à ta façon : comme dans le téléphone arabe, tu l'enjolives, l'exagères ou la comprends de "
        "travers selon ton caractère, sans tout inventer. " + JSON_RULE
    )
    prompt = (
        f"CE QUE TU AS ENTENDU DIRE SUR {subject.upper()} : « {heard} »\n\n"
        f"Tu le racontes à {listener}. Une phrase, 30 mots max, en français québécois.\n"
        'Format exact : {"text": "<la rumeur telle que tu la racontes>"}'
    )
    meta = {"agent": teller.id, "name": teller.name, "heard": heard, "subject": subject}
    return LLMRequest(kind="rumor", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(teller, family))
