"""Le chantier : matériaux, séances de travail, bois posé, entrepreneur, pièce terminée."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.building import place_rooms, trees_in
from world.terrain import build_house

DAY = 24 * 60
SPECS = [{"id": "cuisine", "type": "cuisine", "name": "Cuisine", "width": 5, "height": 4},
         {"id": "chambre", "type": "chambre", "name": "Chambre", "width": 4, "height": 4,
          "anchor": "cuisine", "side": "est"}]


@pytest.fixture
def setup():
    """Samedi 9 h, plan déjà dessiné et emplacements dégagés (sans LLM : tout est déterministe)."""
    config = load_config("config.yaml", scenario="terrain")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    house = build_house("terrain", 120, 80, 42)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, house, agents, SimClock(5, "09:00"), random.Random(1), bus)
    engine.initialize()
    plan = place_rooms(house, SPECS, engine.architect.site())
    for room in plan.rooms:
        for tree in trees_in(house, room):
            house.remove_object(tree.id)
        room.status = "pret"
    engine.architect.plan = plan
    engine.economy.household.money = 6000.0
    engine.economy.household.wood = 100
    for agent in agents:
        agent.action, agent.path = None, []
        for need in ("hunger", "energy", "hygiene", "social", "fun"):
            setattr(agent.needs, need, 80.0)
    return engine, events


def session(engine, agent, room_id):
    """Une séance complète de construction (marche jusqu'au chantier comprise)."""
    action = engine.make_action(agent, "construire", room_id)
    assert action is not None
    agent.pos, agent.action = action.use_pos, action
    engine._progress(agent, engine.clock.total_minutes)  # arrivée : achat des matériaux si besoin
    while agent.action is action:
        engine._progress(agent, engine.clock.total_minutes)
    return action


def test_lancer_le_chantier_achete_les_materiaux(setup):
    engine, events = setup
    cuisine = engine.architect.plan.room("cuisine")
    camille = engine.agent_by_id("camille")
    options = [o for o in engine.options_for(camille) if o.action == "construire"]
    assert options and "lance le chantier" in options[0].label
    session(engine, camille, "cuisine")
    assert cuisine.status == "chantier" and cuisine.materials_paid
    assert engine.economy.household.money == pytest.approx(6000 - cuisine.materials_cost)
    assert any(e.kind == "chantier_debut" for e in events)
    assert cuisine.progress == pytest.approx(1.0)  # Camille : une heure ordinaire
    label = next(o for o in engine.options_for(camille) if o.action == "construire").label
    assert "travaille sur le chantier" in label


def test_pas_de_chantier_sans_les_moyens(setup):
    engine, _ = setup
    engine.economy.household.money = 300.0
    camille = engine.agent_by_id("camille")
    assert not any(o.action == "construire" for o in engine.options_for(camille))
    action = engine.make_action(camille, "construire", "cuisine")
    camille.pos, camille.action = action.use_pos, action
    engine._progress(camille, engine.clock.total_minutes)
    assert camille.action is None and not engine.architect.plan.room("cuisine").materials_paid


def test_le_charpentier_avance_plus_vite_et_le_bois_se_pose(setup):
    engine, _ = setup
    cuisine = engine.architect.plan.room("cuisine")
    maxime = engine.agent_by_id("maxime")
    session(engine, maxime, "cuisine")
    assert cuisine.progress == pytest.approx(1.5)
    per_hour = engine.architect.wood_per_hour(cuisine)
    assert cuisine.wood_used == per_hour and engine.economy.household.wood == 100 - per_hour


def test_sans_assez_de_bois_on_avance_moins(setup):
    engine, _ = setup
    cuisine = engine.architect.plan.room("cuisine")
    camille = engine.agent_by_id("camille")
    engine.economy.household.wood = 1
    session(engine, camille, "cuisine")
    assert 0 < cuisine.progress < 1.0 and engine.economy.household.wood == 0
    assert engine.architect.wood_missing() > 0
    assert "Manque" in engine.architect.hud_lines()[-1]


def test_piece_terminee_quand_heures_et_bois_y_sont(setup):
    engine, events = setup
    cuisine = engine.architect.plan.room("cuisine")
    maxime = engine.agent_by_id("maxime")
    sessions = 0
    while cuisine.status != "bati" and sessions < 60:
        session(engine, maxime, "cuisine")
        sessions += 1
    assert cuisine.status == "bati" and cuisine.wood_used == cuisine.wood_needed
    assert engine.house.room_at(cuisine.interior_tiles()[0]) == "Cuisine"
    assert any(e.kind == "piece_batie" for e in events)
    assert engine.architect.site_room().id == "chambre"


def test_entrepreneur_en_semaine_seulement(setup):
    engine, events = setup
    cuisine = engine.architect.plan.room("cuisine")
    camille = engine.agent_by_id("camille")
    engine.economy.household.money = 20_000.0
    assert any(o.action == "engager" for o in engine.options_for(camille))
    price, days = engine.architect.quote(cuisine)
    engine.architect.hire(camille, "cuisine")
    assert cuisine.contractor and cuisine.status == "chantier"
    assert engine.economy.household.money == pytest.approx(20_000 - price)
    assert not any(o.action in ("construire", "engager") for o in engine.options_for(camille))
    for _ in range(120):  # samedi : personne ne vient
        engine.clock.advance()
        engine.architect.update()
    assert cuisine.progress == 0
    engine.clock.total_minutes = 7 * DAY + parse_hhmm("08:00")  # lundi
    while cuisine.status != "bati" and engine.clock.total_minutes < 7 * DAY + days * DAY + DAY:
        engine.clock.advance()
        engine.architect.update()
    assert cuisine.status == "bati"
    assert any(e.kind == "entrepreneur" for e in events)


def test_le_chantier_releve_la_reserve_de_bois_visee(setup):
    engine, _ = setup
    camille = engine.agent_by_id("camille")
    session(engine, camille, "cuisine")
    engine.economy.household.wood = 60
    cuisine = engine.architect.plan.room("cuisine")
    if cuisine.wood_needed - cuisine.wood_used <= 60:
        engine.economy.household.wood = 5
    option = next((o for o in engine.options_for(camille) if o.action == "couper"), None)
    assert option is not None  # il manque du bois pour finir : on coupe même au-delà de 60 bûches
