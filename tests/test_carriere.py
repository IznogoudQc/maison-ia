"""Carrière : emploi de départ, promotion, perte d'emploi, assurance-emploi, offre, études, école, 18 ans."""

import random

import pytest

import sim.career as career_module
from agents.agent import Agent
from agents.persona import load_family
from sim.career import BOURSE, Career
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House


@pytest.fixture
def setup():
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    config.world.date_depart = "2026-09-14"   # un lundi de septembre : école ouverte, pas de férié
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(1, "05:30"), random.Random(1), bus)
    engine.initialize()
    engine.economy.household.money = 20_000.0
    return engine, events


def test_emploi_et_ecole_de_depart(setup):
    engine, _ = setup
    pere, ado, enfant = (engine.agent_by_id(i) for i in ("pere", "ado", "enfant"))
    assert pere.career.job == "telecom" and pere.career.employer == "Télécom Boréal"
    assert pere.persona.salary_per_day == 200 and pere.career.formations == ["dep_telecom"]
    assert engine.careers.describe(pere).startswith("Technique en télécommunications · 200 $/jour")
    assert engine.careers.describe(ado).startswith("Secondaire 4 · moyenne")
    assert engine.careers.describe(enfant).startswith("3e année du primaire")
    assert "Travail et école : Stéphane" in engine.family_context(engine.agents)


def test_promotion(setup, monkeypatch):
    engine, events = setup
    monkeypatch.setattr(career_module, "PROMO_CHANCE", 1.0)
    pere = engine.agent_by_id("pere")
    pere.career.hired_day = pere.career.promoted_day = -40
    pere.needs.fun = pere.needs.social = 100
    pere.career.satisfaction = 90
    engine.careers.daily(engine.clock.day)
    assert pere.career.level == 1 and pere.persona.salary_per_day == 230
    assert any(e.kind == "promotion" for e in events) and "Promotion" in pere.career.history[-1]


def test_perte_d_emploi_puis_offre_acceptee(setup, monkeypatch):
    engine, events = setup
    monkeypatch.setattr(career_module, "OFFER_JOBLESS", 1.0)
    mere = engine.agent_by_id("mere")
    engine.careers.lose_job(mere, "congédiement")
    assert mere.persona.salary_per_day == 0 and mere.persona.schedule.away is None
    money = engine.economy.household.money
    engine.careers.daily(engine.clock.day)
    assert engine.economy.household.money == pytest.approx(money + 165 * 0.55)     # assurance-emploi
    assert mere.career.offer is not None
    engine.clock.total_minutes = engine.clock.day * 24 * 60 + parse_hhmm("18:00")
    mere.action = None
    offer = next(o for o in engine.options_for(mere) if o.action == "carriere" and o.target.startswith("offre"))
    action = engine.make_action(mere, "carriere", offer.target)
    assert action is not None and action.label.startswith("l'offre")
    engine.careers.decide(mere, offer.target)
    assert mere.career.job is not None and mere.persona.schedule.away.label == "travail"
    assert any(e.kind == "embauche" for e in events)


def test_retour_aux_etudes_et_diplome(setup):
    engine, events = setup
    pere = engine.agent_by_id("pere")
    money = engine.economy.household.money
    engine.careers.start_studies(pere, "dep_charpenterie")
    assert engine.economy.household.money == pytest.approx(money - 350)
    assert pere.persona.salary_per_day == BOURSE and pere.persona.schedule.away.label == "cours"
    pere.career.study_left = 1
    engine.careers.daily(engine.clock.day)                                         # dernier jour de cours
    assert pere.career.studying is None and "dep_charpenterie" in pere.career.formations
    assert pere.career.offer.startswith("charpenterie") and any(e.kind == "diplome" for e in events)


def test_devoirs_et_passage_a_18_ans(setup):
    engine, events = setup
    ado = engine.agent_by_id("ado")
    before = ado.career.grade
    engine.careers.homework(ado)
    assert ado.career.grade == pytest.approx(before + 1.5)
    ado.career.grade = 82
    ado.persona.age = 18
    engine.careers.daily(engine.clock.day)
    assert ado.career.studying is not None and ado.career.studying.startswith("dec_")   # cégep
    assert ado.persona.schedule.away.label == "cours" and any(e.kind == "etudes" for e in events)


def test_sauvegarde_garde_la_carriere(setup, tmp_path):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    pere.career.level = 2
    engine.careers.apply(pere)
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, House(), agents, SimClock(), random.Random(2), EventBus())
    other.load_state(tmp_path / "save.json")
    again = other.agent_by_id("pere")
    assert isinstance(again.career, Career) and again.career.level == 2
    assert again.persona.salary_per_day == 260
