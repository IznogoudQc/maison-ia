"""Garage : vélos, moto, autos, VUS, camionnette, VTT (section « vehicules » de data/catalogue.yaml).

Chaque véhicule acheté est garé près de l'entrée (place trouvée par le moteur). Au départ, chacun
prend le véhicule libre le plus utile pour où il va (le travail, l'épicerie) ; un véhicule ne sert
qu'à une personne à la fois. Effets : retour du travail plus tôt, épicerie plus rapide et moins chère,
moral, bûches de plus par arbre, rabais sur les matériaux du chantier.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel

from agents.actions import Option
from sim.economy import OwnedVehicle
from world.building import place_outside
from world.house import InteractiveObject

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

CATALOGUE_FILE = Path("data/catalogue.yaml")
MAX_VEHICLES = 3
DAYS_BETWEEN_VEHICLES = 7
MAX_SUGGESTIONS = 2


class VehicleModel(BaseModel):
    id: str
    label: str
    prix: float
    hebdo: float = 0.0
    taille: tuple[int, int] = (2, 3)
    places: int = 1
    trajet: int = 0
    epicerie: bool = False
    epicerie_minutes: int = 60
    plaisir: float = 0.0
    bois: int = 0
    materiaux: float = 0.0
    age_min: int = 18
    terrain: bool = False
    utilite: str = ""


def load_vehicles(path: Path = CATALOGUE_FILE) -> dict[str, VehicleModel]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {v.id: v for v in (VehicleModel.model_validate(raw) for raw in data.get("vehicules", []))}


class Garage:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.models = load_vehicles()

    @property
    def owned(self) -> list[OwnedVehicle]:
        return self.engine.economy.household.vehicles

    def model(self, vehicle: OwnedVehicle) -> VehicleModel:
        return self.models.get(vehicle.model) or VehicleModel(id=vehicle.model, label=vehicle.label, prix=0)

    def in_use(self) -> set[str]:
        return {a.vehicle for a in self.engine.agents if a.vehicle}

    def at_home(self) -> list[OwnedVehicle]:
        busy = self.in_use()
        return [v for v in self.owned if v.object_id not in busy and v.object_id in self.engine.house.objects]

    def get(self, object_id: str | None) -> OwnedVehicle | None:
        return next((v for v in self.owned if v.object_id == object_id), None)

    def best_for(self, agent: Agent, purpose: str) -> OwnedVehicle | None:
        """Véhicule libre le plus utile : pour l'épicerie, il doit pouvoir la rapporter."""
        candidates = []
        for vehicle in self.at_home():
            model = self.model(vehicle)
            if agent.persona.age < model.age_min:
                continue
            if purpose == "epicerie" and not model.epicerie:
                continue
            if purpose != "epicerie" and model.trajet <= 0:
                continue  # le VTT ne va pas au travail
            candidates.append((vehicle, model))
        if not candidates:
            return None
        if purpose == "epicerie":
            return min(candidates, key=lambda c: c[1].epicerie_minutes)[0]
        return max(candidates, key=lambda c: (c[1].trajet, c[1].plaisir))[0]

    # ------------------------------------------------------------------ effets

    def wood_bonus(self) -> int:
        return max((self.model(v).bois for v in self.owned), default=0)

    def materials_discount(self) -> float:
        return max((self.model(v).materiaux for v in self.owned), default=0.0)

    def has_motor(self) -> bool:
        return any(self.model(v).id != "velo" for v in self.owned)

    # ------------------------------------------------------------------ achats

    def _anchor(self) -> tuple[int, int]:
        house = self.engine.house
        spot = house.purchase_objects.get("auto")
        if spot is not None:
            x, y, w, h = spot.rect
            return x, y + h // 2
        return house.width // 2, house.height - 4

    def options_for(self, agent: Agent) -> list[Option]:
        engine = self.engine
        household = engine.economy.household
        if not engine.economy.enabled or not agent.persona.is_adult or len(self.owned) >= MAX_VEHICLES:
            return []
        if engine.clock.day - household.last_vehicle_day < DAYS_BETWEEN_VEHICLES:
            return []
        budget = household.money - engine.economy.reserve(engine.alive_count())
        owned = {v.model for v in self.owned}
        wanted: list[tuple[VehicleModel, float]] = []
        motor = [self.model(v) for v in self.owned if self.model(v).epicerie]
        people = sum(1 for a in engine.agents if not a.dead)
        for model in self.models.values():
            if model.id in owned or model.prix > budget or (model.terrain and not engine.house.layout.wild):
                continue
            score = 5.0
            if model.epicerie and not motor:
                score = 9.0  # pas encore d'auto : épicerie et retours plus faciles
            if model.places >= 5 and motor and people > max(m.places for m in motor):
                score = 12.0  # la famille ne rentre plus dans l'auto
            if model.materiaux and engine.architect.site_room() is not None:
                score = 8.0
            if model.id == "velo" and not self.owned:
                score = 7.0
            wanted.append((model, score))
        wanted.sort(key=lambda m: -m[1])
        options = []
        for model, score in wanted[:MAX_SUGGESTIONS]:
            weekly = f", {model.hebdo:.0f} $/semaine" if model.hebdo else ""
            label = f"achète {model.label} ({model.prix:,.0f} ${weekly}) : {model.utilite}".replace(",", " ", 1)
            options.append(Option(action="acheter_vehicule", target=model.id, label=label, score=score))
        return options

    def buy(self, agent: Agent, model_id: str | None, free: bool = False) -> OwnedVehicle | None:
        engine = self.engine
        model = self.models.get(model_id or "")
        household = engine.economy.household
        if model is None or len(self.owned) >= MAX_VEHICLES:
            return None
        recent = engine.clock.day - household.last_vehicle_day < DAYS_BETWEEN_VEHICLES
        if not free and (recent or any(v.model == model.id for v in self.owned)):
            return None  # l'autre parent vient d'en acheter un
        if not free and household.money < model.prix:
            engine.remember(agent, f"Finalement, pas les moyens pour {model.label}.", 3)
            return None
        spot = place_outside(engine.house, model.taille, 1, False, self._anchor(), allow_surface=True)
        if spot is None:
            engine.remember(agent, f"Pas de place pour stationner {model.label}.", 3)
            return None
        rect, uses = spot
        vehicle = OwnedVehicle(uid=household.next_item_uid, model=model.id, label=model.label, rect=rect,
                               uses=uses, price=model.prix, weekly=model.hebdo)
        household.next_item_uid += 1
        household.vehicles.append(vehicle)
        self._park(vehicle)
        if not free:
            household.last_vehicle_day = engine.clock.day
            engine.economy.transaction(engine.clock.total_minutes, f"Achat : {model.label}", -model.prix)
            text = f"{agent.name} a acheté {model.label} ({model.prix:,.0f} $)".replace(",", " ")
            engine.publish("achat_objet", agent=agent.id, item=model.id, room="entrée", amount=-model.prix, text=text)
            for other in engine.agents:
                if not other.dead and other.persona.stage != "bebe":
                    engine.remember(other, text + " !", 6)
        return vehicle

    def _park(self, vehicle: OwnedVehicle) -> None:
        obj = InteractiveObject(vehicle.object_id, "vehicule", vehicle.label.split(" ", 1)[-1].capitalize(),
                                self.engine.house.room_at(vehicle.rect[:2]) or "Dehors", vehicle.rect,
                                list(vehicle.uses))
        self.engine.house.add_object(obj)

    # ------------------------------------------------------------------ sauvegarde, prompts

    def restore(self) -> None:
        """Après un chargement : véhicules garés ; une ancienne « auto » devient une auto compacte."""
        engine = self.engine
        household = engine.economy.household
        if "auto" in household.purchases:
            household.purchases.remove("auto")
            engine.house.remove_object("auto")
            driver = next((a for a in engine.agents if a.persona.is_adult), None)
            if driver is not None:
                self.buy(driver, "compacte", free=True)
        for vehicle in self.owned:
            if vehicle.object_id not in engine.house.objects:
                self._park(vehicle)

    def context_line(self) -> str:
        if not self.owned:
            return ""
        return "Véhicules : " + ", ".join(v.label for v in self.owned) + "."

    def hud_lines(self) -> list[str]:
        busy = self.in_use()
        return [f"{v.label.capitalize()}{' (parti)' if v.object_id in busy else ''}" for v in self.owned]
