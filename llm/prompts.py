"""Templates de prompts (décision, dialogue, résumé mémoire) et schémas de réponse."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.actions import Option
    from agents.agent import Agent

JSON_RULE = "Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après, sans bloc de code."

# ---------------------------------------------------------------- schémas de réponse


class ActionDecision(BaseModel):
    action: str
    target: str | None = None
    reason: str = ""


class DialogueLine(BaseModel):
    speaker: str
    text: str


class Dialogue(BaseModel):
    lines: list[DialogueLine] = Field(min_length=1)


class MemorySummary(BaseModel):
    summary: str = Field(min_length=1)


# ---------------------------------------------------------------- validation métier


def validate_decision(decision: ActionDecision, options: list[Option],
                      names: dict[str, str]) -> ActionDecision:
    """Ramène la décision sur une option proposée ; ValueError sinon.

    names : id d'agent -> prénom, pour accepter une cible donnée par son prénom.
    """
    action = decision.action.strip().lower()
    matching = [o for o in options if o.action == action]
    if not matching:
        raise ValueError(f"action hors des options proposées : {decision.action!r}")
    target = (decision.target or "").strip().lower()
    for option in matching:
        if option.target is None and not target:
            break
        if option.target and target and target in (option.target.lower(),
                                                   names.get(option.target, option.target).lower()):
            break
    else:
        if len(matching) > 1:
            raise ValueError(f"cible ambiguë ou inconnue : {decision.target!r}")
        option = matching[0]
    return ActionDecision(action=option.action, target=option.target, reason=decision.reason.strip()[:160])


def validate_dialogue(dialogue: Dialogue, participants: dict[str, str], max_lines: int = 8) -> Dialogue:
    """Normalise les locuteurs (prénoms) et écarte les répliques d'inconnus ; ValueError si vide.

    participants : id d'agent -> prénom.
    """
    lookup = {name.lower(): name for name in participants.values()}
    lookup.update({agent_id.lower(): name for agent_id, name in participants.items()})
    lines = []
    for line in dialogue.lines:
        speaker = lookup.get(line.speaker.strip().lower())
        text = line.text.strip()
        if speaker and text:
            lines.append(DialogueLine(speaker=speaker, text=text[:220]))
    if not lines:
        raise ValueError("aucune réplique d'un participant reconnu")
    return Dialogue(lines=lines[:max_lines])


# ---------------------------------------------------------------- blocs de contexte


def persona_block(agent: Agent) -> str:
    p = agent.persona
    lines = [
        f"{p.name}, {p.age} ans ({p.role}).",
        f"Traits : {', '.join(p.traits)}.",
        f"Intérêts : {', '.join(p.interests)}.",
    ]
    if p.speech_style:
        lines.append(f"Façon de parler : {p.speech_style}")
    if p.routines:
        lines.append("Habitudes : " + " ; ".join(p.routines) + ".")
    return "\n".join(lines)


def memory_block(memories: list[str], summary: str | None = None) -> str:
    parts = []
    if summary:
        parts.append(f"Résumé de ce qui s'est passé avant : {summary}")
    if memories:
        parts.append("Souvenirs récents :\n" + "\n".join(f"- {m}" for m in memories))
    return "\n".join(parts) if parts else "Aucun souvenir particulier pour l'instant."


# ---------------------------------------------------------------- requêtes


def build_decision_request(agent: Agent, room: str, time_label: str, options: list[Option],
                           memories: list[str], summary: str | None, max_tokens: int,
                           context: str = "", extra_meta: dict | None = None) -> LLMRequest:
    system = (
        "Tu incarnes un membre d'une famille québécoise dans une simulation de vie quotidienne. "
        "Tu choisis sa prochaine activité parmi une liste d'options, en restant fidèle à sa personnalité, "
        "à son humeur et à ses besoins. " + JSON_RULE
    )
    option_lines = "\n".join(
        f"- {json.dumps({'action': o.action, 'target': o.target}, ensure_ascii=False)} : {o.label}"
        for o in options
    )
    prompt = (
        f"PERSONNAGE\n{persona_block(agent)}\n\n"
        f"SITUATION\nMoment : {time_label}. Pièce : {room}.\n"
        f"Humeur : {agent.mood}.\nBesoins : {agent.needs.describe()}.\n\n"
        + (f"FAMILLE\n{context}\n\n" if context else "")
        + f"MÉMOIRE\n{memory_block(memories, summary)}\n\n"
        f"OPTIONS POSSIBLES\n{option_lines}\n\n"
        "Choisis UNE option. Format exact :\n"
        '{"action": "<action>", "target": "<target ou null>", '
        '"reason": "<raison courte à la première personne, en français québécois, 15 mots max>"}'
    )
    meta = {
        "agent_id": agent.id,
        "name": agent.name,
        "options": [o.model_dump() for o in options],
        **(extra_meta or {}),
    }
    return LLMRequest(kind="decision", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)


def build_dialogue_request(participants: list[Agent], room: str, time_label: str,
                           memories: dict[str, list[str]], summaries: dict[str, str | None],
                           max_tokens: int, context: str = "", extra_meta: dict | None = None) -> LLMRequest:
    system = (
        "Tu écris des dialogues pour une simulation de la vie d'une famille de Québec. "
        "Les répliques sont en français québécois naturel et familier (expressions d'ici, pas de France), "
        "courtes, crédibles, cohérentes avec chaque personnalité, l'heure, la pièce, l'humeur "
        "et les souvenirs récents. La situation de la famille (argent, épicerie, chômage, santé, deuil) "
        "teinte naturellement les échanges quand c'est pertinent, avec tact pour les deuils. "
        "Pas de narration, seulement des répliques. " + JSON_RULE
    )
    blocks = []
    ids = {a.id for a in participants}
    for agent in participants:
        relations = "\n".join(f"  - envers {other.name} : {agent.persona.relations[other.id]}"
                              for other in participants
                              if other.id != agent.id and other.id in agent.persona.relations and other.id in ids)
        action = agent.action.label if agent.action else "rien de spécial"
        blocks.append(
            f"### {agent.name}\n{persona_block(agent)}\n"
            f"Fait présentement : {action}. Humeur : {agent.mood}.\n"
            f"Besoins : {agent.needs.describe()}.\n"
            f"Relations :\n{relations or '  - (aucune précisée)'}\n"
            f"{memory_block(memories.get(agent.id, []), summaries.get(agent.id))}"
        )
    names = ", ".join(a.name for a in participants)
    prompt = (
        f"Moment : {time_label}. Pièce : {room}. Personnes présentes : {names}.\n\n"
        + (f"SITUATION DE LA FAMILLE\n{context}\n\n" if context else "")
        + "\n\n".join(blocks)
        + "\n\nÉcris une courte conversation spontanée (2 à 6 répliques) entre ces personnes. "
        "Chaque réplique fait au plus 25 mots. Le champ speaker contient exactement un des prénoms. "
        'Format exact :\n{"lines": [{"speaker": "<prénom>", "text": "<réplique>"}]}'
    )
    meta = {
        "room": room,
        "participants": [{"id": a.id, "name": a.name, "role": a.persona.role} for a in participants],
        **(extra_meta or {}),
    }
    return LLMRequest(kind="dialogue", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)


def build_summary_request(agent: Agent, events: list[str], previous: str | None,
                          max_tokens: int) -> LLMRequest:
    system = (
        "Tu résumes la mémoire d'un personnage de simulation familiale québécoise. " + JSON_RULE
    )
    prompt = (
        f"PERSONNAGE\n{persona_block(agent)}\n\n"
        + (f"Résumé précédent : {previous}\n\n" if previous else "")
        + "Événements récents :\n" + "\n".join(f"- {e}" for e in events)
        + "\n\nRésume ces événements en 1 ou 2 phrases à la première personne, du point de vue de "
        f"{agent.name}, en gardant ce qui compte pour ses relations et son humeur.\n"
        'Format exact : {"summary": "<résumé>"}'
    )
    meta = {"name": agent.name, "events": events}
    return LLMRequest(kind="summary", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)
