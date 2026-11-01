"""Bibliothèque d'objets : la famille achète, place, remplace et revend des objets du catalogue.

Le catalogue (data/catalogue.yaml) donne prix, taille, activité permise, qualité et effets. Le moteur
propose quelques achats pertinents (un lit à qui dort sur un matelas, une gamme supérieure, un objet
utile pas encore possédé) ; l'IA choisit, avec la pièce. Le moteur trouve la place exacte
(world/building.py : place_in_room, place_outside) ; un objet sans place n'est pas acheté.
"""

from __future__ import annotations

import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

from agents.actions import Option
from sim.economy import OwnedItem
from world.building import place_in_room, place_outside
from world.house import InteractiveObject

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

CATALOGUE_FILE = Path("data/catalogue.yaml")
RESALE = 0.4                  # un objet revendu rapporte 40 % de son prix
MAX_SUGGESTIONS = 3
SHOP_HOURS = (8 * 60, 21 * 60)
# Pièces de la maison des Gagnon -> type de pièce du catalogue
MAISON_ROOMS = {"Chambre parents": "chambre", "Chambre ado": "chambre", "Chambre enfant": "chambre",
                "Cuisine": "cuisine", "Salle de bain": "salle_de_bain", "Salon": "salon"}


class CatalogItem(BaseModel):
    id: str
    label: str
    famille: str | None = None
    niveau: int = 1
    prix: float
    hebdo: float = 0.0
    taille: tuple[int, int] = (1, 1)
    type: str = "deco"
    qualite: float = 1.0
    places: int = 1
    lieu: list[str] = Field(default_factory=lambda: ["salon"])
    effet: dict[str, float] = Field(default_factory=dict)
    utilite: str = ""


def load_catalogue(path: Path = CATALOGUE_FILE) -> dict[str, CatalogItem]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {item.id: item for item in (CatalogItem.model_validate(raw) for raw in data.get("objets", []))}


class Inventory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.catalogue = load_catalogue()

    @property
    def items(self) -> list[OwnedItem]:
        return self.engine.economy.household.items

    # ------------------------------------------------------------------ pièces

    def room_types(self) -> dict[str, str]:
        """Pièces où l'on peut placer un objet : nom -> type (chambre, cuisine...) ; « exterieur » à part."""
        engine = self.engine
        if engine.house.layout.wild:
            plan = engine.architect.plan
            return {r.name: r.type for r in plan.built()} if plan else {}
        return {name: kind for name, kind in MAISON_ROOMS.items() if name in engine.house.rooms}

    def outside_center(self) -> tuple[int, int]:
        house = self.engine.house
        plan = self.engine.architect.plan
        if plan is not None and plan.front_door is not None and plan.built():
            x, y = plan.front_door
            return x + 4, y + 3
        if "Cour arrière" in house.rooms:
            x0, y0, x1, y1 = house.rooms["Cour arrière"]
            return (x0 + x1) // 2, (y0 + y1) // 2
        tent = house.objects.get("tente")
        return (tent.rect[0] + 6, tent.rect[1] + 2) if tent else (house.width // 2, house.height // 2)

    def find_spot(self, item: CatalogItem, room: str):
        house = self.engine.house
        deco = item.type == "deco"
        if room == "exterieur":
            return place_outside(house, item.taille, item.places, deco, self.outside_center())
        rect = house.rooms.get(room)
        return place_in_room(house, room, rect, item.taille, item.places, deco) if rect else None

    def _rooms_for(self, item: CatalogItem) -> list[str]:
        rooms = [name for name, kind in self.room_types().items() if kind in item.lieu]
        if "exterieur" in item.lieu and self.engine.economy.enabled:
            rooms.append("exterieur")
        return rooms

    # ------------------------------------------------------------------ suggestions

    def _budget(self) -> float:
        eco = self.engine.economy
        return eco.household.money - eco.reserve(self.engine.alive_count())

    def needs_bed(self) -> list[Agent]:
        """Personnes (pas les bébés) qui dorment sous la tente ou sur un matelas, alors qu'une chambre existe."""
        if "chambre" not in self.room_types().values():
            return []
        out = []
        for agent in self.engine.agents:
            if agent.dead or agent.persona.stage == "bebe":
                continue
            bed = self.engine.house.objects.get(agent.bed_id)
            if agent.bed_id == "tente" or (bed is not None and bed.quality < 0.85):
                out.append(agent)
        return out

    def options_for(self, agent: Agent) -> list[Option]:
        engine = self.engine
        minute = engine.clock.minute_of_day
        if not engine.economy.enabled or not agent.persona.is_adult or not SHOP_HOURS[0] <= minute < SHOP_HOURS[1]:
            return []
        if not self.catalogue:
            return []
        options = self._resale_options() if engine.economy.household.money < 0 else []
        budget = self._budget()
        suggestions: list[Option] = []
        for sleeper in self.needs_bed()[:1]:
            for item_id in ("lit_double", "lit_simple", "matelas"):
                item = self.catalogue.get(item_id)
                if item is None or item.prix > budget or (item_id == "lit_double" and sleeper.bed_id != "tente"):
                    continue
                room = self._bed_room(sleeper)
                if room and self.find_spot(item, room):
                    label = f"achète {item.label} pour {sleeper.name} ({item.prix:.0f} $, {room.lower()})"
                    suggestions.append(Option(action="acheter_objet", target=f"{item.id}|{room}|{sleeper.id}",
                                              label=label, score=14.0))
                    break
        day = engine.clock.day
        if engine.economy.household.last_item_day == day:
            return options + suggestions  # déjà un achat aujourd'hui : seulement un lit qui manque
        owned_ids = {o.item_id for o in self.items}
        pool = []
        for item in self.catalogue.values():
            if item.prix > budget or item.famille == "lit":
                continue
            if item.id in owned_ids:
                continue
            better_owned = item.famille and any(self.catalogue.get(o.item_id) and
                                                self.catalogue[o.item_id].famille == item.famille and
                                                self.catalogue[o.item_id].niveau >= item.niveau for o in self.items)
            if better_owned:
                continue
            rooms = self._rooms_for(item)
            if rooms:
                pool.append((item, rooms[(day + len(item.id)) % len(rooms)]))
        # Une sélection qui tourne chaque jour : l'IA voit des idées différentes sans liste interminable
        pool.sort(key=lambda p: zlib.crc32(f"{p[0].id}{day}".encode()))
        for item, room in pool[:MAX_SUGGESTIONS - len(suggestions)]:
            replaced = self._replaced_by(item)
            extra = f", remplace {replaced.label}" if replaced else ""
            where = "dehors" if room == "exterieur" else room.lower()
            weekly = f", {item.hebdo:+.0f} $/semaine" if item.hebdo else ""
            label = f"achète {item.label} ({item.prix:.0f} ${weekly}, {where}{extra}) : {item.utilite}"
            score = 6.0 + (3.0 if item.effet else 0.0)
            suggestions.append(Option(action="acheter_objet", target=f"{item.id}|{room}|", label=label, score=score))
        return options + suggestions

    def _bed_room(self, sleeper: Agent) -> str | None:
        """Chambre où mettre le lit : celle qui a le moins de lits."""
        house = self.engine.house
        rooms = [name for name, kind in self.room_types().items() if kind == "chambre"]
        if not rooms:
            return None
        return min(rooms, key=lambda r: sum(1 for o in house.objects.values() if o.kind == "lit" and o.room == r))

    def _replaced_by(self, item: CatalogItem) -> OwnedItem | None:
        if not item.famille:
            return None
        return next((o for o in self.items if self.catalogue.get(o.item_id) and
                     self.catalogue[o.item_id].famille == item.famille and
                     self.catalogue[o.item_id].niveau < item.niveau), None)

    def _resale_options(self) -> list[Option]:
        """Dans le rouge : revendre un objet qui n'est pas un lit."""
        options = []
        for owned in self.items:
            if owned.kind == "lit":
                continue
            value = round(owned.price * RESALE)
            options.append(Option(action="revendre", target=str(owned.uid),
                                  label=f"revend {owned.label} (+{value} $)", score=10.0))
        return options[:2]

    # ------------------------------------------------------------------ achat, revente

    def buy(self, agent: Agent, target: str | None) -> None:
        engine = self.engine
        item_id, room, for_id = ((target or "") + "||").split("|")[:3]
        item = self.catalogue.get(item_id)
        if item is None or not room:
            return
        eco = engine.economy
        if eco.household.money < item.prix:
            engine.remember(agent, f"Finalement, pas les moyens pour {item.label}.", 3)
            return
        already = any(o.item_id == item.id for o in self.items)
        if item.type != "lit" and (already or eco.household.last_item_day == engine.clock.day):
            return  # quelqu'un d'autre vient d'acheter (décisions prises en même temps)
        replaced = self._replaced_by(item)
        previous = [a for a in engine.agents if replaced is not None and a.bed == replaced.object_id]
        if replaced is not None:
            self._remove(replaced)
        spot = self.find_spot(item, room)
        if spot is None:
            if replaced is not None:
                self._place(replaced)  # pas de place : on garde l'ancien
                for sleeper in previous:
                    sleeper.bed = replaced.object_id
            engine.remember(agent, f"Pas de place pour {item.label} ({room.lower()}).", 3)
            return
        rect, uses = spot
        eco.transaction(engine.clock.total_minutes, f"Achat : {item.label}", -item.prix)
        refund = 0
        if replaced is not None:
            refund = round(replaced.price * RESALE)
            eco.transaction(engine.clock.total_minutes, f"Revente : {replaced.label}", refund)
        owned = OwnedItem(uid=eco.household.next_item_uid, item_id=item.id, label=item.label, kind=item.type,
                          room=room, rect=rect, uses=uses, quality=item.qualite, weekly=item.hebdo,
                          food=item.effet.get("nourriture", 0.0), hydro=item.effet.get("hydro", 0.0),
                          discount=item.effet.get("epicerie", 0.0), price=item.prix)
        eco.household.next_item_uid += 1
        eco.household.last_item_day = engine.clock.day
        eco.household.items.append(owned)
        obj = self._place(owned)
        if item.type == "lit":
            self._assign_bed(obj, for_id, previous)
        text = f"{agent.name} a acheté {item.label} ({item.prix:.0f} $)" + (f", l'ancien revendu {refund} $" if refund else "")
        engine.publish("achat_objet", agent=agent.id, item=item.id, room=room, amount=-item.prix, text=text)
        for other in engine.agents:
            if not other.dead and other.persona.stage != "bebe":
                engine.remember(other, text + ".", 4)

    def sell(self, agent: Agent, target: str | None) -> None:
        engine = self.engine
        owned = next((o for o in self.items if str(o.uid) == target), None)
        if owned is None:
            return
        value = round(owned.price * RESALE)
        self._remove(owned)
        engine.economy.transaction(engine.clock.total_minutes, f"Revente : {owned.label}", value)
        text = f"{agent.name} a revendu {owned.label} (+{value} $)"
        engine.publish("achat_objet", agent=agent.id, item=owned.item_id, room=owned.room, amount=value, text=text)
        engine.remember(agent, text + " pour joindre les deux bouts.", 5)

    def _place(self, owned: OwnedItem) -> InteractiveObject:
        if owned not in self.items:
            self.items.append(owned)
        obj = InteractiveObject(owned.object_id, owned.kind, owned.label.removeprefix("un ").removeprefix("une ")
                                .removeprefix("des ").capitalize(), owned.room, owned.rect, list(owned.uses),
                                owned.quality)
        self.engine.house.add_object(obj)
        return obj

    def _remove(self, owned: OwnedItem) -> None:
        self.engine.house.remove_object(owned.object_id)
        if owned in self.items:
            self.items.remove(owned)
        for agent in self.engine.agents:
            if agent.bed == owned.object_id:
                agent.bed = None

    def _assign_bed(self, bed: InteractiveObject, for_id: str, previous: list[Agent]) -> None:
        """Ceux qui dormaient dans le lit remplacé, puis la personne visée, puis qui dort sur un matelas."""
        engine = self.engine
        sleepers = list(previous)
        target = engine.agent_by_id(for_id) if for_id else None
        if target is not None:
            sleepers = [target] + [a for a in sleepers if a is not target]
        sleepers += [a for a in self.needs_bed() if a not in sleepers]
        for agent in sleepers[:bed.capacity]:
            old = engine.house.objects.get(agent.bed or "")
            agent.bed = bed.id
            if old is not None and old.id.startswith("matelas_"):
                engine.house.remove_object(old.id)
            engine.remember(agent, f"J'ai un nouveau lit : {bed.label.lower()} !", 5)

    # ------------------------------------------------------------------ effets, prompts, sauvegarde

    def update(self) -> None:
        """Chaque matin : le potager et les poules donnent de la nourriture."""
        engine = self.engine
        household = engine.economy.household
        if engine.clock.minute_of_day < 7 * 60 or household.last_harvest_day == engine.clock.day:
            return
        household.last_harvest_day = engine.clock.day
        food = sum(o.food for o in self.items)
        if food:
            household.pantry = round(household.pantry + food, 2)

    def restore(self) -> None:
        """Après un chargement : les objets possédés reprennent leur place."""
        for owned in list(self.items):
            if owned.object_id not in self.engine.house.objects:
                self._place(owned)

    def context_line(self) -> str:
        if not self.items:
            return ""
        return "Objets achetés : " + ", ".join(f"{o.label} ({'dehors' if o.room == 'exterieur' else o.room.lower()})"
                                               for o in self.items[-8:]) + "."

    def hud_lines(self) -> list[str]:
        weekly = sum(o.weekly - o.hydro for o in self.items)
        lines = [o.label.capitalize() for o in self.items[-6:]]
        if lines and weekly:
            lines.append(f"Frais : {weekly:+.0f} $/semaine")
        return lines
