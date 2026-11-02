"""Projets de vie : aspiration découpée en mois et semaines, progrès par le geste du jour, fiche et sauvegarde."""

import random
import time

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.project_prompts import ProjectIdea, validate_project
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from ui.portrait import project_rows
from world.house import House


def make(llm=None):
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(5, "07:50"), random.Random(1), bus, llm)
    engine.initialize()
    engine.visitors.known.clear()
    return engine, events


def idea(action="lire"):
    return ProjectIdea(aspiration="Lire plus de livres", why="pour m'évader", action=action,
                       month_goal="Finir un roman", weeks=["a", "b", "c", "d"])


def test_validation_du_projet():
    ok = validate_project(ProjectIdea(aspiration=" Courir ", action="exercice", month_goal="5 km", weeks=["x"]),
                          {"exercice"})
    assert ok.aspiration == "Courir" and len(ok.weeks) == 4
    with pytest.raises(ValueError):
        validate_project(idea("voler"), {"lire"})
    kept = validate_project(idea("tele"), {"lire", "tele"}, keep="lire")
    assert kept.action == "lire"


def test_actions_possibles_selon_la_personne():
    engine, _ = make()
    felix, marc = engine.agent_by_id("enfant"), engine.agent_by_id("pere")
    assert "jouer" in engine.projects.actions_for(felix) and "jouer" not in engine.projects.actions_for(marc)
    assert "jaser" not in engine.projects.actions_for(marc)


def test_projet_cree_le_lendemain_sans_ia():
    engine, events = make()
    for _ in range(20):
        engine.tick()
    assert all(a.aspiration is None for a in engine.agents)      # premier jour : on s'installe
    engine.projects.checked_day = engine.clock.day - 1
    engine.projects.update()
    people = [a for a in engine.agents if a.persona.stage != "bebe"]
    assert all(a.aspiration is not None for a in people)
    assert any(e.kind == "projet" for e in events)
    julie = engine.agent_by_id("mere")
    from llm.prompts import mind_block
    assert "Mon projet de vie" in mind_block(julie, engine.clock.total_minutes)


def test_progres_mois_semaine_et_projet_accompli():
    engine, events = make()
    julie = engine.agent_by_id("mere")
    engine.projects._apply(julie, idea())
    asp = julie.aspiration
    options = engine.options_for(julie)
    lire = next((o for o in options if o.action == "lire"), None)
    engine.projects.on_done(julie, "lire")
    engine.projects.on_done(julie, "lire")
    engine.projects.on_done(julie, "lire")                      # deux fois par jour au plus
    assert asp.month_progress == pytest.approx(18) and asp.did_today(engine.clock.day)
    assert lire is None or lire.score > 0
    engine.clock.total_minutes += 8 * 24 * 60 + 70
    engine.projects.update()
    assert asp.week_index == 1 and any("retard" in e.text for e in julie.memory.events)
    for day in range(30):
        asp.credited.clear()
        engine.projects.on_done(julie, "lire")
        if asp.done:
            break
    assert asp.done and asp.progress == 100 and any(e.kind == "projet_reussi" for e in events)
    assert any(e.kind == "projet_mois" for e in events) and any("réussi" in h for h in asp.history)
    rows = project_rows(engine, julie)
    assert rows[1][0] == "Projet de vie" and "Accompli" in rows[2][0]


def test_mois_manque_on_recommence():
    engine, _ = make()
    julie = engine.agent_by_id("mere")
    engine.projects._apply(julie, idea())
    engine.clock.total_minutes += 29 * 24 * 60 + 70
    engine.projects.update()
    asp = julie.aspiration
    assert asp.phase == 1 and asp.month_progress == 0 and asp.phase_day == engine.clock.day
    assert any("manqué" in h for h in asp.history)


def test_projet_par_l_ia_et_sauvegarde(tmp_path):
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 1000, 1)
    engine, _ = make(llm)
    felix = engine.agent_by_id("enfant")
    engine.projects._request(felix, None)
    deadline = time.monotonic() + 3
    while engine.projects.pending and time.monotonic() < deadline:
        engine.poll()
        time.sleep(0.005)
    assert felix.aspiration is not None and felix.aspiration.action in engine.projects.actions_for(felix)
    path = tmp_path / "save.json"
    engine.save_state(path)
    other, _ = make()
    other.load_state(path)
    assert other.agent_by_id("enfant").aspiration.text == felix.aspiration.text
    llm.shutdown()
