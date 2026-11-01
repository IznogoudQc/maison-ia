"""Économie du ménage : garde-manger, épicerie, paie, factures."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock, parse_hhmm
from sim.config import EconomyConfig, load_config
from sim.economy import Economy
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House

DAY = 24 * 60


def economy(money=100.0, pantry=10.0) -> Economy:
    eco = Economy(EconomyConfig())
    eco.household.money, eco.household.pantry = money, pantry
    return eco


def test_consommation_et_frigo_vide():
    eco = economy(pantry=1.5)
    assert eco.consume(1.0) and eco.household.pantry == pytest.approx(0.5)
    assert not eco.consume(1.0)
    assert eco.household.pantry == pytest.approx(0.5)  # rien retiré en cas d'échec


def test_epicerie_limitee_par_l_argent():
    eco = economy(money=100.0, pantry=0.0)
    bought, cost = eco.buy_groceries(0, alive=4, shopper="Julie")
    assert bought == 12 and cost == pytest.approx(96.0)  # 100 $ / 8 $ la portion
    assert eco.household.money == pytest.approx(4.0)
    assert eco.household.ledger[-1].amount == pytest.approx(-96.0)


def test_epicerie_vise_une_semaine():
    eco = economy(money=10_000.0, pantry=10.0)
    bought, _ = eco.buy_groceries(0, alive=4, shopper="Julie")
    assert eco.household.pantry == pytest.approx(4 * 3.5 * 7, abs=1)
    assert bought == 88


def test_epicerie_sans_argent():
    eco = economy(money=-50.0, pantry=0.0)
    assert eco.buy_groceries(0, alive=4, shopper="Julie") == (0, 0.0)


def test_factures_une_fois_par_semaine():
    eco = economy()
    clock = SimClock(4, "08:59")  # vendredi
    assert not eco.bills_due(clock)
    clock.advance()
    assert eco.bills_due(clock)
    total = eco.charge_bills(clock)
    assert total == pytest.approx(515.0)
    assert not eco.bills_due(clock)
    assert eco.household.money == pytest.approx(100.0 - 515.0)
    assert eco.in_debt


# ---------------------------------------------------------------- dans le moteur


@pytest.fixture
def engine():
    config = load_config("config.yaml", scenario="maison")
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    eng = Engine(config, House(), agents, SimClock(0, "06:00"), random.Random(2), bus)
    eng.initialize()
    return eng, events


def run_until(eng: Engine, minute: int) -> None:
    while eng.clock.total_minutes < minute:
        eng.tick()


def test_paie_versee_au_retour_du_travail(engine):
    eng, events = engine
    start = eng.economy.household.money
    run_until(eng, parse_hhmm("17:30"))
    paid = {e.data["name"]: e.data["amount"] for e in events if e.kind == "paie"}
    assert paid == {"Stéphane": 200, "Julie": 165}
    assert eng.economy.household.money > start  # paies > épicerie éventuelle du lundi


def test_factures_prelevees_le_vendredi(engine):
    eng, events = engine
    run_until(eng, 4 * DAY + parse_hhmm("10:00"))
    bills = [e for e in events if e.kind == "factures"]
    assert len(bills) == 1 and bills[0].data["amount"] == pytest.approx(-515.0)


def test_frigo_vide_puis_epicerie_avec_les_paies(engine):
    eng, events = engine
    eng.economy.household.pantry = 0.0
    eng.economy.household.money = 0.0  # pas d'épicerie possible avant les paies
    run_until(eng, parse_hhmm("12:00"))
    skipped = {e.data["name"] for e in events if e.kind == "frigo_vide" and e.data["action"] == "dejeuner"}
    assert skipped == {"Stéphane", "Julie", "Léa", "Félix"}
    assert eng.economy.household.pantry == 0.0

    run_until(eng, parse_hhmm("19:30"))
    assert any(e.kind == "paie" for e in events)
    assert any(e.kind == "epicerie" and e.data["portions"] > 0 for e in events)


def test_epicerie_quand_le_garde_manger_baisse(engine):
    eng, events = engine
    eng.economy.household.pantry = 3.0
    run_until(eng, 5 * DAY + parse_hhmm("20:00"))  # samedi soir : un adulte a eu le temps d'y aller
    groceries = [e for e in events if e.kind == "epicerie"]
    assert groceries and groceries[0].data["portions"] > 0
    assert eng.economy.household.pantry > 3.0
