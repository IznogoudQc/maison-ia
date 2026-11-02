"""Revente d'occasion : le campement remplacé par la maison, un objet dont personne ne se sert."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import EventBus
from world.building import place_rooms, trees_in
from world.house import House
from world.terrain import build_house


def terrain(rooms):
    config = load_config("config.yaml", scenario="terrain")
    config.events.frequency = 0.0
    house = build_house("terrain", 120, 80, 42)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, house, agents, SimClock(1, "10:00"), random.Random(1), EventBus())
    engine.initialize()
    engine.economy.household.money = 3000.0
    site = engine.architect.site()
    plan = place_rooms(house, rooms, site)
    for room in plan.rooms:
        for tree in trees_in(house, room):
            house.remove_object(tree.id)
    engine.architect.plan = plan
    return engine, plan, site


CHAMBRE = {"id": "chambre", "type": "chambre", "name": "Chambre", "width": 4, "height": 4}
CUISINE = {"id": "cuisine", "type": "cuisine", "name": "Cuisine", "width": 5, "height": 4,
           "anchor": "chambre", "side": "est"}


def test_la_tente_se_revend_quand_tout_le_monde_a_un_lit(tmp_path):
    engine, plan, site = terrain([CHAMBRE])
    inventory = engine.inventory
    assert not inventory.camp_obsolete("tente")                               # encore sous la tente
    engine.architect.build(plan.rooms[0])
    assert inventory.camp_obsolete("tente") and not inventory.camp_obsolete("glaciere")
    maxime = engine.agent_by_id("maxime")
    maxime.action = None
    option = next(o for o in engine.options_for(maxime) if o.target == "camp|tente")
    assert "la tente d'occasion (+80 $)" in option.label
    assert engine.make_action(maxime, "revendre", option.target) is not None
    money = engine.economy.household.money
    inventory.sell(maxime, "camp|tente")
    assert "tente" not in engine.house.objects and engine.economy.household.money == pytest.approx(money + 80)
    assert engine.architect.site() == site                                    # la maison reste au même endroit
    assert not any(o.target == "camp|tente" for o in engine.options_for(maxime))
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="terrain")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, build_house("terrain", 120, 80, 42), agents, SimClock(), random.Random(2), EventBus())
    other.load_state(tmp_path / "save.json")
    assert "tente" not in other.house.objects                                 # vendue pour de bon


def test_la_glaciere_quand_la_cuisine_a_un_frigo():
    engine, plan, _ = terrain([CHAMBRE, CUISINE])
    for room in plan.rooms:
        engine.architect.build(room)
    assert engine.inventory.camp_obsolete("glaciere") and engine.inventory.camp_obsolete("table_pique_nique")
    camille = engine.agent_by_id("camille")
    engine.inventory.sell(camille, "camp|glaciere")
    assert "glaciere" not in engine.house.objects
    assert engine.inventory._used_sale_options([]) == []                      # une seule revente par jour


def test_objet_que_personne_n_utilise():
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(30, "10:00"), random.Random(1), EventBus())
    engine.initialize()
    engine.economy.household.money = 20_000.0
    engine.economy.household.last_item_day = -1
    engine.inventory.buy(engine.agent_by_id("pere"), "piano|Salon|")
    piano = engine.economy.household.items[-1]
    assert not engine.inventory._used_sale_options([])
    piano.bought_day = piano.last_used_day = engine.clock.day - 20
    option = engine.inventory._used_sale_options([])[0]
    assert option.target == str(piano.uid) and "depuis 20 jours" in option.label
    engine.inventory.mark_used(engine.house.objects[piano.object_id].use_positions[0])
    assert not engine.inventory._used_sale_options([])                        # quelqu'un vient d'en jouer
