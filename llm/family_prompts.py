"""Prompts de la vie de famille : le couple parle d'avoir un enfant, puis l'IA imagine le bébé."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.architect_prompts import SpeechLine
from llm.prompts import JSON_RULE, mind_block, persona_block, relations_block
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent

MAX_DISCUSSION = 4
# Prénoms de repli (sans genre présumé : on ne choisit rien selon le prénom)
FALLBACK_NAMES = ["Charlie", "Alex", "Sasha", "Noa", "Éden", "Camille", "Jessy", "Lou", "Andy", "Ariel"]


class BabyTalk(BaseModel):
    decision: str            # oui ou pas_maintenant
    reason: str = ""
    discussion: list[SpeechLine] = Field(default_factory=list)

    @property
    def yes(self) -> bool:
        return self.decision.strip().lower() in ("oui", "yes", "on_essaie", "on essaie")


class ChildProfile(BaseModel):
    name: str
    traits: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    speech_style: str = ""
    color: list[int] = Field(default_factory=lambda: [120, 160, 200])
    hair: list[int] = Field(default_factory=lambda: [90, 64, 44])


def validate_talk(talk: BabyTalk, names: dict[str, str]) -> BabyTalk:
    decision = "oui" if talk.yes else "pas_maintenant"
    lookup = {n.lower(): n for n in names.values()} | {i.lower(): n for i, n in names.items()}
    discussion = [SpeechLine(speaker=lookup[line.speaker.strip().lower()], text=line.text.strip()[:200])
                  for line in talk.discussion if line.speaker.strip().lower() in lookup and line.text.strip()]
    return BabyTalk(decision=decision, reason=talk.reason.strip()[:160], discussion=discussion[:MAX_DISCUSSION])


def _rgb(values: list[int], default: list[int]) -> list[int]:
    if len(values) != 3:
        return default
    return [max(0, min(255, int(v))) for v in values]


def validate_child(profile: ChildProfile, taken: set[str]) -> ChildProfile:
    """Prénom libre dans la famille, 2 à 4 traits, couleurs valides ; ValueError sans prénom utilisable."""
    name = profile.name.strip().split()[0][:20] if profile.name.strip() else ""
    if not name or name.lower() in {t.lower() for t in taken}:
        raise ValueError(f"prénom vide ou déjà pris dans la famille : {profile.name!r}")
    traits = [t.strip()[:30] for t in profile.traits if t.strip()][:4]
    if len(traits) < 2:
        raise ValueError("il faut au moins deux traits de caractère")
    return ChildProfile(name=name, traits=traits, interests=[i.strip()[:40] for i in profile.interests if i.strip()][:3],
                        speech_style=profile.speech_style.strip()[:120],
                        color=_rgb(profile.color, [120, 160, 200]), hair=_rgb(profile.hair, [90, 64, 44]))


def build_talk_request(couple: list[Agent], context: str, now: int, max_tokens: int,
                       children: int) -> LLMRequest:
    system = (
        "Tu joues un couple québécois dans une simulation de vie. Ce soir, ils parlent d'avoir un "
        f"{'autre ' if children else ''}enfant. Ils décident selon leur caractère, leur relation, leur bonheur, "
        "leur argent et leur maison : c'est un vrai choix, « pas maintenant » est une réponse valable. " + JSON_RULE
    )
    people = "\n\n".join(
        f"### {a.name}\n{persona_block(a)}\nCe que {a.name} ressent :\n{relations_block(a, couple)}\n"
        f"En tête :\n{mind_block(a, now, with_plan=False)}" for a in couple)
    prompt = (
        f"LE COUPLE\n{people}\n\nSITUATION\n{context}\nEnfants : {children}.\n\n"
        "Écris leur discussion (2 à 4 répliques, français québécois, 20 mots max chacune) et leur décision.\n"
        'Format exact : {"decision": "oui" ou "pas_maintenant", "reason": "<pourquoi, une phrase>", '
        '"discussion": [{"speaker": "<prénom>", "text": "<réplique>"}]}'
    )
    meta = {"couple": [{"id": a.id, "name": a.name} for a in couple], "children": children}
    return LLMRequest(kind="baby_talk", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)


def build_birth_request(parents: list[Agent], taken: set[str], max_tokens: int, adoption: bool) -> LLMRequest:
    system = (
        "Tu imagines le tempérament d'un bébé qui vient d'arriver dans une famille québécoise de simulation. "
        "Les parents choisissent le prénom ; tu décris des traits de caractère qui se révéleront en grandissant "
        "(un mélange des parents, avec ses propres surprises). " + JSON_RULE
    )
    people = "\n\n".join(f"### {a.name}\n{persona_block(a)}" for a in parents)
    how = "Le couple vient d'adopter ce bébé." if adoption else "Le bébé vient de naître."
    prompt = (
        f"LES PARENTS\n{people}\n\n{how}\nPrénoms déjà pris dans la famille : {', '.join(sorted(taken))}.\n\n"
        "Donne un prénom (québécois, un seul mot), 3 traits, 2 intérêts qu'il aura enfant, sa future façon de "
        "parler, une couleur de vêtement et une couleur de cheveux (RGB).\n"
        'Format exact : {"name": "<prénom>", "traits": ["..."], "interests": ["..."], "speech_style": "...", '
        '"color": [r, g, b], "hair": [r, g, b]}'
    )
    meta = {"parents": [{"id": a.id, "name": a.name} for a in parents], "taken": sorted(taken)}
    return LLMRequest(kind="birth", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)
