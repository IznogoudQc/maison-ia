"""Événements selon le scénario et la situation, et récit des événements par le LLM."""

import random
import time
from concurrent.futures import Future

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.prompts import EventStory, validate_story
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.random_events import EVENTS, SURPRISE_BILLS, RandomEvents
from world.building import place_rooms, trees_in
from world.house import House
from world.terrain import build_house

DAY = 24 * 60
EVENT = {e.id: e for e in EVENTS}


def terrain_engine(llm=None):
    config = load_config("config.yaml", scenario="terrain")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, build_house("terrain", 120, 80, 42), agents, SimClock(0, "09:00"),
                    random.Random(4), bus, llm)
    engine.initialize()
    return engine, events


def with_site(engine):
    """Plan dessiné, cuisine en chantier (matériaux payés, 5 heures faites)."""
    plan = place_rooms(engine.house, [{"id": "cuisine", "type": "cuisine", "name": "Cuisine",
                                       "width": 5, "height": 4}], engine.architect.site())
    room = plan.rooms[0]
    for tree in trees_in(engine.house, room):
        engine.house.remove_object(tree.id)
    room.status, room.materials_paid, room.progress = "chantier", True, 5.0
    engine.architect.plan = plan
    return room


def ids(engine):
    return {e.id for e in RandomEvents.possible(engine)}


# ---------------------------------------------------------------- filtres


def test_les_evenements_suivent_le_scenario():
    maison_cfg = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(maison_cfg.family_file)]
    maison = Engine(maison_cfg, House(), agents, SimClock(), random.Random(1), EventBus())
    assert not ids(maison) & {"orage", "ratons", "vol_chantier", "arbre_tombe"}
    assert "gardiennage" in ids(maison)  # Léa a 15 ans
    terrain, _ = terrain_engine()
    possible = ids(terrain)
    assert {"orage", "ratons", "arbre_tombe", "belle_journee", "facture_imprevue"} <= possible
    assert not possible & {"gardiennage", "vol_chantier", "corvee", "inspecteur", "bebe_malade"}


def test_le_chantier_ouvre_ses_evenements(setup_site):
    engine, room = setup_site
    assert {"vol_chantier", "corvee", "inspecteur"} <= ids(engine)
    engine.economy.household.building_permit = True
    assert "inspecteur" not in ids(engine)


@pytest.fixture
def setup_site():
    engine, _ = terrain_engine()
    return engine, with_site(engine)


def test_factures_du_terrain_sans_les_gagnon():
    assert not any("Félix" in label for label, _ in SURPRISE_BILLS["terrain"])


# ---------------------------------------------------------------- effets


def test_orage_sous_la_tente_puis_sur_le_chantier(setup_site):
    engine, room = setup_site
    rng = random.Random(1)
    maxime = engine.agent_by_id("maxime")
    maxime.needs.energy = 60
    text = EVENT["orage"].apply(engine, rng)
    assert "tente" in text and maxime.needs.energy == pytest.approx(45)
    engine.house.add_room("Abri", (5, 5, 6, 6), [], [])  # un toit quelque part
    text = EVENT["orage"].apply(engine, rng)
    assert "bâche" in text and room.progress == pytest.approx(2.0)


def test_arbre_tombe_donne_des_buches():
    engine, _ = terrain_engine()
    trees = len(engine.house.objects_of_kind("arbre"))
    text = EVENT["arbre_tombe"].apply(engine, random.Random(2))
    assert "bûches gratuites" in text
    assert len(engine.house.objects_of_kind("arbre")) == trees - 1 and engine.economy.household.wood >= 4


def test_ratons_vente_de_bois_vol_et_corvee(setup_site):
    engine, room = setup_site
    rng = random.Random(3)
    household = engine.economy.household
    household.pantry, household.wood, household.money = 20.0, 60, 3000.0
    EVENT["ratons"].apply(engine, rng)
    assert household.pantry == pytest.approx(14.0)
    EVENT["vente_bois"].apply(engine, rng)
    assert household.wood == 45 and household.money == pytest.approx(3105.0)
    EVENT["vol_chantier"].apply(engine, rng)
    assert household.money == pytest.approx(3105.0 - round(room.materials_cost * 0.15, -1))
    EVENT["corvee"].apply(engine, rng)
    assert room.progress == pytest.approx(9.0)


def test_inspecteur_une_seule_fois(setup_site):
    engine, _ = setup_site
    money = engine.economy.household.money
    assert "permis" in EVENT["inspecteur"].apply(engine, random.Random(1))
    assert EVENT["inspecteur"].apply(engine, random.Random(1)) is None
    assert engine.economy.household.money == pytest.approx(money - 250)


# ---------------------------------------------------------------- récit par le LLM


def test_le_recit_garde_les_chiffres():
    base = "Le voisin achète 15 bûches pour son poêle : +105 $."
    assert validate_story(EventStory(text="Bonne affaire : 15 bûches vendues au voisin, 105 $ dans le pot !"), base)
    with pytest.raises(ValueError):
        validate_story(EventStory(text="Le voisin achète du bois pour une bouchée de pain."), base)


def test_l_evenement_parait_raconte(monkeypatch):
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 100_000, 2)
    engine, events = terrain_engine(llm)
    engine.config.events.frequency = 1.0
    monkeypatch.setattr("sim.random_events.EVENTS", [EVENT["belle_journee"].__class__(
        "belle_journee", 1.0, True, EVENT["belle_journee"].apply)])
    engine._roll_events()
    assert engine.pending_stories
    engine.pending_stories[0][2].result(timeout=5)
    engine.poll()
    news = [e for e in events if e.kind == "evenement"]
    assert news and "magnifique journée" in news[0].data["text"] and news[0].data["text"] != \
        "Une magnifique journée d'été : tout le monde est de bonne humeur."
    llm.shutdown()


def test_recit_trop_lent_on_publie_le_texte_fixe():
    engine, events = terrain_engine()
    never: Future = Future()
    engine.pending_stories.append((EVENT["belle_journee"], "Texte fixe 42.", never, time.monotonic() - 11))
    engine.poll()
    assert any(e.kind == "evenement" and e.data["text"] == "Texte fixe 42." for e in events)
    assert not engine.pending_stories
