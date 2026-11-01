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
    config = load_config("config.yaml", scenario="terrain")
    config.events.frequency = 0.0
    return config


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
    maison_cfg = load_config("config.yaml", scenario="maison")
    family = [Agent(persona=p, pos=(0, 0)) for p in load_family(maison_cfg.family_file)]
    maison = Engine(maison_cfg, House(), family, SimClock(), random.Random(1), EventBus())
    with pytest.raises(ValueError, match="terrain"):
        maison.load_state(tmp_path / "save.json")


# ---------------------------------------------------------------- C2 : tente, bois, veillées


def free(engine, agent):
    agent.action, agent.path = None, []
    agent.away_until = agent.away_label = agent.away_kind = None
    for need in ("hunger", "energy", "hygiene", "social", "fun"):
        setattr(agent.needs, need, 80.0)


def test_couper_propose_de_jour_quand_la_reserve_est_basse(setup):
    engine, _ = setup
    run_until(engine, 5 * DAY + parse_hhmm("10:00"))
    engine.architect.plan = None  # sans chantier : la réserve visée est celle du feu de camp
    maxime = engine.agent_by_id("maxime")
    engine.economy.household.wood = 0
    low = next(o for o in engine.options_for(maxime) if o.action == "couper")
    engine.economy.household.wood = 20
    high = next(o for o in engine.options_for(maxime) if o.action == "couper")
    assert low.score > high.score
    engine.economy.household.wood = 60
    assert not any(o.action == "couper" for o in engine.options_for(maxime))


def test_arbre_abattu_donne_des_buches_et_recule_la_lisiere(setup):
    engine, events = setup
    run_until(engine, 5 * DAY + parse_hhmm("10:00"))
    maxime = engine.agent_by_id("maxime")
    free(engine, maxime)
    engine.economy.household.wood = 0
    action = engine.make_action(maxime, "couper")
    tree = engine.house.objects[action.target]
    assert action.remaining == 60 or engine.economy.owns("scie")
    maxime.pos = action.use_pos
    action.started = True
    maxime.action = action
    for _ in range(action.remaining):
        engine._progress(maxime, engine.clock.total_minutes)
    assert action.target not in engine.house.objects
    assert engine.economy.household.wood == {"Érable": 6, "Sapin": 5, "Bouleau": 4}[tree.label]
    assert any(e.kind == "coupe" for e in events)
    x, y = tree.rect[:2]
    for nx, ny in ((x + 1, y), (x - 1, y), (x, y - 1)):
        neighbor = engine.house.objects.get(f"arbre_{nx}_{ny}")
        if neighbor is not None:
            assert (x, y) in neighbor.use_positions  # on l'atteint maintenant par la case libérée


def test_scie_a_chaine_coupe_plus_vite(setup):
    engine, _ = setup
    maxime = engine.agent_by_id("maxime")
    free(engine, maxime)
    by_hand = engine.make_action(maxime, "couper").remaining
    engine.economy.household.purchases.append("scie")
    assert engine.make_action(maxime, "couper").remaining < by_hand / 2


def test_veillee_le_soir_brule_une_buche(setup):
    engine, _ = setup
    run_until(engine, 5 * DAY + parse_hhmm("14:00"))
    camille = engine.agent_by_id("camille")
    free(engine, camille)
    engine.economy.household.wood = 3
    assert not any(o.action == "veiller" for o in engine.options_for(camille))  # pas en plein jour
    run_until(engine, 5 * DAY + parse_hhmm("20:00"))
    free(engine, camille)
    assert any(o.action == "veiller" for o in engine.options_for(camille))
    engine.economy.household.wood = 0
    assert not any(o.action == "veiller" for o in engine.options_for(camille))  # pas de bois, pas de feu
    engine.economy.household.wood = 3
    action = engine.make_action(camille, "veiller")
    camille.pos, camille.action = action.use_pos, action
    engine._progress(camille, engine.clock.total_minutes)
    assert action.started and engine.economy.household.wood == 2


def test_souper_froid_sans_bois(setup):
    engine, _ = setup
    camille = engine.agent_by_id("camille")
    free(engine, camille)
    engine.economy.household.wood = 0
    action = engine.make_action(camille, "cuisiner")
    camille.pos, camille.action = action.use_pos, action
    engine._progress(camille, engine.clock.total_minutes)
    assert camille.action is action  # on cuisine quand même...
    assert "souper froid" in camille.memory.events[-1].text  # ... mais c'est froid


def test_on_dort_moins_bien_sous_la_tente(setup):
    engine, _ = setup
    maxime = engine.agent_by_id("maxime")
    maxime.needs.energy = 20
    tent = engine.house.objects["tente"]
    action = engine.make_action(maxime, "dormir", forced=True, until=engine.clock.total_minutes + 120)
    maxime.pos, action.started, maxime.action = action.use_pos, True, action
    for _ in range(60):
        engine.clock.advance()
        engine._update_agent(maxime)
    assert tent.quality < 1
    assert maxime.needs.energy < 20 + 12 - 1  # moins que les 12 points/h d'un vrai lit


def test_la_maison_n_offre_ni_coupe_ni_scie():
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(5, "10:00"), random.Random(1), EventBus())
    engine.initialize()
    engine.economy.household.money = 50_000
    pere = engine.agent_by_id("pere")
    options = engine.options_for(pere)
    assert not any(o.action == "couper" for o in options)
    assert not any(o.action == "acheter" and o.target == "scie" for o in options)
