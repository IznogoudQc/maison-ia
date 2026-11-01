"""Garage : catalogue de véhicules, achat, choix au départ, effets, ancienne « auto »."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.garage import load_vehicles
from world.house import House
from world.terrain import build_house


def make_engine(scenario="maison", day=0, time="06:00"):
    config = load_config("config.yaml", scenario=scenario)
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    house = House() if scenario == "maison" else build_house("terrain", 120, 80, 42)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, house, agents, SimClock(day, time), random.Random(3), bus)
    engine.initialize()
    engine.economy.household.money = 50_000.0
    return engine, events


def run_until(engine, minute):
    while engine.clock.total_minutes < minute:
        engine.tick()


def test_catalogue_des_vehicules():
    models = load_vehicles()
    assert {"velo", "moto", "compacte", "vus", "pickup", "vtt"} <= set(models)
    assert models["vus"].places > models["compacte"].places and models["pickup"].materiaux > 0


def test_achat_gare_le_vehicule_et_ajoute_les_frais():
    engine, events = make_engine()
    pere = engine.agent_by_id("pere")
    bills = engine.economy.weekly_bills()
    vehicle = engine.garage.buy(pere, "compacte")
    obj = engine.house.objects[vehicle.object_id]
    assert obj.kind == "vehicule" and engine.house.is_walkable(vehicle.uses[0])
    assert engine.economy.weekly_bills() == pytest.approx(bills + 55)
    assert engine.car_home() and any(e.kind == "achat_objet" for e in events)


def test_le_bon_vehicule_pour_la_bonne_course():
    engine, _ = make_engine()
    pere, felix = engine.agent_by_id("pere"), engine.agent_by_id("enfant")
    for model in ("moto", "compacte", "velo"):
        engine.garage.buy(pere, model)
        engine.economy.household.last_vehicle_day = -100
    assert engine.garage.best_for(pere, "travail").model == "moto"          # le plus rapide au travail
    assert engine.garage.best_for(pere, "epicerie").model == "compacte"     # la moto ne rapporte pas l'épicerie
    assert engine.garage.best_for(felix, "travail") is None                 # 8 ans : même pas le vélo


def test_depart_en_auto_retour_plus_tot():
    engine, events = make_engine()
    engine.garage.buy(engine.agent_by_id("pere"), "compacte")
    run_until(engine, parse_hhmm("09:00"))
    pere = engine.agent_by_id("pere")
    assert pere.drove and pere.vehicle is not None and not engine.car_home()
    run_until(engine, parse_hhmm("16:45") - 30 + 1)
    back = next(e for e in events if e.kind == "retour" and e.data["name"] == "Stéphane")
    assert back.minute == parse_hhmm("16:45") - 30 and pere.vehicle is None


def test_camionnette_rabais_et_buches():
    engine, _ = make_engine("terrain")
    maxime = engine.agent_by_id("maxime")
    engine.garage.buy(maxime, "pickup")
    assert engine.garage.materials_discount() == pytest.approx(0.15)
    tree = next(o for o in engine.house.objects.values() if o.kind == "arbre" and o.label == "Sapin")
    assert engine.fell_tree(tree.id) == 5 + 2


def test_suggestions_et_rythme_d_achat():
    engine, _ = make_engine(day=5, time="10:00")
    pere = engine.agent_by_id("pere")
    offered = {o.target for o in engine.garage.options_for(pere)}
    assert offered and "vtt" not in offered and "pickup" not in offered  # réservés au terrain
    engine.garage.buy(pere, "velo")
    assert not engine.garage.options_for(pere)  # un véhicule par semaine au plus


def test_ancienne_auto_devient_une_compacte():
    engine, _ = make_engine()
    engine.economy.household.purchases.append("auto")
    engine.garage.restore()
    assert "auto" not in engine.economy.household.purchases
    assert [v.model for v in engine.economy.household.vehicles] == ["compacte"]
    assert engine.economy.household.money == pytest.approx(50_000.0)  # rien à repayer
