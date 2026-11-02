"""Coût de la partie : tokens x tarifs de Claude, affiché dans le panneau et l'écran Maison."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.service import LLMService, LLMStats
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import EventBus
from ui.household import expense_rows
from ui.hud import format_cost
from world.house import House


def test_cout_selon_les_tarifs():
    stats = LLMStats()
    stats.record_call(67_474, 11_942)
    assert stats.cost(0.10, 0.50) == pytest.approx(0.0127, abs=1e-4)
    assert format_cost(stats.cost(0.10, 0.50)) == "0,013 $ US"
    assert format_cost(12.345) == "12,35 $ US"


def test_tarifs_par_defaut_et_gratuit_sans_claude():
    config = load_config("config.yaml", scenario="maison")
    assert (config.llm.claude_price_in, config.llm.claude_price_out) == (0.10, 0.50)
    llm = LLMService(MockProvider((0.0, 0.0), 0.0), 100, 1)
    llm.stats.record_call(1000, 1000)
    assert llm.cost() == 0.0
    llm.shutdown()


def test_ecran_maison_montre_le_cout():
    config = load_config("config.yaml", scenario="maison")
    llm = LLMService(MockProvider((0.0, 0.0), 0.0), 100, 1, prices=(0.10, 0.50))
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(1, "10:00"), random.Random(1), EventBus(), llm)
    engine.initialize()
    llm.stats.record_call(2_000_000, 0)
    assert any("0,200 $ US" in text for text, _ in expense_rows(engine))
    llm.shutdown()
