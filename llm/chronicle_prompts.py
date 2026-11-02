"""Chronique de la semaine : l'IA raconte la semaine de la famille comme un petit journal de quartier illustré."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.prompts import JSON_RULE, stable_prefix
from llm.provider import LLMRequest

if TYPE_CHECKING:
    from agents.agent import Agent

MAX_PARAGRAPHS = 8


class Paragraph(BaseModel):
    text: str
    image: int | None = None      # numéro de la capture (1 = la première), ou rien


class ChronicleText(BaseModel):
    title: str
    paragraphs: list[Paragraph] = Field(default_factory=list)


def validate_chronicle(text: ChronicleText, images: int) -> ChronicleText:
    """Titre, 2 à 8 paragraphes ; chaque capture une seule fois, et seulement si elle existe."""
    title = text.title.strip()
    paragraphs = [p for p in text.paragraphs if p.text.strip()][:MAX_PARAGRAPHS]
    if not title or len(paragraphs) < 2:
        raise ValueError("chronique trop courte")
    used: set[int] = set()
    clean = []
    for p in paragraphs:
        image = p.image if p.image is not None and 1 <= p.image <= images and p.image not in used else None
        if image is not None:
            used.add(image)
        clean.append(Paragraph(text=p.text.strip()[:900], image=image))
    return ChronicleText(title=title[:90], paragraphs=clean)


def build_chronicle_request(family: list[Agent], week: str, events: list[str], captions: list[str],
                            max_tokens: int) -> LLMRequest:
    system = (
        "Tu es le chroniqueur d'une simulation de vie d'une famille québécoise. Chaque semaine, tu racontes la "
        "semaine de la famille comme une chronique de journal de quartier : vivante, tendre, drôle par moments, en "
        "français québécois, sans rien inventer qui contredise les faits. " + JSON_RULE
    )
    shots = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(captions)) or "(aucune)"
    prompt = (
        f"SEMAINE : {week}\n\n"
        "CE QUI S'EST PASSÉ (dans l'ordre)\n" + "\n".join(f"- {e}" for e in events) + "\n\n"
        f"CAPTURES D'ÉCRAN DE LA SEMAINE\n{shots}\n\n"
        "Écris un titre accrocheur et 3 à 6 paragraphes (60 à 120 mots chacun) qui racontent la semaine : les "
        "moments forts, ce que chacun a vécu, les liens entre les gens. Place chaque capture à côté du paragraphe "
        "qu'elle illustre (son numéro), chacune une seule fois.\n"
        'Format exact : {"title": "<titre>", "paragraphs": [{"text": "<paragraphe>", "image": 1}, '
        '{"text": "<paragraphe>", "image": null}]}'
    )
    meta = {"week": week, "events": events, "captions": captions}
    return LLMRequest(kind="chronicle", system=system, prompt=prompt, max_tokens=max(max_tokens, 1500), meta=meta,
                      prefix=stable_prefix(None, family))
