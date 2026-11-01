"""Prompt de l'IA architecte : le couple dessine sa maison (pièces, tailles, ordre de construction)."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from llm.prompts import JSON_RULE, persona_block, relations_block
from llm.provider import LLMRequest
from world.building import MAX_ROOMS, ROOM_TYPES, SIDES, room_cost

if TYPE_CHECKING:
    from agents.agent import Agent

SIDE_ALIASES = {"north": "nord", "south": "sud", "east": "est", "west": "ouest", "n": "nord", "s": "sud",
                "e": "est", "o": "ouest", "w": "ouest"}
MAX_DISCUSSION = 4

# ---------------------------------------------------------------- schémas de réponse


class RoomRequest(BaseModel):
    id: str
    type: str
    name: str = ""
    width: int
    height: int
    anchor: str | None = None   # id d'une pièce plus haut dans la liste
    side: str | None = None     # nord, sud, est, ouest
    why: str = ""


class SpeechLine(BaseModel):
    speaker: str
    text: str


class HouseDesign(BaseModel):
    vision: str = ""
    discussion: list[SpeechLine] = Field(default_factory=list)
    rooms: list[RoomRequest] = Field(min_length=1)


# ---------------------------------------------------------------- validation métier


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")[:20] or "piece"


def validate_design(design: HouseDesign, names: dict[str, str], existing: set[str] | None = None) -> HouseDesign:
    """Types connus, tailles ramenées dans les bornes, ancrages valides ; ValueError si aucune pièce.

    names : id d'agent -> prénom (locuteurs de la discussion). existing : ids de pièces déjà prévues.
    """
    known = set(existing or set())
    rooms: list[RoomRequest] = []
    counts: dict[str, int] = {}
    for room in design.rooms:
        rtype = _slug(room.type)
        if rtype not in ROOM_TYPES:
            continue
        spec = ROOM_TYPES[rtype]
        width = max(spec.width[0], min(spec.width[1], room.width))
        height = max(spec.height[0], min(spec.height[1], room.height))
        room_id = _slug(room.id)
        while room_id in known:
            room_id += "_2"
        counts[rtype] = counts.get(rtype, 0) + 1
        name = room.name.strip()[:30] or (spec.label if counts[rtype] == 1 else f"{spec.label} {counts[rtype]}")
        anchor = _slug(room.anchor) if room.anchor else None
        if anchor not in known:
            anchor = None
        side = (room.side or "").strip().lower()
        side = SIDE_ALIASES.get(side, side)
        rooms.append(RoomRequest(id=room_id, type=rtype, name=name, width=width, height=height,
                                 anchor=anchor, side=side if side in SIDES else None, why=room.why.strip()[:120]))
        known.add(room_id)
        if len(rooms) + len(existing or ()) >= MAX_ROOMS:
            break
    if not rooms:
        raise ValueError("aucune pièce d'un type connu (cuisine, salle_de_bain, chambre, salon, bureau, atelier)")
    lookup = {n.lower(): n for n in names.values()} | {i.lower(): n for i, n in names.items()}
    discussion = [SpeechLine(speaker=lookup[line.speaker.strip().lower()], text=line.text.strip()[:200])
                  for line in design.discussion
                  if line.speaker.strip().lower() in lookup and line.text.strip()][:MAX_DISCUSSION]
    return HouseDesign(vision=design.vision.strip()[:160], discussion=discussion, rooms=rooms)


# ---------------------------------------------------------------- requête


def _money(amount: float) -> str:
    return f"{amount:,.0f} $".replace(",", " ")


def room_catalog() -> str:
    lines = []
    for key, spec in ROOM_TYPES.items():
        money, wood = room_cost(key, spec.width[0], spec.height[0])
        money_max, wood_max = room_cost(key, spec.width[1], spec.height[1])
        lines.append(f"- {key} : {spec.purpose} ; de {spec.width[0]}×{spec.height[0]} à {spec.width[1]}×{spec.height[1]} "
                     f"cases ; coût de {_money(money)} et {wood} bûches à {_money(money_max)} et {wood_max} bûches")
    return "\n".join(lines)


def build_design_request(couple: list[Agent], context: str, max_tokens: int,
                         existing: list[str] | None = None, reason: str | None = None) -> LLMRequest:
    system = (
        "Tu joues un couple québécois qui vit sous la tente sur son terrain boisé et dessine la maison qu'il va "
        "bâtir lui-même, pièce par pièce, au fil des paies et du bois coupé. Tu décides des pièces, de leur taille, "
        "de leur nombre et de l'ordre de construction selon leurs personnalités, leurs moyens et leurs projets. "
        "Un moteur de jeu place ensuite les pièces sur la grille : tu indiques seulement à côté de quelle pièce "
        "et de quel côté. " + JSON_RULE
    )
    people = "\n\n".join(f"### {a.name}\n{persona_block(a)}\nCe que {a.name} ressent :\n{relations_block(a, couple)}"
                         for a in couple)
    if existing:
        task = (f"RAISON : {reason or 'agrandir'}\nPièces déjà prévues ou bâties (ids) : {', '.join(existing)}.\n"
                "Ajoute 1 à 3 pièces, chacune collée à une pièce existante (anchor = son id).")
    else:
        task = (f"Dessinez votre maison : 3 à {MAX_ROOMS} pièces, dans l'ordre où vous les bâtirez (la plus urgente "
                "d'abord). La première est posée près du campement (anchor null) ; chaque autre est collée à une "
                "pièce plus haut dans la liste (anchor = son id, side = nord, sud, est ou ouest).")
    prompt = (
        f"LE COUPLE\n{people}\n\n"
        f"SITUATION\n{context}\n\n"
        f"TYPES DE PIÈCES (largeur × profondeur en cases ; 1 case ≈ 1 m)\n{room_catalog()}\n\n"
        f"{task}\n"
        "vision : la maison en une phrase. discussion : 2 à 4 répliques où le couple en discute (français "
        "québécois, 20 mots max chacune, avec leurs désaccords s'il y en a). why : pourquoi cette pièce, cette "
        "taille, ce rang.\n"
        'Format exact : {"vision": "<phrase>", "discussion": [{"speaker": "<prénom>", "text": "<réplique>"}], '
        '"rooms": [{"id": "cuisine", "type": "cuisine", "name": "<nom affiché>", "width": 6, "height": 5, '
        '"anchor": null, "side": null, "why": "<raison>"}]}'
    )
    meta = {"couple": [{"id": a.id, "name": a.name} for a in couple], "existing": existing or [],
            "reason": reason}
    return LLMRequest(kind="house_plan", system=system, prompt=prompt, max_tokens=max_tokens, meta=meta)
