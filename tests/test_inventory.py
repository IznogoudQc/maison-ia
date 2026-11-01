"""Bibliothèque d'objets : catalogue, placement, achat, remplacement, revente, effets, sauvegarde."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.inventory import load_catalogue
from world.house import House
from world.pathfinding import find_path


@pytest.fixture
def setup():
    """Maison des Gagnon, samedi 10 h, compte bien garni."""
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(5, "10:00"), random.Random(1), bus)
    engine.initialize()
    engine.economy.household.money = 20_000.0
    return engine, events


def test_catalogue_charge_et_coherent():
    catalogue = load_catalogue()
    assert {"lit_simple", "potager", "console", "panneaux_solaires"} <= set(catalogue)
    beds = sorted((i for i in catalogue.values() if i.famille == "lit"), key=lambda i: i.niveau)
    assert [b.prix for b in beds] == sorted(b.prix for b in beds)  # plus haut de gamme = plus cher


def test_achat_place_l_objet_et_ouvre_l_activite(setup):
    engine, events = setup
    pere = engine.agent_by_id("pere")
    assert not any(o.action == "console" for o in engine.options_for(pere))
    engine.inventory.buy(pere, "console|Salon|")
    owned = engine.economy.household.items[-1]
    obj = engine.house.objects[owned.object_id]
    assert engine.economy.household.money == pytest.approx(19_500.0)
    assert obj.kind == "console" and engine.house.room_at(obj.rect[:2]) == "Salon"
    for spot in obj.use_positions:
        assert find_path((5, 15), spot, engine.house.is_walkable) is not None
    pere.action = None
    assert any(o.action == "console" for o in engine.options_for(pere))
    assert any(e.kind == "achat_objet" for e in events)


def test_tout_reste_accessible_apres_plusieurs_achats(setup):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    for target in ("bibliotheque|Salon|", "piano|Salon|", "console|Salon|", "ordinateur|Salon|"):
        engine.inventory.buy(pere, target)
    for obj in engine.house.objects.values():
        for spot in obj.use_positions:
            assert find_path((5, 15), spot, engine.house.is_walkable) is not None, obj.id


def test_gamme_superieure_remplace_et_revend(setup):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    engine.inventory.buy(pere, "canape_usage|Salon|")
    engine.inventory.buy(pere, "canape_cuir|Salon|")
    items = [o.item_id for o in engine.economy.household.items]
    assert items == ["canape_cuir"]
    assert any(e.label.startswith("Revente : un divan") and e.amount == 80 for e in engine.economy.household.ledger)


def test_dans_le_rouge_on_peut_revendre(setup):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    engine.inventory.buy(pere, "piano|Salon|")
    engine.economy.household.money = -200.0
    pere.action = None
    sale = next(o for o in engine.options_for(pere) if o.action == "revendre")
    engine.inventory.sell(pere, sale.target)
    assert not engine.economy.household.items
    assert engine.economy.household.money == pytest.approx(-200 + 1200)


def test_effets_potager_solaire_congelateur(setup):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    bills = engine.economy.weekly_bills()
    for target in ("potager|exterieur|", "panneaux_solaires|exterieur|", "congelateur|Cuisine|"):
        engine.inventory.buy(pere, target)
    assert engine.economy.weekly_bills() == pytest.approx(bills - 30 + 4)  # solaire -30, congélateur +4
    pantry = engine.economy.household.pantry
    engine.economy.household.last_harvest_day = -1
    engine.inventory.update()
    assert engine.economy.household.pantry == pytest.approx(pantry + 2)
    assert engine.economy.grocery_discount() == pytest.approx(0.08)


def test_un_achat_par_jour(setup):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    pere.action = None
    assert any(o.action == "acheter_objet" for o in engine.options_for(pere))
    engine.inventory.buy(pere, "hamac|exterieur|")
    assert not any(o.action == "acheter_objet" for o in engine.options_for(pere))


def test_sauvegarde_replace_les_objets(setup, tmp_path):
    engine, _ = setup
    engine.inventory.buy(engine.agent_by_id("pere"), "trampoline|exterieur|")
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, House(), agents, SimClock(), random.Random(1), EventBus())
    other.load_state(tmp_path / "save.json")
    owned = other.economy.household.items[0]
    assert owned.object_id in other.house.objects and other.house.objects[owned.object_id].kind == "trampoline"
