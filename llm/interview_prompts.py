"""Entrevue : on pose une question à un personnage (ou on lui souffle une idée) ; il répond de son point de vue."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from llm.prompts import JSON_RULE, memory_block, mind_block, relations_block, stable_prefix
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent

MAX_ANSWER = 400


class InterviewAnswer(BaseModel):
    answer: str


def validate_answer(answer: InterviewAnswer) -> InterviewAnswer:
    text = answer.answer.strip()
    if not text:
        raise ValueError("réponse vide")
    return InterviewAnswer(answer=text[:MAX_ANSWER])


def build_interview_request(agent: Agent, family: list[Agent], text: str, whisper: bool, memories: list[str],
                            summary: str | None, now: int, context: str, exchanges: list[tuple[str, str]],
                            max_tokens: int) -> LLMRequest:
    if whisper:
        system = (
            "Tu incarnes un membre d'une famille québécoise dans une simulation. Une petite voix intérieure lui "
            "souffle une idée. Tu dis sa réaction intérieure, sincère, selon son caractère, ses souvenirs et ce "
            "que la personne vit : l'idée peut lui plaire, l'agacer ou la laisser indifférente. " + JSON_RULE
        )
        task = (f"LA PETITE VOIX TE SOUFFLE : « {text} »\n\nRéagis intérieurement en une ou deux phrases à la "
                "première personne, en français québécois (40 mots max).")
    else:
        system = (
            "Tu incarnes un membre d'une famille québécoise dans une simulation. Une personne qui observe la "
            "famille lui pose une question, comme en entrevue. Tu réponds avec franchise, à la première personne, "
            "en français québécois, à partir de tes vrais souvenirs, tes constats et ton caractère. Tu ne sais "
            "que ce que tu as vécu : si tu ne sais pas, dis-le. " + JSON_RULE
        )
        task = f"QUESTION : « {text} »\n\nRéponds en 1 à 4 phrases (80 mots max)."
    earlier = "\n".join(f"Question : {q}\nMoi : {a}" for q, a in exchanges[-4:])
    prompt = (
        f"MOI EN CE MOMENT\nHumeur : {agent.mood}. Fait présentement : "
        f"{agent.action.label if agent.action else 'rien de spécial'}.\n\n"
        + (f"FAMILLE\n{context}\n\n" if context else "")
        + f"DANS MA TÊTE\n{mind_block(agent, now, with_plan=False)}\n\n"
        f"MES RELATIONS\n{relations_block(agent, family, with_profile=True)}\n\n"
        f"MES SOUVENIRS LIÉS\n{memory_block(memories, summary)}\n\n"
        + (f"PLUS TÔT DANS L'ENTREVUE\n{earlier}\n\n" if earlier else "")
        + task + '\nFormat exact : {"answer": "<réponse>"}'
    )
    meta = {"agent": agent.id, "name": agent.name, "text": text, "whisper": whisper, "memories": memories}
    return LLMRequest(kind="interview", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta,
                      prefix=stable_prefix(agent, family))
