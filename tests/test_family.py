"""Vie de famille : âge, désir d'enfant, grossesse, naissance, soins du bébé, grandir, sauvegarde."""

import random

import pytest

from agents.actions import ACTIONS, allowed_for
from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.family import _keeps_passage
from world.building import build_room, place_rooms, trees_in
from world.terrain import build_house

DAY = 24 * 60
SPECS = [{"id": "cuisine", "type": "cuisine", "name": "Cuisine", "width": 5, "height": 4},
         {"id": "chambre", "type": "chambre", "name": "Chambre", "width": 4, "height": 4,
          "anchor": "cuisine", "side": "est"}]


def make_engine(with_house: bool = True, carrier: bool = True):
    """Lundi 6 h, sans LLM (tout est déterministe) ; maison déjà bâtie si with_house."""
    config = load_config("config.yaml", scenario="terrain")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    house = build_house("terrain", 120, 80, 42)
    personas = load_family(config.family_file)
    if not carrier:
        for p in personas:
            p.can_be_pregnant = False
    agents = [Agent(persona=p, pos=(0, 0)) for p in personas]
    engine = Engine(config, house, agents, SimClock(0, "06:00"), random.Random(2), bus)
    engine.initialize()
    if with_house:
        plan = place_rooms(house, SPECS, engine.architect.site())
        engine.architect.plan = plan
        for room in plan.rooms:
            for tree in trees_in(house, room):
                house.remove_object(tree.id)
            engine.architect.build(room)
    engine.economy.household.money = 8000.0
    engine.economy.household.pantry = 200.0
    return engine, events


def run_until(engine, minute):
    while engine.clock.total_minutes < minute:
        engine.tick()


def couple_ready(engine):
    maxime, camille = engine.agent_by_id("maxime"), engine.agent_by_id("camille")
    maxime.relation("camille").affection = camille.relation("maxime").affection = 90
    engine.family.happiness = {"maxime": 80.0, "camille": 80.0}


# ---------------------------------------------------------------- étapes de vie


def test_etapes_de_vie_et_actions_par_etape():
    engine, _ = make_engine(with_house=False)
    camille = engine.agent_by_id("camille")
    assert camille.persona.stage == "adulte" and camille.persona.can_be_pregnant
    camille.persona.age = 6
    assert camille.persona.stage == "enfant"
    assert allowed_for(ACTIONS["jouer"], camille.persona.keys)       # les Lego : à tout enfant
    assert not allowed_for(ACTIONS["telephone"], camille.persona.keys)


def test_un_an_par_semaine_et_anniversaire_des_enfants(setup_baby):
    engine, events, baby = setup_baby
    adult_age = engine.agent_by_id("maxime").persona.age
    run_until(engine, engine.clock.total_minutes + 7 * DAY + 60)
    assert baby.persona.age == 1
    assert any(e.kind == "anniversaire" and e.data["name"] == baby.name for e in events)
    assert engine.agent_by_id("maxime").persona.age == adult_age + 1
    assert not any(e.kind == "anniversaire" and e.data["name"] == "Maxime" for e in events)


# ---------------------------------------------------------------- désir d'enfant et grossesse


def test_pas_de_bebe_sous_la_tente():
    engine, _ = make_engine(with_house=False)
    couple_ready(engine)
    ready, reason = engine.family.ready_for_baby()
    assert not ready and "tente" in reason


def test_discussion_puis_grossesse_de_la_bonne_personne():
    engine, events = make_engine()
    couple_ready(engine)
    assert engine.family.ready_for_baby() == (True, "")
    run_until(engine, parse_hhmm("19:45"))
    assert any(e.kind == "projet_bebe" and e.data["yes"] for e in events)
    assert engine.family.conceive_at is not None
    assert any(e.kind == "agrandissement" for e in events)  # une chambre pour le bébé au plan
    run_until(engine, engine.family.conceive_at + 1)
    assert engine.family.pregnancy.carrier == "camille"
    assert any(e.kind == "grossesse" and "Camille" in e.data["text"] for e in events)


def test_adoption_sans_fiche_qui_porte():
    engine, events = make_engine(carrier=False)
    couple_ready(engine)
    run_until(engine, parse_hhmm("19:45"))
    run_until(engine, engine.family.conceive_at + 1)
    assert engine.family.pregnancy.carrier is None
    assert any(e.kind == "grossesse" and "adoption" in e.data["text"] for e in events)


@pytest.fixture
def setup_baby():
    engine, events = make_engine()
    couple_ready(engine)
    run_until(engine, parse_hhmm("19:45"))
    run_until(engine, engine.family.conceive_at + 1)
    run_until(engine, engine.family.pregnancy.due + 1)
    baby = next(a for a in engine.agents if a.id.startswith("enfant_"))
    return engine, events, baby


def test_naissance_berceau_conge_parental(setup_baby):
    engine, events, baby = setup_baby
    camille = engine.agent_by_id("camille")
    assert baby.persona.stage == "bebe" and baby.persona.age == 0
    assert camille.away_label.startswith("hôpital") and baby.is_away
    crib = engine.house.objects[baby.bed]
    bed = engine.house.objects[camille.bed_id]
    assert crib.kind == "berceau"
    # Dans la chambre des parents s'il reste de la place (sinon tout près), toujours accessible
    from world.pathfinding import find_path
    assert find_path(bed.use_positions[0], crib.use_positions[0], engine.house.is_walkable) is not None
    assert camille.parental_leave_until is not None
    assert any(e.kind == "naissance" for e in events)
    memory = [m for m in camille.memory.events if baby.name in m.text and m.importance == 10]
    assert memory
    assert baby.id in camille.persona.relations


def test_bebe_reste_au_berceau_et_se_fait_soigner(setup_baby):
    engine, _, baby = setup_baby
    run_until(engine, engine.clock.total_minutes + 14 * 60)  # retour de l'hôpital
    assert not baby.is_away
    crib = engine.house.objects[baby.bed]
    assert baby.pos == crib.rect[:2] and not baby.is_available  # un bébé ne jase pas
    maxime = engine.agent_by_id("maxime")
    maxime.action, maxime.away_until = None, None
    for need in ("hunger", "energy", "hygiene", "social", "fun"):
        setattr(maxime.needs, need, 80.0)
    baby.action, baby.needs.hunger = None, 10
    care = next(o for o in engine.options_for(maxime) if o.action == "soigner")
    assert care.urgent and care.target == baby.id
    maxime.needs.hunger = 5  # parent affamé : il mange d'abord (sinon il tomberait avant le bébé)
    care = next(o for o in engine.options_for(maxime) if o.action == "soigner")
    assert not care.urgent


def test_soin_remonte_les_besoins_du_bebe(setup_baby):
    engine, _, baby = setup_baby
    run_until(engine, engine.clock.total_minutes + 14 * 60)
    maxime = engine.agent_by_id("maxime")
    maxime.action, maxime.away_until = None, None
    engine.agent_by_id("camille").action = None  # la place devant le berceau est libre
    baby.needs.hunger = 20
    action = engine.make_action(maxime, "soigner", baby.id)
    maxime.pos, action.started, maxime.action = action.use_pos, True, action
    for _ in range(action.remaining):
        engine._progress(maxime, engine.clock.total_minutes)
    assert baby.needs.hunger >= 60


def test_garderie_a_un_an_et_lit_a_trois_ans(setup_baby):
    engine, events, baby = setup_baby
    year = 7 * DAY
    run_until(engine, engine.clock.total_minutes + year + 2 * DAY)
    assert baby.persona.age == 1 and baby.persona.schedule.away.label == "garderie"
    assert any(e.kind == "depart" and e.data["name"] == baby.name and e.data["label"] == "garderie" for e in events)
    assert any(entry.label.startswith("Garderie") for entry in engine.economy.household.ledger)
    run_until(engine, engine.clock.total_minutes + 2 * year)
    assert baby.persona.stage == "enfant"
    assert not baby.bed_id.startswith("berceau_")


def test_prestations_rqap_pendant_le_conge(setup_baby):
    engine, _, _baby = setup_baby
    run_until(engine, engine.clock.total_minutes + 3 * DAY)
    assert any(entry.label.startswith("Prestations RQAP") for entry in engine.economy.household.ledger)


def test_sauvegarde_garde_les_enfants_et_les_ages(setup_baby, tmp_path):
    engine, _, baby = setup_baby
    run_until(engine, engine.clock.total_minutes + 8 * DAY)
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="terrain")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, build_house("terrain", 120, 80, 42), agents, SimClock(), random.Random(1), EventBus())
    other.load_state(tmp_path / "save.json")
    child = other.agent_by_id(baby.id)
    assert child is not None and child.persona.name == baby.name and child.persona.age == baby.persona.age
    assert other.agent_by_id("maxime").persona.age == engine.agent_by_id("maxime").persona.age
    assert child.bed in other.house.objects


# ---------------------------------------------------------------- passages (régressions)


def test_berceau_ne_coupe_jamais_un_passage():
    engine, _ = make_engine()
    house = engine.house
    room = engine.architect.plan.room("chambre")
    x0, y0, x1, y1 = room.rect
    corridor = (x0, y1)  # coin : poser un objet dans un coin ne coupe rien
    assert _keeps_passage(house, corridor)


def test_personne_ne_reste_dans_un_mur_apres_une_construction():
    engine, _ = make_engine(with_house=False)
    plan = place_rooms(engine.house, SPECS, engine.architect.site())
    engine.architect.plan = plan
    cuisine = plan.room("cuisine")
    for tree in trees_in(engine.house, cuisine):
        engine.house.remove_object(tree.id)
    maxime = engine.agent_by_id("maxime")
    wall = next(t for t in cuisine.wall_tiles() if t not in plan.all_doors())
    maxime.pos, maxime.away_until = wall, None
    engine.architect.build(cuisine)
    assert engine.house.is_walkable(maxime.pos)
