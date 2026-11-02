"""Dialogues variés : contexte léger, sujets récents à ne pas reprendre, idée de sujet, pas de but rabâché."""

import random

from agents.agent import Agent
from agents.persona import load_family
from agents.plan import Goal
from llm.mock_provider import MockProvider
from llm.prompts import mind_block
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import EventBus
from world.house import House


def make():
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    config.dialogue.mode = "tour_par_tour"
    llm = LLMService(MockProvider((0.0, 0.0), 0.0), 1000, 1)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(2, "18:00"), random.Random(1), EventBus(), llm)
    engine.initialize()
    engine.economy.household.money = 10_000.0
    engine.economy.add_food("lait", 30, engine.clock.day)
    return engine, llm


def captured_prompt(engine, monkeypatch):
    seen = []
    monkeypatch.setattr(engine.llm, "try_submit", lambda request, *a, **k: seen.append(request) or None)
    group = [engine.agent_by_id("pere"), engine.agent_by_id("mere")]
    engine.social.start(group, "Cuisine")
    return seen[0]


def test_contexte_leger_pour_jaser():
    engine, llm = make()
    family = engine.family_context(engine.agents)
    chat = engine.dialogue_context(engine.agents)
    assert "Dans le garde-manger" in family and "Dans le garde-manger" not in chat
    assert "lait" not in chat and "Aujourd'hui" in chat and "Travail et école" in chat
    engine.economy.household.pantry = 0.5
    engine.economy.household.foods.clear()
    assert "presque plus rien à manger" in engine.dialogue_context(engine.agents)
    llm.shutdown()


def test_la_replique_varie_les_sujets(monkeypatch):
    engine, llm = make()
    pere, mere = engine.agent_by_id("pere"), engine.agent_by_id("mere")
    pere.goal = Goal(text="montrer le budget à Julie", action="jaser", until=engine.clock.total_minutes + 600)
    mere.goal = Goal(text="montrer le budget à Stéphane", action="jaser", until=engine.clock.total_minutes + 600)
    engine.social.remember_topic([pere, mere], "Julie demande la liste d'épicerie et le budget.")
    request = captured_prompt(engine, monkeypatch)
    assert "Varie les sujets" in request.system and "épicerie, chômage" not in request.system
    assert "DÉJÀ JASÉ RÉCEMMENT" in request.prompt and "liste d'épicerie" in request.prompt
    assert "IDÉE DE SUJET" in request.prompt and "Dans le garde-manger" not in request.prompt
    assert "montrer le budget" not in request.prompt                            # le but du soir n'est pas rabâché
    assert "Je me suis promis" in mind_block(pere, engine.clock.total_minutes)  # mais il guide toujours les décisions
    llm.shutdown()


def test_sujets_recents_garde_les_deux_derniers_et_se_sauvegarde(tmp_path):
    engine, llm = make()
    pair = [engine.agent_by_id("pere"), engine.agent_by_id("mere")]
    for text in ("budget", "épicerie", "hockey"):
        engine.social.remember_topic(pair, text)
    assert engine.social.recent_topics(list(reversed(pair))) == ["épicerie", "hockey"]
    idea = engine.social.topic_idea(pair, 7)
    assert idea == engine.social.topic_idea(pair, 7) and "hockey" not in idea.lower()
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, House(), agents, SimClock(), random.Random(2), EventBus())
    other.load_state(tmp_path / "save.json")
    assert other.social.recent_topics(pair) == ["épicerie", "hockey"]
    llm.shutdown()
