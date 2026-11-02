"""Templates de prompts (décision, dialogue, résumé mémoire) et schémas de réponse."""

from __future__ import annotations

import json
import re
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

VARIETY = ("Varie les sujets d'une conversation à l'autre : la journée, le travail ou l'école, les intérêts de chacun, les projets, les enfants, une anecdote, une blague, un souvenir. L'argent et la bouffe reviennent seulement quand il se passe quelque chose de nouveau. ")


WORLD_RULES = ("La famille vit au Québec, aujourd'hui. Le temps passe minute par minute : on se lève, on mange, on travaille ou on va à l'école en semaine, on jase, on se repose, on dort. Les besoins vont de 0 (au plancher) à 100 (comblé) : satiété, énergie, hygiène, social et loisir ; un besoin au plancher rend maussade et peut nuire à la santé. L'argent vient des paies et part dans les factures du vendredi, l'épicerie et les achats. Chaque personne a ses souvenirs, ses constats et ses relations : elle agit selon son caractère (qualités et défauts), son humeur et ce qu'elle sait, pas selon ce que les autres pensent en secret. On parle un français québécois naturel et familier (expressions d'ici, pas de France). Les réponses sont toujours en JSON valide, au format demandé à la fin du message.")


def family_roster(family: list[Agent] | None, exclude: Agent | None = None) -> str:
    """Portrait stable de chaque membre (pour le cache) : âge, rôle, caractère, intérêts."""
    lines = []
    for member in family or []:
        if member is exclude or member.dead:
            continue
        p = member.persona
        parts = [f"{p.name}, {p.age} ans ({p.role}) : {', '.join(p.traits)}"]
        if p.qualites:
            parts.append(f"qualités : {', '.join(p.qualites)}")
        if p.defauts:
            parts.append(f"défauts : {', '.join(p.defauts)}")
        if p.interests:
            parts.append(f"aime : {', '.join(p.interests[:3])}")
        lines.append("- " + " ; ".join(parts) + ".")
    return "\n".join(lines) or "- (personne d'autre)"


def stable_prefix(agent: Agent | None, family: list[Agent] | None) -> str:
    """Début de message identique d'un appel à l'autre pour cette personne : mis en cache par Claude."""
    head = f"QUI JE SUIS\n{persona_block(agent)}\n\n" if agent is not None else ""
    return (f"{head}LA FAMILLE\n{family_roster(family, exclude=agent)}\n\n"
            f"LE MONDE\n{WORLD_RULES}")


def topics_block(recent: list[str] | None, topic: str | None) -> str:
    """Sujets déjà jasés entre ces personnes (à ne pas reprendre) et une idée pour lancer la conversation."""
    text = ""
    if recent:
        text += ("\n\nDÉJÀ JASÉ RÉCEMMENT ENSEMBLE (n'y revenez pas sans élément nouveau) :\n"
                 + "\n".join(f"- {r}" for r in recent))
    if topic:
        text += f"\n\nIDÉE DE SUJET (si rien de plus pressant) : {topic}."
    return text



def persona_block(agent: Agent) -> str:
    p = agent.persona
    lines = [
        f"{p.name}, {p.age} ans ({p.role}).",
        f"Traits : {', '.join(p.traits)}.",
        f"Intérêts : {', '.join(p.interests)}.",
    ]
    if p.qualites:
        lines.append(f"Qualités : {', '.join(p.qualites)}.")
    if p.defauts:
        lines.append(f"Défauts (ils paraissent surtout quand ça va mal) : {', '.join(p.defauts)}.")
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


def mind_block(agent: Agent, now: int, with_plan: bool = True, beliefs: int = 3, with_goal: bool = True) -> str:
    """Constats des réflexions, intention et plan du jour, objectif en cours (with_goal : pas pour jaser)."""
    lines = [f"- Je pense : {b.text}" for b in agent.memory.beliefs[-beliefs:]]
    plan = agent.plan
    if plan is not None and plan.day == now // (24 * 60):
        if plan.intention:
            lines.append(f"- Mon intention aujourd'hui : {plan.intention}")
        if with_plan and plan.items:
            marks = {"done": "fait", "missed": "manqué", "todo": "à faire"}
            steps = "; ".join(f"{i.hhmm} {i.action}{' ' + i.target if i.target else ''} ({marks[i.status]})"
                              for i in plan.items)
            lines.append(f"- Mon plan : {steps}")
    if with_goal and agent.goal is not None and now < agent.goal.until:
        lines.append(f"- Je me suis promis : {agent.goal.text}")
    return "\n".join(lines) if lines else "Rien de particulier en tête."


def relations_block(agent: Agent, others: list[Agent], with_profile: bool = False) -> str:
    """Ce que l'agent ressent envers chacun en ce moment (et, au besoin, la relation de fond)."""
    lines = []
    for other in others:
        if other.id == agent.id or other.dead:
            continue
        line = f"- {other.name} : {agent.relation(other.id).describe()}"
        if with_profile and other.id in agent.persona.relations:
            line += f". De fond : {agent.persona.relations[other.id]}"
        lines.append(line)
    return "\n".join(lines) or "- (personne)"


# ---------------------------------------------------------------- requêtes


def build_decision_request(agent: Agent, room: str, time_label: str, options: list[Option],
                           memories: list[str], summary: str | None, max_tokens: int,
                           context: str = "", extra_meta: dict | None = None, now: int = 0,
                           family: list[Agent] | None = None) -> LLMRequest:
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
        f"SITUATION\nMoment : {time_label}. Pièce : {room}.\n"
        f"Humeur : {agent.mood}.\nBesoins : {agent.needs.describe()}.\n\n"
        + (f"FAMILLE\n{context}\n\n" if context else "")
        + f"DANS MA TÊTE\n{mind_block(agent, now)}\n\n"
        + (f"MES RELATIONS EN CE MOMENT\n{relations_block(agent, family)}\n\n" if family else "")
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
    return LLMRequest(kind="decision", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(agent, family))


def build_dialogue_request(participants: list[Agent], room: str, time_label: str,
                           memories: dict[str, list[str]], summaries: dict[str, str | None],
                           max_tokens: int, context: str = "", extra_meta: dict | None = None,
                           now: int = 0, recent: list[str] | None = None, topic: str | None = None,
                           family: list[Agent] | None = None) -> LLMRequest:
    system = (
        "Tu écris des dialogues pour une simulation de la vie d'une famille de Québec. "
        "Les répliques sont en français québécois naturel et familier (expressions d'ici, pas de France), "
        "courtes, crédibles, cohérentes avec chaque personnalité, l'heure, la pièce, l'humeur "
        "et les souvenirs récents. La situation de la famille peut teinter un échange, avec tact pour les "
        "deuils, sans devenir le sujet de chaque conversation. " + VARIETY +
        "Pas de narration, seulement des répliques. " + JSON_RULE
    )
    blocks = []
    for agent in participants:
        action = agent.action.label if agent.action else "rien de spécial"
        blocks.append(
            f"### {agent.name}\n{persona_block(agent)}\n"
            f"Fait présentement : {action}. Humeur : {agent.mood}.\n"
            f"Besoins : {agent.needs.describe()}.\n"
            f"Relations :\n{relations_block(agent, participants, with_profile=True)}\n"
            f"En tête :\n{mind_block(agent, now, with_plan=False, beliefs=2, with_goal=False)}\n"
            f"{memory_block(memories.get(agent.id, []), summaries.get(agent.id))}"
        )
    names = ", ".join(a.name for a in participants)
    prompt = (
        f"Moment : {time_label}. Pièce : {room}. Personnes présentes : {names}.\n\n"
        + (f"SITUATION DE LA FAMILLE\n{context}\n\n" if context else "")
        + "\n\n".join(blocks)
        + topics_block(recent, topic)
        + "\n\nÉcris une courte conversation spontanée (2 à 6 répliques) entre ces personnes. "
        "Chaque réplique fait au plus 25 mots. Le champ speaker contient exactement un des prénoms. "
        'Format exact :\n{"lines": [{"speaker": "<prénom>", "text": "<réplique>"}]}'
    )
    meta = {
        "room": room,
        "participants": [{"id": a.id, "name": a.name, "role": a.persona.role} for a in participants],
        **(extra_meta or {}),
    }
    return LLMRequest(kind="dialogue", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(None, family or participants))


class EventStory(BaseModel):
    text: str = Field(min_length=1)


def validate_story(story: EventStory, base: str) -> EventStory:
    """Le récit garde tous les chiffres du fait (montants, jours, portions) ; ValueError sinon."""
    text = " ".join(story.text.split())[:240]
    digits = re.findall(r"\d+", base)
    plain = text.replace("\u202f", "").replace("\xa0", "")
    missing = [d for d in digits if d not in re.findall(r"\d+", plain.replace(" ", ""))
               and d not in re.findall(r"\d+", plain)]
    if missing:
        raise ValueError(f"chiffres du fait absents du récit : {', '.join(missing)}")
    return EventStory(text=text)


def build_story_request(base: str, good: bool, context: str, max_tokens: int) -> LLMRequest:
    system = (
        "Tu es le narrateur d'une simulation de vie d'une famille québécoise. Tu racontes un événement du jour "
        "en une ou deux phrases vivantes, en français québécois, sans rien inventer qui contredise le fait. "
        "Tous les chiffres du fait (montants, jours, heures, portions) doivent apparaître tels quels. " + JSON_RULE
    )
    tone = "bonne nouvelle" if good else "coup dur"
    prompt = (
        f"FAIT ({tone}) : {base}\n\n"
        + (f"SITUATION DE LA FAMILLE\n{context}\n\n" if context else "")
        + "Raconte ce fait en 35 mots au plus, en nommant les personnes concernées s'il y en a.\n"
        'Format exact : {"text": "<récit>"}'
    )
    return LLMRequest(kind="event_story", system=system, prompt=prompt, max_tokens=max_tokens,
                      meta={"base": base, "good": good})


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
