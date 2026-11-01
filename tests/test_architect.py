"""L'IA architecte : validation du plan, placement des pièces, défrichage, construction, sauvegarde."""

import random
import time

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.architect_prompts import HouseDesign, validate_design
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.building import build_room, place_rooms, trees_in
from world.house import House
from world.pathfinding import find_path
from world.terrain import build_house, camp_center

DAY = 24 * 60
SPECS = [
    {"id": "cuisine", "type": "cuisine", "name": "Cuisine", "width": 6, "height": 5},
    {"id": "sdb", "type": "salle_de_bain", "name": "Salle de bain", "width": 3, "height": 3,
     "anchor": "cuisine", "side": "ouest"},
    {"id": "chambre", "type": "chambre", "name": "Chambre", "width": 5, "height": 4, "anchor": "cuisine", "side": "est"},
    {"id": "salon", "type": "salon", "name": "Salon", "width": 7, "height": 5, "anchor": "cuisine", "side": "nord"},
]


def terrain():
    house = build_house("terrain", 120, 80, 42)
    cx, cy = camp_center(house.width, house.height)
    return house, (cx, cy - 7)


@pytest.fixture
def setup():
    config = load_config("config.yaml", scenario="terrain")
    config.events.frequency = 0.0
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=3), 100_000, 2)
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, build_house("terrain", 120, 80, 42), agents, SimClock(0, "06:00"),
                    random.Random(3), bus, llm)
    engine.initialize()
    yield engine, events
    llm.shutdown()


def run_until(engine, minute):
    while engine.clock.total_minutes < minute:
        engine.tick()
        deadline = time.monotonic() + 1.0
        while (engine.pending_decisions or engine.pending_dialogues or engine.pending_summaries
               or engine.mind.busy() or engine.social.busy() or engine.architect.busy()) \
                and time.monotonic() < deadline:
            engine.poll()
            time.sleep(0.0005)


# ---------------------------------------------------------------- plan et placement


def test_validation_borne_les_tailles_et_ecarte_l_inconnu():
    design = HouseDesign.model_validate({
        "vision": "Notre nid", "discussion": [{"speaker": "Maxime", "text": "Ça va être malade!"},
                                              {"speaker": "Inconnu", "text": "?"}],
        "rooms": [{"id": "Cuisine", "type": "cuisine", "width": 30, "height": 1},
                  {"id": "garage", "type": "garage", "width": 6, "height": 6},
                  {"id": "ch", "type": "Chambre", "width": 4, "height": 4, "anchor": "cuisine", "side": "East"},
                  {"id": "x", "type": "bureau", "width": 3, "height": 3, "anchor": "fantome"}]})
    valid = validate_design(design, {"maxime": "Maxime"})
    assert [(r.id, r.type, r.width, r.height) for r in valid.rooms] == [
        ("cuisine", "cuisine", 8, 4), ("ch", "chambre", 4, 4), ("x", "bureau", 3, 3)]
    assert valid.rooms[1].anchor == "cuisine" and valid.rooms[1].side == "est"
    assert valid.rooms[2].anchor is None  # ancre inconnue : collée à la précédente au placement
    assert [line.speaker for line in valid.discussion] == ["Maxime"]
    with pytest.raises(ValueError):
        validate_design(HouseDesign.model_validate({"rooms": [{"id": "g", "type": "garage", "width": 5,
                                                               "height": 5}]}), {})


def test_pieces_placees_sans_chevauchement_avec_portes():
    house, site = terrain()
    plan = place_rooms(house, SPECS, site, "Petit chalet")
    assert [r.id for r in plan.rooms] == ["cuisine", "sdb", "chambre", "salon"] and not plan.rejected
    rooms = plan.rooms
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            assert not set(a.interior_tiles()) & set(b.outer_tiles())
    assert len(plan.doors) == 3  # une par pièce collée
    cuisine = plan.room("cuisine")
    assert plan.front_door[1] == max(r.rect[3] for r in rooms) + 1  # mur sud, côté campement
    assert plan.room("salon").rect[3] == cuisine.rect[1] - 2  # au nord, mur commun


def test_piece_impossible_refusee_avec_raison():
    house, site = terrain()
    specs = SPECS[:1] + [{"id": "s2", "type": "salon", "name": "Salon géant", "width": 9, "height": 8,
                          "anchor": "cuisine", "side": "sud"}]
    plan = place_rooms(house, specs, site)
    salon = plan.room("s2")
    assert salon is None or salon.side != "sud"  # au sud, il y a la tente et le feu de camp
    if salon is None:
        assert plan.rejected and "Salon géant" in plan.rejected[0]


def test_construction_murs_portes_fenetres_et_meubles_accessibles():
    house, site = terrain()
    plan = place_rooms(house, SPECS, site)
    for room in plan.rooms:
        build_room(house, plan, room)
    cx, cy = camp_center(house.width, house.height)
    furniture = [o for o in house.objects.values() if o.id.startswith("maison_")]
    assert {o.kind for o in furniture} >= {"frigo", "cuisiniere", "table", "douche", "lit", "tele"}
    for obj in furniture:
        for spot in obj.use_positions:
            assert find_path((cx, cy + 2), spot, house.is_walkable) is not None, obj.id
    for room in plan.rooms:
        assert all(house.room_at(t) == room.name for t in room.interior_tiles())
        walls = [t for t in room.wall_tiles() if t not in plan.all_doors()]
        assert all(house.is_wall(t) for t in walls)
    inner = {t for r in plan.rooms for t in r.interior_tiles()}
    for x, y, vertical in house.windows:  # jamais sur un mur commun
        sides = [(x - 1, y), (x + 1, y)] if vertical else [(x, y - 1), (x, y + 1)]
        assert sum(p in inner for p in sides) == 1


# ---------------------------------------------------------------- dans le moteur


def test_le_couple_dessine_sa_maison_un_soir(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("18:59"))
    assert engine.architect.plan is None
    run_until(engine, parse_hhmm("19:30"))
    plan = engine.architect.plan
    assert plan is not None and plan.rooms and plan.vision
    assert any(e.kind == "plan_maison" for e in events)
    assert any(e.kind == "dialogue" and e.data.get("mode") == "scene" for e in events)  # la discussion
    memory = [m for m in engine.agents[0].memory.events if m.text.startswith("On a dessiné")]
    assert memory and memory[-1].importance == 8
    assert "Projet de maison" in engine.family_context(engine.agents)


def test_defrichage_prioritaire_puis_emplacement_pret(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("19:30"))
    room = engine.architect.clearing_room()
    if room is None:
        pytest.skip("aucun arbre sur le plan avec cette graine")
    run_until(engine, DAY + parse_hhmm("17:00"))
    maxime = engine.agent_by_id("maxime")
    maxime.action, maxime.away_until, maxime.away_label, maxime.away_kind = None, None, None, None
    trees = engine.architect.clearing_trees()
    if trees:
        option = next(o for o in engine.options_for(maxime) if o.action == "couper")
        assert option.target == "defrichage"
        action = engine.make_action(maxime, "couper", "defrichage")
        assert action.target in {t.id for t in trees} or action.target is not None
    for tree in engine.architect.clearing_trees():
        engine.house.remove_object(tree.id)
    engine.architect.update()
    assert room.status == "pret"
    assert any(e.kind == "emplacement_pret" for e in events)


def test_construction_instantanee_donne_un_toit_et_un_lit(setup):
    engine, events = setup
    engine.config.world.terrain.instant_build = True
    run_until(engine, parse_hhmm("19:30"))
    plan = engine.architect.plan
    for room in plan.rooms:
        for tree in trees_in(engine.house, room):
            engine.house.remove_object(tree.id)
    for _ in plan.rooms:
        engine.architect.update()
    assert all(r.status == "bati" for r in plan.rooms)
    assert engine.has_roof()
    beds = {a.bed_id for a in engine.agents}
    assert len(beds) == 1 and beds.pop().startswith("maison_")
    assert any(e.kind == "piece_batie" for e in events)


def test_sauvegarde_remonte_la_maison(setup, tmp_path):
    engine, _ = setup
    engine.config.world.terrain.instant_build = True
    run_until(engine, parse_hhmm("19:30"))
    plan = engine.architect.plan
    first = plan.rooms[0]
    for tree in trees_in(engine.house, first):
        engine.house.remove_object(tree.id)
    engine.architect.update()
    assert first.status == "bati"
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="terrain")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, build_house("terrain", 120, 80, 42), agents, SimClock(), random.Random(1), EventBus())
    other.load_state(tmp_path / "save.json")
    assert other.architect.plan.rooms[0].status == "bati"
    assert other.house.room_at(first.interior_tiles()[0]) == first.name
    assert any(o.id.startswith(f"maison_{first.id}_") for o in other.house.objects.values())


def test_pas_d_architecte_dans_la_maison_des_gagnon():
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(0, "19:10"), random.Random(1), EventBus())
    engine.initialize()
    engine.architect.update()
    assert not engine.architect.active and engine.architect.plan is None and not engine.architect.busy()
