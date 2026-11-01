"""Prompts des conversations tour par tour (une réplique par appel) et du bilan de conversation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from llm.prompts import JSON_RULE, memory_block, mind_block, persona_block, relations_block
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent

MAX_DELTA = 3        # variation maximale de ressenti par réplique
MAX_PROMISES = 2

# ---------------------------------------------------------------- schémas de réponse


class Line(BaseModel):
    text: str
    to: str | None = None        # prénom de la personne à qui on parle
    end: bool = False            # la conversation se termine naturellement
    thought: str = ""            # pensée intérieure, jamais dite
    affection: float = 0.0       # changement de ressenti envers « to »
    tension: float = 0.0


class PromiseSpec(BaseModel):
    who: list[str] = Field(min_length=1)   # prénoms des personnes qui feront l'activité
    by: str = ""                           # prénom de celui ou celle qui promet
    action: str
    time: str                              # HH:MM
    day: str = "aujourd'hui"               # aujourd'hui, demain ou un jour de la semaine
    text: str = ""


class Feeling(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source: str = Field(alias="from")
    to: str
    affection: float = 0.0
    tension: float = 0.0


class Debrief(BaseModel):
    importance: int = 3
    summary: str = ""
    promises: list[PromiseSpec] = Field(default_factory=list)
    feelings: list[Feeling] = Field(default_factory=list)   # mode scène seulement


# ---------------------------------------------------------------- validation métier


def _clamp(value: float, limit: float = MAX_DELTA) -> float:
    return max(-limit, min(limit, value))


def validate_line(line: Line, speaker: str, listeners: dict[str, str]) -> Line:
    """Nettoie la réplique (préfixe « Prénom : », guillemets) et ramène « to » sur un id ; ValueError si vide.

    listeners : id d'agent -> prénom.
    """
    text = line.text.strip()
    text = re.sub(rf"^{re.escape(speaker)}\s*:\s*", "", text).strip().strip("«»\"").strip()
    if not text:
        raise ValueError("réplique vide")
    lookup = {name.lower(): agent_id for agent_id, name in listeners.items()}
    lookup.update({agent_id.lower(): agent_id for agent_id in listeners})
    to = lookup.get((line.to or "").strip().lower())
    return Line(text=text[:220], to=to, end=line.end, thought=line.thought.strip()[:120],
                affection=_clamp(line.affection), tension=_clamp(line.tension))


# ---------------------------------------------------------------- requêtes


def _transcript(lines: list[tuple[str, str]]) -> str:
    return "\n".join(f"{speaker} : {text}" for speaker, text in lines)


def build_line_request(speaker: Agent, listeners: list[Agent], room: str, time_label: str,
                       lines: list[tuple[str, str]], memories: list[str], summary: str | None,
                       max_tokens: int, now: int, turn: int, max_turns: int, context: str = "",
                       extra_meta: dict | None = None) -> LLMRequest:
    system = (
        f"Tu incarnes {speaker.name}, membre d'une famille québécoise, dans une conversation en cours. "
        "Tu dis UNE seule réplique, de son point de vue uniquement : tu ne sais que ce qu'il ou elle sait "
        "et tu ne vois des autres que leur air et ce qu'ils disent. Selon sa personnalité et ses relations, "
        "tu peux être sincère, taquin, bougon, éviter un sujet, mal comprendre ou cacher quelque chose. "
        "Français québécois naturel et familier, pas de narration. " + JSON_RULE
    )
    others = "\n".join(
        f"- {o.name} ({o.persona.role}), fait : {o.action.label if o.action else 'rien de spécial'}, "
        f"a l'air {o.mood}" for o in listeners
    )
    history = _transcript(lines) if lines else "(Personne n'a encore parlé : c'est toi qui commences.)"
    closing = ("C'est une des dernières répliques : amène la conversation à sa fin."
               if turn >= max_turns - 1 else
               "Mets end à true si la conversation se termine naturellement après ta réplique.")
    prompt = (
        f"PERSONNAGE\n{persona_block(speaker)}\nHumeur : {speaker.mood}. Besoins : {speaker.needs.describe()}.\n\n"
        f"SITUATION\nMoment : {time_label}. Pièce : {room}.\nAvec toi :\n{others}\n\n"
        + (f"FAMILLE\n{context}\n\n" if context else "")
        + f"CE QUE TU RESSENS POUR EUX\n{relations_block(speaker, listeners, with_profile=True)}\n\n"
        f"DANS TA TÊTE\n{mind_block(speaker, now, beliefs=3)}\n\n"
        f"TA MÉMOIRE\n{memory_block(memories, summary)}\n\n"
        f"CONVERSATION JUSQU'ICI\n{history}\n\n"
        f"Réplique {turn + 1} sur {max_turns} au plus, 25 mots max. {closing} "
        "Si tu proposes ou acceptes de faire une activité ensemble à un moment précis, dis-le clairement. "
        "thought = ce que tu penses vraiment sans le dire (15 mots max). affection et tension = comment "
        f"cet échange change ce que tu ressens envers la personne à qui tu parles (de -{MAX_DELTA} à {MAX_DELTA}).\n"
        'Format exact : {"text": "<réplique>", "to": "<prénom>", "end": false, "thought": "<pensée>", '
        '"affection": 0, "tension": 0}'
    )
    meta = {
        "speaker": {"id": speaker.id, "name": speaker.name},
        "listeners": [{"id": o.id, "name": o.name} for o in listeners],
        "room": room,
        "turn": turn,
        "max_turns": max_turns,
        "lines": lines,
        **(extra_meta or {}),
    }
    return LLMRequest(kind="line", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)


def build_debrief_request(participants: list[Agent], room: str, time_label: str, day_label: str,
                          lines: list[tuple[str, str]], activities: list[tuple[str, str]],
                          max_tokens: int, with_feelings: bool = False) -> LLMRequest:
    system = (
        "Tu analyses une conversation d'une famille québécoise dans une simulation, en observateur neutre. "
        "Tu n'inventes rien : tu relèves seulement ce qui a vraiment été dit. " + JSON_RULE
    )
    names = ", ".join(a.name for a in participants)
    catalog = "\n".join(f"- {action} : {label}" for action, label in activities)
    feelings = (
        '\nfeelings : pour chaque personne, comment son ressenti envers chaque autre a changé '
        f'(de -{MAX_DELTA} à {MAX_DELTA}).'
        if with_feelings else ""
    )
    prompt = (
        f"Moment : {time_label} ({day_label}). Pièce : {room}. Participants : {names}.\n\n"
        f"CONVERSATION\n{_transcript(lines)}\n\n"
        f"ACTIVITÉS QUI PEUVENT ÊTRE PROMISES\n{catalog}\n\n"
        "importance : de 1 (banal) à 10 (marquant pour la famille).\n"
        "summary : une phrase neutre qui résume l'échange.\n"
        f"promises : seulement les engagements explicites et acceptés de faire une activité de la liste à un moment "
        f"précis ({MAX_PROMISES} max, sinon liste vide). who = prénoms de ceux qui la feront ; by = qui a promis ; "
        "day = aujourd'hui, demain ou un jour de la semaine ; time = HH:MM ; text = la promesse en une phrase."
        f"{feelings}\n"
        'Format exact : {"importance": 3, "summary": "<résumé>", "promises": [{"who": ["<prénom>"], '
        '"by": "<prénom>", "action": "<action>", "time": "HH:MM", "day": "demain", "text": "<promesse>"}]'
        + (', "feelings": [{"from": "<prénom>", "to": "<prénom>", "affection": 0, "tension": 0}]' if with_feelings
           else "")
        + "}"
    )
    meta = {
        "participants": [{"id": a.id, "name": a.name} for a in participants],
        "lines": lines,
        "activities": [action for action, _ in activities],
        "with_feelings": with_feelings,
    }
    return LLMRequest(kind="debrief", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)
