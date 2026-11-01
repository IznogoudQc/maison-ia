"""Crédit : amortissement, prêteur, paiements du vendredi, retards, saisie, remboursement, prêt rénovation."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.credit import weekly_payment
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.building import place_rooms, trees_in
from world.house import House
from world.terrain import build_house


def make_engine(scenario="maison", money=5000.0):
    config = load_config("config.yaml", scenario=scenario)
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    house = House() if scenario == "maison" else build_house("terrain", 120, 80, 42)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, house, agents, SimClock(5, "10:00"), random.Random(2), bus)
    engine.initialize()
    engine.economy.household.money = money
    return engine, events


def test_amortissement():
    assert weekly_payment(5200, 0.0, 52) == pytest.approx(100.0)
    payment = weekly_payment(10_000, 0.06, 104)
    assert 96 < payment < 110 and payment * 104 > 10_000  # des intérêts, mais raisonnables


def test_financer_une_premiere_auto():
    engine, events = make_engine(money=5000.0)
    pere = engine.agent_by_id("pere")
    option = next(o for o in engine.credit.options_for(pere) if o.target.startswith("vehicule|"))
    assert "à crédit" in option.label and "$/semaine" in option.label
    loan = engine.credit.borrow(pere, "vehicule|compacte")
    assert loan is not None and loan.principal == pytest.approx(8000 - 1200)
    assert engine.economy.household.money == pytest.approx(5000 - 1200)
    assert [v.model for v in engine.economy.household.vehicles] == ["compacte"]
    assert any(e.kind == "pret" and e.data["ok"] for e in events)


def test_le_preteur_refuse_si_les_paiements_sont_trop_lourds():
    engine, _ = make_engine(money=5000.0)
    for agent in engine.agents:
        agent.persona.salary_per_day = 20  # petit revenu
    ok, reason, _down, _payment = engine.credit.check("vehicule", 20_000)
    assert not ok and "revenu" in reason
    engine.economy.household.credit_score = 500
    ok, reason, _down, _payment = engine.credit.check("objet", 2000)
    assert not ok and "dossier" in reason


def test_paiement_du_vendredi_et_dossier_qui_monte():
    engine, _ = make_engine(money=5000.0)
    loan = engine.credit.borrow(engine.agent_by_id("pere"), "vehicule|compacte")
    balance, score = loan.balance, engine.economy.household.credit_score
    engine.credit.charge()
    assert loan.balance < balance and loan.weeks_left == 103
    assert engine.economy.household.credit_score == score + 3


def test_trois_retards_la_banque_reprend_le_vehicule():
    engine, events = make_engine(money=5000.0)
    loan = engine.credit.borrow(engine.agent_by_id("pere"), "vehicule|compacte")
    engine.economy.household.money = 0.0
    score = engine.economy.household.credit_score
    for _ in range(3):
        engine.credit.charge()
    assert not engine.economy.household.loans and not engine.economy.household.vehicles
    assert engine.economy.household.credit_score < score - 120
    assert any(e.kind == "pret_retard" and "repris" in e.data["text"] for e in events)
    assert not any(o.kind == "vehicule" for o in engine.house.objects.values())
    assert loan.missed == 3


def test_remboursement_anticipe():
    engine, _ = make_engine(money=5000.0)
    pere = engine.agent_by_id("pere")
    loan = engine.credit.borrow(pere, "vehicule|compacte")
    engine.economy.household.money = 50_000.0
    option = next(o for o in engine.credit.options_for(pere) if o.action == "rembourser")
    engine.credit.repay(pere, option.target)
    assert not engine.economy.household.loans
    assert engine.economy.household.money == pytest.approx(50_000.0 - loan.balance)


def test_pret_renovation_paie_les_materiaux():
    engine, _ = make_engine("terrain", money=1500.0)
    plan = place_rooms(engine.house, [{"id": "cuisine", "type": "cuisine", "name": "Cuisine",
                                       "width": 6, "height": 5}], engine.architect.site())
    room = plan.rooms[0]
    for tree in trees_in(engine.house, room):
        engine.house.remove_object(tree.id)
    room.status = "pret"
    engine.architect.plan = plan
    maxime = engine.agent_by_id("maxime")
    assert not engine.architect.can_afford_materials(room)
    option = next(o for o in engine.credit.options_for(maxime) if o.target.startswith("chantier|"))
    loan = engine.credit.borrow(maxime, option.target)
    assert loan is not None and loan.purpose == "chantier"
    assert room.materials_paid and room.status == "chantier"
