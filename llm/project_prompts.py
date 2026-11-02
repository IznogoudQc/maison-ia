"""Projet de vie : l'IA choisit une aspiration à la mesure du personnage et la découpe en mois et en semaines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.prompts import JSON_RULE, mind_block, stable_prefix
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent


class ProjectIdea(BaseModel):
    aspiration: str
    why: str = ""
    action: str
    month_goal: str
    weeks: list[str] = Field(default_factory=list)


def validate_project(idea: ProjectIdea, allowed: set[str], keep: str | None = None) -> ProjectIdea:
    """Action connue du jeu ; quatre étapes (complétées au besoin) ; pour un nouveau mois, la même aspiration."""
    action = idea.action.strip()
    if keep is not None:
        action = keep
    if action not in allowed:
        raise ValueError(f"action inconnue : {action}")
    text, goal = idea.aspiration.strip(), idea.month_goal.strip()
    if not text or not goal:
        raise ValueError("aspiration ou objectif du mois vide")
    weeks = [w.strip()[:90] for w in idea.weeks if w.strip()][:4]
    while len(weeks) < 4:
        weeks.append(f"Continuer : {goal[:70]}")
    return ProjectIdea(aspiration=text[:80], why=idea.why.strip()[:140], action=action, month_goal=goal[:120],
                       weeks=weeks)


def build_project_request(agent: Agent, family: list[Agent], actions: dict[str, str], now: int, context: str,
                          current: str | None, history: list[str], max_tokens: int) -> LLMRequest:
    choices = "\n".join(f"- {name} : {label}" for name, label in actions.items())
    if current:
        system = ("Tu incarnes un membre d'une famille québécoise dans une simulation. Tu poursuis ton projet de vie "
                  "et tu planifies le mois qui vient, de façon réaliste. " + JSON_RULE)
        task = (f"MON PROJET DE VIE : {current}\nDÉJÀ FAIT : " + ("; ".join(history[-4:]) or "rien encore") + "\n\n"
                "Donne l'objectif du prochain mois et 4 étapes, une par semaine, qui avancent pas à pas.")
    else:
        system = ("Tu incarnes un membre d'une famille québécoise dans une simulation. Tu te donnes un projet de vie à "
                  "ta mesure (âge, goûts, caractère, situation), qui prend quelques mois, et tu le découpes. " + JSON_RULE)
        task = ("Choisis une aspiration (« apprendre le piano », « courir 5 km », « finir mon cours », « bâtir une "
                "cabane »...), l'action du jeu qui la fait avancer, l'objectif du premier mois et 4 étapes, une par semaine.")
    prompt = (
        (f"FAMILLE\n{context}\n\n" if context else "")
        + f"DANS MA TÊTE\n{mind_block(agent, now, with_plan=False)}\n\n"
        + f"ACTIONS DU JEU QUI PEUVENT FAIRE AVANCER UN PROJET\n{choices}\n\n"
        + task + "\n"
        'Format exact : {"aspiration": "<projet, 8 mots max>", "why": "<pourquoi, 20 mots max>", '
        '"action": "<nom d\'action de la liste>", "month_goal": "<objectif du mois>", '
        '"weeks": ["<semaine 1>", "<semaine 2>", "<semaine 3>", "<semaine 4>"]}'
    )
    meta = {"agent": agent.id, "name": agent.name, "actions": list(actions), "current": current,
            "interests": list(agent.persona.interests)}
    return LLMRequest(kind="project", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(agent, family))
