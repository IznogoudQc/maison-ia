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
UNUSED_DAYS = 14              # un objet dont personne ne s'est servi depuis ces jours-là peut être revendu
# Campement du terrain : revendu d'occasion quand la maison le remplace (id : nom, prix, raison)
CAMP_RESALE = {
    "tente": ("la tente", 80, "on dort tous dans un vrai lit"),
    "glaciere": ("la glacière", 30, "il y a un frigo dans la cuisine"),
    "baril": ("le baril d'eau de pluie", 20, "il y a une vraie douche"),
    "becosse": ("la bécosse", 60, "il y a une toilette dans la maison"),
    "table_pique_nique": ("la table de pique-nique", 50, "on mange à la vraie table"),
}
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
    recolte: str = ""
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
        options += self._used_sale_options(options)
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

    def rehouse(self) -> None:
        """Une place libre dans un vrai lit : qui dort sous la tente ou sur un matelas s'y installe.

        Les lits ne sont donnés qu'au moment de bâtir ou d'acheter ; ce tour du soir rattrape une place restée
        libre (lit acheté pour une autre personne, chambre bâtie quand le lit ne rentrait pas, vieille partie).
        """
        engine = self.engine
        objects = engine.house.objects
        beds = [o for o in objects.values() if o.kind == "lit" and o.id != "tente" and o.capacity > 0]
        if not beds:
            return
        living = [a for a in engine.agents if not a.dead]
        for agent in living:
            if agent.bed is not None and agent.bed not in objects:
                agent.bed = None  # lit disparu (revendu, pièce remeublée) : on lui trouve une autre place

        def comfort(agent: Agent) -> float:
            bed = objects.get(agent.bed_id)
            return -1.0 if agent.bed_id == "tente" or bed is None else bed.quality

        sleepers = sorted((a for a in living if a.persona.stage != "bebe" and comfort(a) < 0.85), key=comfort)
        for agent in sleepers:
            free = [b for b in beds if b.quality > comfort(agent)
                    and sum(1 for a in living if a.bed_id == b.id) < b.capacity]
            if not free:
                continue
            bed = max(free, key=lambda b: b.quality)
            was_tent = agent.bed_id == "tente"
            agent.bed = bed.id
            engine.remember(agent, "Fini la tente : ce soir, je dors dans un vrai lit !" if was_tent
                            else f"Je laisse le matelas pour un vrai lit : {bed.label.lower()}.", 6)

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

    def camp_obsolete(self, obj_id: str) -> bool:
        """L'objet du campement est remplacé par la maison : on peut s'en défaire."""
        engine = self.engine
        objects = engine.house.objects
        if obj_id == "tente":
            sleepers = [a for a in engine.agents if not a.dead and a.persona.stage != "bebe"]
            return all(a.bed not in (None, "tente") and a.bed in objects for a in sleepers)
        replacements = {"glaciere": lambda o: o.kind == "frigo" and o.id != "glaciere",
                        "baril": lambda o: o.kind == "douche" and o.id != "baril",
                        "becosse": lambda o: o.label.startswith("Toilette"),
                        "table_pique_nique": lambda o: o.kind == "table" and o.id != "table_pique_nique"}
        test = replacements.get(obj_id)
        return test is not None and any(test(o) for o in objects.values())

    def _used_sale_options(self, already: list[Option]) -> list[Option]:
        """Revendre d'occasion ce qui ne sert plus : le campement remplacé, un objet dont personne ne se sert."""
        engine = self.engine
        day = engine.clock.day
        if engine.economy.household.last_sale_day == day:
            return []
        offered = {o.target for o in already}
        options = []
        for obj_id, (name, value, why) in CAMP_RESALE.items():
            if obj_id in engine.house.objects and self.camp_obsolete(obj_id):
                options.append(Option(action="revendre", target=f"camp|{obj_id}",
                                      label=f"revend {name} d'occasion (+{value} $) : {why}", score=7.0))
        for owned in self.items:
            if str(owned.uid) in offered or owned.kind in ("lit", "deco") or owned.food or owned.hydro or owned.discount:
                continue  # un lit, une déco ou un objet qui fait économiser sert même sans qu'on y touche
            idle = day - max(owned.bought_day, owned.last_used_day)
            if owned.last_used_day >= 0 and idle >= UNUSED_DAYS:
                options.append(Option(action="revendre", target=str(owned.uid), score=5.0,
                                      label=f"revend {owned.label} (+{round(owned.price * RESALE)} $) : "
                                            f"personne ne s'en sert depuis {idle} jours"))
        return options[:2]

    def mark_used(self, use_pos) -> None:
        """Quelqu'un vient de se servir de l'objet à cette place : il n'est pas inutile."""
        obj = self.engine.house.object_at_spot(use_pos) if use_pos is not None else None
        if obj is None:
            return
        owned = next((o for o in self.items if o.object_id == obj.id), None)
        if owned is not None:
            owned.last_used_day = self.engine.clock.day

    def target_name(self, target: str | None) -> str | None:
        """Nom de ce qu'on revend (objet acheté, ou un objet du campement)."""
        if (target or "").startswith("camp|"):
            entry = CAMP_RESALE.get(target.split("|")[1])
            return f"{entry[0]} d'occasion" if entry else None
        owned = next((o for o in self.items if str(o.uid) == target), None)
        return owned.label if owned else None

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
                          bought_day=engine.clock.day, last_used_day=engine.clock.day,
                          food=item.effet.get("nourriture", 0.0), hydro=item.effet.get("hydro", 0.0),
                          discount=item.effet.get("epicerie", 0.0), price=item.prix, harvest=item.recolte)
        eco.household.next_item_uid += 1
        eco.household.last_item_day = engine.clock.day
        eco.household.items.append(owned)
        obj = self._place(owned)
        if item.type == "lit":
            self._assign_bed(obj, for_id, previous)
        if item.type == "chien":
            eco.household.dog_walk_day = engine.clock.day
        text = f"{agent.name} a acheté {item.label} ({item.prix:.0f} $)" + (f", l'ancien revendu {refund} $" if refund else "")
        engine.publish("achat_objet", agent=agent.id, item=item.id, room=room, amount=-item.prix, text=text)
        for other in engine.agents:
            if not other.dead and other.persona.stage != "bebe":
                engine.remember(other, text + ".", 4)

    def sell(self, agent: Agent, target: str | None) -> None:
        engine = self.engine
        household = engine.economy.household
        if (target or "").startswith("camp|"):
            self._sell_camp(agent, target.split("|")[1])
            return
        owned = next((o for o in self.items if str(o.uid) == target), None)
        if owned is None:
            return
        value = round(owned.price * RESALE)
        broke = household.money < 0
        self._remove(owned)
        household.last_sale_day = engine.clock.day
        engine.economy.transaction(engine.clock.total_minutes, f"Revente : {owned.label}", value)
        text = f"{agent.name} a revendu {owned.label} (+{value} $)"
        engine.publish("achat_objet", agent=agent.id, item=owned.item_id, room=owned.room, amount=value, text=text)
        engine.remember(agent, text + (" pour joindre les deux bouts." if broke else " : personne ne s'en servait."), 5)

    def _sell_camp(self, agent: Agent, obj_id: str) -> None:
        """Un objet du campement part d'occasion : la place se libère, l'argent rentre."""
        engine = self.engine
        entry = CAMP_RESALE.get(obj_id)
        if entry is None or obj_id not in engine.house.objects or not self.camp_obsolete(obj_id):
            return  # déjà vendu, ou de nouveau utile (décisions prises en même temps)
        name, value, why = entry
        engine.house.remove_object(obj_id)
        engine.economy.household.last_sale_day = engine.clock.day
        engine.economy.transaction(engine.clock.total_minutes, f"Revente : {name} d'occasion", value)
        text = f"{agent.name} a revendu {name} d'occasion (+{value} $)"
        engine.publish("achat_objet", agent=agent.id, item=obj_id, room="exterieur", amount=value, text=text)
        for other in engine.agents:
            if not other.dead and other.persona.stage != "bebe":
                engine.remember(other, f"{text} : {why}. Une page de tournée !", 5)

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
        for owned in self.items:
            if owned.food:  # le potager donne des légumes, les poules des œufs
                food_id = owned.harvest or ("oeufs" if owned.kind == "poulailler" else "legumes")
                engine.economy.add_food(food_id, owned.food, engine.clock.day)
        self._dog_check()
        spoiled = engine.economy.spoil(engine.clock.day)
        if spoiled:
            text = ", ".join(f"{name} ({portions:.0f})" for name, portions in spoiled)
            for agent in engine.agents:
                if agent.persona.is_adult and not agent.dead:
                    engine.remember(agent, f"Il a fallu jeter de la bouffe périmée : {text}.", 3)

    # ------------------------------------------------------------------ chien

    def has_dog(self) -> bool:
        return any(o.kind == "chien" for o in self.items)

    def dog_walked_today(self) -> bool:
        return self.engine.economy.household.dog_walk_day >= self.engine.clock.day

    def boost(self, agent: Agent, options: list[Option]) -> None:
        """Le chien n'est pas sorti aujourd'hui : la promenade devient pressante en après-midi."""
        if not self.has_dog() or self.dog_walked_today():
            return
        hour = self.engine.clock.minute_of_day // 60
        for option in options:
            if option.action == "promener":
                option.score = round(option.score + (14.0 if hour >= 15 else 6.0), 2)
                option.label = "promène le chien (il attend sa marche depuis ce matin)"

    def walked(self, agent: Agent) -> None:
        household = self.engine.economy.household
        first = household.dog_walk_day < self.engine.clock.day
        household.dog_walk_day = self.engine.clock.day
        if first:
            self.engine.remember(agent, "J'ai promené le chien, il était fou de joie.", 2)

    def _dog_check(self) -> None:
        """Chaque matin : si personne n'a sorti le chien hier, il a fait des dégâts."""
        engine = self.engine
        household = engine.economy.household
        if not self.has_dog() or household.dog_walk_day >= engine.clock.day - 1:
            return
        household.dog_walk_day = engine.clock.day - 1  # un seul dégât par oubli
        for agent in engine.agents:
            if not agent.dead and agent.persona.stage != "bebe":
                agent.needs.apply({"fun": -10})
                engine.remember(agent, "Personne n'a sorti le chien hier : il a fait un dégât dans la maison.", 4)

    def restore(self) -> None:
        """Après un chargement : les objets possédés reprennent leur place."""
        for owned in list(self.items):
            if owned.object_id not in self.engine.house.objects:
                self._place(owned)
            if owned.last_used_day < 0:
                owned.last_used_day = self.engine.clock.day  # vieille partie : on ne sait pas, on laisse un délai

    def context_line(self) -> str:
        if not self.items:
            return ""
        dog = ""
        if self.has_dog():
            dog = "Le chien a eu sa marche aujourd'hui. " if self.dog_walked_today() else "Le chien attend encore sa marche. "
        return dog + "Objets achetés : " + ", ".join(f"{o.label} ({'dehors' if o.room == 'exterieur' else o.room.lower()})"
                                               for o in self.items[-8:]) + "."

    def hud_lines(self) -> list[str]:
        weekly = sum(o.weekly - o.hydro for o in self.items)
        lines = [o.label.capitalize() for o in self.items[-6:]]
        if lines and weekly:
            lines.append(f"Frais : {weekly:+.0f} $/semaine")
        return lines
