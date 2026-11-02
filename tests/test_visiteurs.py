"""Voisins et visite : arrivée par l'arrêt d'autobus, jasette avec la famille, départ, mémoire gardée."""

import random

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.visitors import load_visitors
from world.house import House


def make(llm=None, start="11:00"):
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(5, start), random.Random(1), bus, llm)
    engine.initialize()
    return engine, events


def test_fiches_des_visiteurs():
    maison, terrain = load_visitors("maison"), load_visitors("terrain")
    assert {p.id for p in maison} >= {"grandmere", "voisin"} and len(terrain) >= 2
    assert load_visitors("inconnu") == []


def test_visite_arrive_bouge_et_repart():
    engine, events = make()
    visits = engine.visitors
    ginette = visits.known["grandmere"]
    visits.planned_day = engine.clock.day   # pas de tirage du jour : on la fait venir
    visits.planned = None
    visits.arrive(ginette, duration=30)
    assert ginette in engine.visitors.present and ginette.pos == visits.door()
    assert engine.agent_by_id("grandmere") is ginette
    assert ginette not in engine.agents                      # pas membre du ménage
    assert any(e.kind == "visite" for e in events)
    julie = engine.agent_by_id("mere")
    assert any("Ginette" in e.text for e in julie.memory.events)
    assert "Ginette" in engine.dialogue_context(engine.agents)
    for _ in range(30):
        engine.tick()
    assert ginette in engine.everyone
    assert all(o.action not in ("epicerie", "acheter", "tondre", "soigner") for o in engine.options_for(ginette))
    for _ in range(200):
        engine.tick()
    assert ginette not in engine.visitors.present and ginette not in engine.everyone
    assert any(e.kind == "fin_visite" for e in events)
    assert any(e.title.startswith("Ginette") for e in engine.history.entries)


def test_les_visiteurs_jasent_avec_la_famille():
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 1000, 1)
    engine, _events = make(llm)
    visits = engine.visitors
    visits.planned_day, visits.planned = engine.clock.day, None
    rejean = visits.known["voisin"]
    visits.arrive(rejean, duration=120)
    julie = engine.agent_by_id("mere")
    rejean.pos = julie.pos
    seen = []
    submit = engine.llm.try_submit
    engine.llm.try_submit = lambda request, *a, **k: seen.append(request) or submit(request, *a, **k)
    engine.everyone[:] = [*engine.agents, *visits.present]
    engine._detect_encounters()
    assert any("Réjean" in r.prompt for r in seen)
    assert not engine._should_ask_llm(rejean, engine.options_for(rejean))   # pas de décision par l'IA
    llm.shutdown()


def test_tirage_de_la_journee_reproductible():
    engine, _ = make()
    plans = [engine.visitors.plan_day(day) for day in range(5, 40)]
    assert plans == [engine.visitors.plan_day(day) for day in range(5, 40)]
    visits = [p for p in plans if p is not None]
    assert visits and all(10 * 60 <= p[0] % (24 * 60) <= 17 * 60 for p in visits)


def test_sauvegarde_garde_les_souvenirs(tmp_path):
    engine, _ = make()
    ginette = engine.visitors.known["grandmere"]
    engine.remember(ginette, "Félix m'a montré son château de Lego.", 6)
    engine.visitors.arrive(ginette)
    path = tmp_path / "save.json"
    engine.save_state(path)
    other, _ = make()
    other.load_state(path)
    again = other.visitors.known["grandmere"]
    assert any("château de Lego" in e.text for e in again.memory.events)
    assert again.visitor and other.visitors.present == []
    assert other.visitors.last_visit["grandmere"] == engine.clock.day
