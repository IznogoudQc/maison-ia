"""Lits : un lit simple en repli dans une petite chambre, et les places libres reprises chaque soir."""

import dataclasses
import random

import world.building as building
from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from world.building import place_rooms, trees_in
from world.terrain import build_house


def terrain_with_bedroom(width=4, height=4):
    config = load_config("config.yaml", scenario="terrain")
    config.events.frequency = 0.0
    house = build_house("terrain", 120, 80, 42)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, house, agents, SimClock(1, "10:00"), random.Random(1))
    engine.initialize()
    plan = place_rooms(house, [{"id": "chambre", "type": "chambre", "name": "Chambre", "width": width,
                                "height": height}], engine.architect.site())
    for room in plan.rooms:
        for tree in trees_in(house, room):
            house.remove_object(tree.id)
    engine.architect.plan = plan
    return engine, plan.rooms[0]


def test_lit_simple_si_le_lit_double_ne_rentre_pas(monkeypatch):
    chambre = building.ROOM_TYPES["chambre"]
    big = dataclasses.replace(chambre.furniture[0], size=(9, 9))          # un lit double qui ne rentre jamais
    monkeypatch.setitem(building.ROOM_TYPES, "chambre",
                        dataclasses.replace(chambre, furniture=(big,) + chambre.furniture[1:]))
    engine, room = terrain_with_bedroom()
    engine.architect.build(room)
    beds = [o for o in engine.house.objects.values() if o.kind == "lit" and o.room == "Chambre"]
    assert beds and all(o.label.startswith("Lit simple") for o in beds)
    assert all(engine.house.objects[a.bed_id].room == "Chambre" for a in engine.agents[:len(beds)])


def test_place_libre_reprise_le_soir():
    engine, room = terrain_with_bedroom()
    engine.architect.build(room)
    for agent in engine.agents:
        agent.bed = None                                                     # tous retournés sous la tente
    assert all(a.bed_id == "tente" for a in engine.agents)
    engine.clock.total_minutes = engine.clock.day * 24 * 60 + 19 * 60 - 1
    engine.tick()
    bed = next(o for o in engine.house.objects.values() if o.kind == "lit" and o.room == "Chambre")
    assert [a.bed_id for a in engine.agents] == [bed.id] * min(bed.capacity, len(engine.agents))
    assert any("Fini la tente" in m.text for m in engine.agents[0].memory.events)


def test_rechargement_sans_meubles_superposes(tmp_path):
    from sim.economy import OwnedItem
    from sim.events import EventBus
    engine, room = terrain_with_bedroom()
    engine.architect.build(room)
    bed = next(o for o in engine.house.objects.values() if o.kind == "lit" and o.room == "Chambre")
    # Un matelas acheté à la place exacte du lit bâti (partie faite avec une autre version)
    engine.economy.household.items.append(OwnedItem(uid=1, item_id="matelas", label="un matelas", kind="lit",
                                                    room="Chambre", rect=bed.rect, uses=list(bed.use_positions),
                                                    quality=0.8, price=120))
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="terrain")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, build_house("terrain", 120, 80, 42), agents, SimClock(), random.Random(2), EventBus())
    other.load_state(tmp_path / "save.json")
    tiles = [t for o in other.house.objects.values() if o.room == "Chambre" for t in o.tiles]
    assert len(tiles) == len(set(tiles))                                       # rien l'un sur l'autre
    assert "objet_1" in other.house.objects


def test_lit_disparu_on_trouve_une_autre_place():
    engine, room = terrain_with_bedroom()
    engine.architect.build(room)
    maxime = engine.agent_by_id("maxime")
    maxime.bed = "objet_99"                                                    # n'existe plus
    engine.inventory.rehouse()
    assert maxime.bed in engine.house.objects
