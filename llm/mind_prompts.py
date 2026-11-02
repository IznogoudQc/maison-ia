"""Prompts du plan de la journée et de la réflexion du soir, avec leurs schémas et leur validation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from agents.plan import PlanItem
from llm.prompts import JSON_RULE, memory_block, mind_block, persona_block, relations_block
from llm.provider import LLMRequest
from sim.clock import format_hhmm, parse_hhmm

if TYPE_CHECKING:
    from agents.actions import Option
    from agents.agent import Agent

MAX_PLAN_ITEMS = 6
MAX_INSIGHTS = 3
MAX_SOURCES = 4

# ---------------------------------------------------------------- schémas de réponse


class PlanEntry(BaseModel):
    time: str
    action: str
    target: str | None = None
    note: str = ""


class PlanResponse(BaseModel):
    intention: str = ""
    plan: list[PlanEntry] = Field(min_length=1)


class Insight(BaseModel):
    text: str
    importance: int = 5
    sources: list[int] = Field(default_factory=list)   # numéros des souvenirs (ou constats) qui le prouvent


class GoalSpec(BaseModel):
    action: str
    target: str | None = None
    why: str = ""


class Reflection(BaseModel):
    questions: list[str] = Field(default_factory=list)  # étape 1 : les grandes questions du moment
    insights: list[Insight] = Field(min_length=1)        # étape 2 : un constat par question, avec ses sources
    deep: Insight | None = None                          # constat de fond tiré des constats précédents
    important: list[int] = Field(default_factory=list)  # numéros des événements marquants
    goal: GoalSpec | None = None


# ---------------------------------------------------------------- validation métier


def _match_option(action: str, target: str | None, catalog: list[Option],
                  names: dict[str, str]) -> Option | None:
    """Option du catalogue correspondant à (action, cible) ; la cible peut être un prénom."""
    action = action.strip().lower()
    wanted = (target or "").strip().lower()
    matching = [o for o in catalog if o.action == action]
    for option in matching:
        if option.target is None and not wanted:
            return option
        if option.target and wanted in (option.target.lower(), names.get(option.target, "").lower()):
            return option
    return matching[0] if len(matching) == 1 and matching[0].target is None else None


def in_slots(minute: int, slots: list[tuple[int, int]]) -> bool:
    return any(start <= minute < end for start, end in slots)


def validate_plan(response: PlanResponse, catalog: list[Option], slots: list[tuple[int, int]],
                  names: dict[str, str]) -> PlanResponse:
    """Garde les activités connues, à une heure libre ; ValueError si rien de valable."""
    kept: list[PlanEntry] = []
    seen: set[int] = set()
    for entry in response.plan:
        try:
            minute = parse_hhmm(entry.time.strip())
        except (ValueError, IndexError):
            continue
        option = _match_option(entry.action, entry.target, catalog, names)
        if option is None or not in_slots(minute, slots) or minute in seen:
            continue
        seen.add(minute)
        kept.append(PlanEntry(time=format_hhmm(minute), action=option.action, target=option.target,
                              note=entry.note.strip()[:80]))
    if not kept:
        raise ValueError("aucune activité valable dans le plan (action inconnue ou heure occupée)")
    kept.sort(key=lambda e: parse_hhmm(e.time))
    return PlanResponse(intention=response.intention.strip()[:120], plan=kept[:MAX_PLAN_ITEMS])


def plan_items(response: PlanResponse) -> list[PlanItem]:
    return [PlanItem(minute=parse_hhmm(e.time), action=e.action, target=e.target, note=e.note)
            for e in response.plan]


def validate_reflection(reflection: Reflection, event_count: int, catalog: list[Option],
                        names: dict[str, str], previous_count: int = 0) -> Reflection:
    def sources(numbers: list[int], count: int) -> list[int]:
        return sorted({n for n in numbers if 1 <= n <= count})[:MAX_SOURCES]

    insights = [Insight(text=i.text.strip()[:200], importance=max(1, min(10, i.importance)),
                        sources=sources(i.sources, event_count))
                for i in reflection.insights if i.text.strip()][:MAX_INSIGHTS]
    if not insights:
        raise ValueError("réflexion vide")
    deep = None
    if reflection.deep is not None and reflection.deep.text.strip() and previous_count:
        found = sources(reflection.deep.sources, previous_count)
        if found:  # une conclusion de fond doit s'appuyer sur des constats précédents
            deep = Insight(text=reflection.deep.text.strip()[:200], sources=found,
                           importance=max(8, min(10, reflection.deep.importance)))
    important = sorted({n for n in reflection.important if 1 <= n <= event_count})[:3]
    goal = None
    if reflection.goal is not None:
        option = _match_option(reflection.goal.action, reflection.goal.target, catalog, names)
        if option is not None:
            goal = GoalSpec(action=option.action, target=option.target, why=reflection.goal.why.strip()[:100])
    questions = [q.strip()[:120] for q in reflection.questions if q.strip()][:3]
    return Reflection(questions=questions, insights=insights, deep=deep, important=important, goal=goal)


def _catalog_lines(catalog: list[Option]) -> str:
    return "\n".join(
        f"- {json.dumps({'action': o.action, 'target': o.target}, ensure_ascii=False)} : {o.label}"
        for o in catalog
    )


def _slots_text(slots: list[tuple[int, int]]) -> str:
    return ", ".join(f"{format_hhmm(a)}-{format_hhmm(b % (24 * 60))}" for a, b in slots) or "aucun"


def build_plan_request(agent: Agent, now: int, day_label: str, fixed: list[str],
                       slots: list[tuple[int, int]], catalog: list[Option], memories: list[str],
                       summary: str | None, max_tokens: int, context: str = "",
                       replan_reason: str | None = None, family: list[Agent] | None = None) -> LLMRequest:
    system = (
        "Tu incarnes un membre d'une famille québécoise dans une simulation de vie quotidienne. "
        "Tu planifies sa journée de façon réaliste, selon sa personnalité, ses préoccupations "
        "et ce qui se passe dans la famille. " + JSON_RULE
    )
    relations = relations_block(agent, family or [], with_profile=True)
    task = (
        f"IMPRÉVU : {replan_reason}\nRefais ton plan pour le reste de la journée en tenant compte de ça."
        if replan_reason else "C'est le matin : planifie ta journée."
    )
    prompt = (
        f"PERSONNAGE\n{persona_block(agent)}\nRelations :\n{relations}\n\n"
        f"AUJOURD'HUI : {day_label}\n"
        f"Déjà prévu (horaire fixe) : {'; '.join(fixed) or 'rien'}.\n"
        f"Plages libres : {_slots_text(slots)}.\n\n"
        + (f"FAMILLE\n{context}\n\n" if context else "")
        + f"DANS MA TÊTE\n{mind_block(agent, now, with_plan=bool(replan_reason))}\n\n"
        f"MÉMOIRE\n{memory_block(memories, summary)}\n\n"
        f"ACTIVITÉS POSSIBLES\n{_catalog_lines(catalog)}\n\n"
        f"{task}\n"
        f"Choisis 3 à {MAX_PLAN_ITEMS} activités, chacune à une heure (HH:MM) comprise dans une plage libre. "
        "La note dit pourquoi en quelques mots, à la première personne.\n"
        'Format exact : {"intention": "<fil de ta journée, 15 mots max>", '
        '"plan": [{"time": "HH:MM", "action": "<action>", "target": "<target ou null>", "note": "<pourquoi>"}]}'
    )
    meta = {
        "agent_id": agent.id,
        "name": agent.name,
        "slots": slots,
        "catalog": [o.model_dump() for o in catalog],
        "favorites": agent.persona.favorite_actions,
        "replan": bool(replan_reason),
    }
    return LLMRequest(kind="plan", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)


def build_reflection_request(agent: Agent, now: int, events: list[str], catalog: list[Option],
                             max_tokens: int, context: str = "", family: list[Agent] | None = None,
                             previous: list[str] | None = None, reason: str = "soir") -> LLMRequest:
    """Réflexion à la « Generative Agents » : les grandes questions, puis un constat sourcé par question."""
    moment = ("C'est le soir : la personne repense à ce qu'elle a vécu" if reason == "soir"
              else "Il vient de se passer beaucoup de choses : la personne prend un moment pour y repenser")
    system = (
        f"Tu incarnes un membre d'une famille québécoise dans une simulation. {moment} et en tire des "
        "constats personnels, honnêtes et concrets sur elle-même, ses proches et ce qui compte pour elle. "
        "Pas besoin de parler d'argent ou de bouffe si ce n'est pas ce qui a marqué. " + JSON_RULE
    )
    numbered = "\n".join(f"{n}. {e}" for n, e in enumerate(events, 1))
    earlier = "\n".join(f"R{n}. {r}" for n, r in enumerate(previous or [], 1))
    deep_rule = (
        "ÉTAPE 3 (seulement si ça se dégage vraiment) : à partir de MES CONSTATS DES DERNIERS JOURS, une "
        "conclusion de fond sur ma vie, plus large qu'un seul jour, avec les numéros R qui la fondent.\n"
        if previous else "")
    prompt = (
        f"PERSONNAGE\n{persona_block(agent)}\n\n"
        + (f"FAMILLE\n{context}\n\n" if context else "")
        + f"DANS MA TÊTE\n{mind_block(agent, now, with_plan=True)}\n\n"
        + (f"MES RELATIONS\n{relations_block(agent, family)}\n\n" if family else "")
        + f"CE QUE J'AI VÉCU DERNIÈREMENT\n{numbered}\n\n"
        + (f"MES CONSTATS DES DERNIERS JOURS\n{earlier}\n\n" if previous else "")
        + f"OBJECTIFS POSSIBLES POUR DEMAIN\n{_catalog_lines(catalog)}\n\n"
        "ÉTAPE 1 : en relisant ces souvenirs, quelles sont les 3 grandes questions que je me pose ?\n"
        f"ÉTAPE 2 : pour chaque question, un constat de haut niveau à la première personne, en français "
        f"québécois (25 mots max), noté de 1 (banal) à 10 (bouleversant), avec les numéros des souvenirs "
        f"qui le prouvent ({MAX_SOURCES} max).\n" + deep_rule +
        "Indique aussi les numéros des souvenirs (3 max) qui m'ont le plus marqué, et au besoin un objectif "
        "pour demain parmi la liste (ou null).\n"
        'Format exact : {"questions": ["<question>"], "insights": [{"text": "<constat>", "importance": 5, '
        '"sources": [1, 2]}], "deep": {"text": "<conclusion de fond>", "importance": 8, "sources": [1]} ou null, '
        '"important": [1], "goal": {"action": "<action>", "target": "<target ou null>", "why": "<pourquoi>"}}'
    )
    meta = {
        "agent_id": agent.id,
        "name": agent.name,
        "events": events,
        "previous": previous or [],
        "catalog": [o.model_dump() for o in catalog],
    }
    return LLMRequest(kind="reflection", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)
