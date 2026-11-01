"""Extérieur : achats, pelouse, auto familiale, BBQ."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.economy import CATALOG
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import PURCHASE_OBJECTS, House
from world.pathfinding import find_path

DAY = 24 * 60


def make_engine(day: int = 0, time: str = "06:00", money: float = 1500.0):
    config = load_config("config.yaml")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    eng = Engine(config, House(), agents, SimClock(day, time), random.Random(6), bus)
    eng.initialize()
    eng.economy.household.money = money
    return eng, events


def run_until(eng, minute):
    while eng.clock.total_minutes < minute:
        eng.tick()


def test_objets_achetes_atteignables():
    house = House()
    for obj in PURCHASE_OBJECTS.values():
        house.add_object(obj)
    start = (2, 11)
    for obj in house.objects.values():
        for pos in obj.use_positions:
            assert house.is_walkable(pos), f"{obj.id} : {pos}"
            assert find_path(start, pos, house.is_walkable) is not None, f"{obj.id} : {pos}"


def test_achat_debite_ajoute_l_objet_et_les_frais():
    eng, events = make_engine(money=4000.0)
    bills_before = eng.economy.weekly_bills()
    eng._buy(eng.agent_by_id("pere"), "piscine")
    assert eng.economy.household.money == pytest.approx(1500.0)
    assert "piscine" in eng.house.objects and eng.economy.owns("piscine")
    assert eng.economy.weekly_bills() == pytest.approx(bills_before + CATALOG["piscine"].weekly_cost)
    assert any(e.kind == "achat" for e in events)
    eng._buy(eng.agent_by_id("pere"), "piscine")  # déjà possédée : rien ne se passe
    assert eng.economy.household.money == pytest.approx(1500.0)


def test_achat_propose_seulement_avec_un_coussin():
    eng, _ = make_engine(money=1500.0)
    pere = eng.agent_by_id("pere")
    assert not any(o.action == "acheter" for o in eng.options_for(pere))
    eng.economy.household.money = 50_000.0
    offered = {o.target for o in eng.options_for(pere) if o.action == "acheter"}
    assert offered == set(eng.house.layout.catalog)  # la scie à chaîne est réservée au terrain
    assert not any(o.action == "acheter" for o in eng.options_for(eng.agent_by_id("enfant")))


def test_gazon_pousse_et_le_voisin_tond_sans_tondeuse():
    eng, events = make_engine()
    eng.economy.household.lawn = 50.0
    eng.economy.household.last_lawn_day = 0  # déjà poussé aujourd'hui
    run_until(eng, DAY + parse_hhmm("06:05"))
    assert eng.economy.household.lawn == pytest.approx(64.0)  # +14 par jour
    eng.economy.household.lawn = 80.0
    run_until(eng, 2 * DAY + parse_hhmm("06:05"))
    assert eng.economy.household.lawn == 0.0
    assert any(e.kind == "evenement" and "jeune d'à côté" in e.data["text"] for e in events)
    assert any(entry.amount == -40 for entry in eng.economy.household.ledger)


def test_amende_si_pelouse_a_100_sans_argent():
    eng, events = make_engine(money=10.0)
    eng.economy.household.lawn = 95.0
    run_until(eng, parse_hhmm("06:05"))
    assert any(e.kind == "evenement" and "Amende" in e.data["text"] for e in events)
    assert any(entry.label.startswith("Amende") and entry.amount == -150 for entry in eng.economy.household.ledger)
    run_until(eng, DAY + parse_hhmm("06:05"))
    fines = [e for e in eng.economy.household.ledger if e.label.startswith("Amende")]
    assert len(fines) == 1  # au plus une amende par semaine


def test_tondre_remet_le_gazon_a_zero():
    eng, events = make_engine(day=5, time="09:00", money=500.0)  # samedi
    eng.economy.household.purchases.append("tondeuse")
    eng.economy.household.lawn = 95.0
    eng.economy.household.last_lawn_day = eng.clock.day
    run_until(eng, 5 * DAY + parse_hhmm("19:00"))
    assert any(e.kind == "action" and e.data["action"] == "tondre" for e in events)
    assert eng.economy.household.lawn < 50.0


def test_auto_retour_plus_tot_et_absente_de_l_entree():
    eng, events = make_engine(money=20_000.0)
    eng._buy(eng.agent_by_id("pere"), "auto")
    run_until(eng, parse_hhmm("09:00"))
    pere = eng.agent_by_id("pere")
    assert pere.drove and not eng.car_home()
    run_until(eng, parse_hhmm("17:00"))
    back = next(e for e in events if e.kind == "retour" and e.data["name"] == "Stéphane")
    assert back.minute == parse_hhmm("16:45") - 30
    assert eng.car_home()


def test_bbq_la_fin_de_semaine():
    eng, events = make_engine(day=5, time="16:00", money=5000.0)
    eng._buy(eng.agent_by_id("pere"), "bbq")
    run_until(eng, 5 * DAY + parse_hhmm("18:00"))
    assert any(e.kind == "action" and e.data["action"] == "bbq" and e.data["name"] == "Stéphane"
               for e in events)


def test_sauvegarde_restaure_les_achats(tmp_path):
    eng, _ = make_engine(money=20_000.0)
    eng._buy(eng.agent_by_id("pere"), "piscine")
    eng.save_state(tmp_path / "save.json")
    other, _ = make_engine()
    other.load_state(tmp_path / "save.json")
    assert "piscine" in other.house.objects and other.economy.owns("piscine")
