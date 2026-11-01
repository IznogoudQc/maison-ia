"""Scénario « terrain » : lot boisé, campement, scénario dans la config, sauvegarde du monde."""

import random
import time

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock, parse_hhmm
from sim.config import apply_scenario, load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House
from world.pathfinding import find_path
from world.terrain import build_house, camp_center, terrain_layout

DAY = 24 * 60


def terrain_config():
    config = load_config("config.yaml")
    config.world.scenario = "terrain"
    config.events.frequency = 0.0
    return apply_scenario(config)


@pytest.fixture
def setup():
    config = terrain_config()
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=4), 100_000, 2)
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    house = build_house("terrain", 120, 80, 42)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, house, agents, SimClock(5, "06:00"), random.Random(2), bus, llm)  # samedi
    engine.initialize()
    yield engine, events
    llm.shutdown()


def run_until(engine, minute):
    while engine.clock.total_minutes < minute:
        engine.tick()
        deadline = time.monotonic() + 1.0
        while (engine.pending_decisions or engine.pending_dialogues or engine.pending_summaries
               or engine.mind.busy() or engine.social.busy()) and time.monotonic() < deadline:
            engine.poll()
            time.sleep(0.0005)


def test_meme_graine_meme_foret():
    a, b = terrain_layout(seed=7), terrain_layout(seed=7)
    trees = lambda layout: sorted(o.id for o in layout.objects if o.kind == "arbre")  # noqa: E731
    assert trees(a) == trees(b) and len(trees(a)) > 500
    assert a.water == b.water and a.water
    assert trees(terrain_layout(seed=8)) != trees(a)


def test_campement_complet_et_accessible():
    house = House(terrain_layout(seed=42))
    cx, cy = camp_center(house.width, house.height)
    for obj_id in ("tente", "feu", "bancs_feu", "glaciere", "table_pique_nique", "baril", "porte"):
        obj = house.objects[obj_id]
        for spot in obj.use_positions:
            assert house.is_walkable(spot), (obj_id, spot)
            assert find_path((cx, cy + 2), spot, house.is_walkable) is not None, (obj_id, spot)
    for obj in house.purchase_objects.values():
        assert all(house.is_walkable(p) for p in obj.tiles + obj.use_positions), obj.id
    assert not house.objects_of_kind("tele") and house.layout.wild


def test_couper_un_arbre_libere_la_case_et_marque_le_monde():
    house = House(terrain_layout(seed=42))
    tree = next(o for o in house.objects.values() if o.kind == "arbre")
    pos = tree.rect[:2]
    assert not house.is_walkable(pos)
    revision = house.revision
    house.remove_object(tree.id)
    assert house.is_walkable(pos) and tree.id in house.removed
    assert house.revision == revision + 1 and pos in house.dirty


def test_scenario_terrain_dans_la_config():
    config = terrain_config()
    assert config.family_file == "data/couple.yaml"
    assert config.economy.start_money == 3000
    assert "Hypothèque" not in config.economy.weekly_bills
    personas = load_family(config.family_file)
    assert [p.name for p in personas] == ["Maxime", "Camille"]
    assert all(p.bed == "tente" and p.look for p in personas)


def test_premier_jour_au_campement(setup):
    engine, events = setup
    run_until(engine, 5 * DAY + parse_hhmm("21:00"))
    actions = {e.data["action"] for e in events if e.kind == "action"}
    assert {"souper", "cuisiner"} <= actions or {"souper", "bbq"} <= actions
    assert not any(e.data["action"] in ("tondre", "tele", "ordi") for e in events if e.kind == "action")
    assert "Achat" not in str([e for e in events if e.kind == "achat" and e.data["item"] == "piscine"])


def test_baril_lave_moins_bien_qu_une_douche(setup):
    engine, _ = setup
    camille = engine.agent_by_id("camille")
    camille.needs.hygiene = 10
    camille.action = None
    action = engine.make_action(camille, "douche")
    camille.pos = action.use_pos
    action.started = True
    camille.action = action
    for _ in range(action.remaining):
        engine._progress(camille, engine.clock.total_minutes)
    assert 10 + 70 * 0.55 - 3 < camille.needs.hygiene < 10 + 70 * 0.55 + 3


def test_on_ne_jase_pas_d_un_bout_a_l_autre_du_terrain(setup):
    engine, _ = setup
    maxime, camille = engine.agents
    maxime.pos, camille.pos = (10, 10), (100, 60)
    maxime.action = camille.action = None
    engine._detect_encounters()
    assert not engine.social.conversations and not engine.pending_dialogues


def test_sauvegarde_garde_les_arbres_coupes_et_refuse_un_autre_scenario(setup, tmp_path):
    engine, _ = setup
    trees = [o.id for o in engine.house.objects.values() if o.kind == "arbre"][:3]
    for tree_id in trees:
        engine.house.remove_object(tree_id)
    engine.save_state(tmp_path / "save.json")
    config = terrain_config()
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, build_house("terrain", 120, 80, 42), agents, SimClock(), random.Random(1), EventBus())
    other.load_state(tmp_path / "save.json")
    assert all(t not in other.house.objects for t in trees)
    maison_cfg = load_config("config.yaml")
    family = [Agent(persona=p, pos=(0, 0)) for p in load_family(maison_cfg.family_file)]
    maison = Engine(maison_cfg, House(), family, SimClock(), random.Random(1), EventBus())
    with pytest.raises(ValueError, match="terrain"):
        maison.load_state(tmp_path / "save.json")
