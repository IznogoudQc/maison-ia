"""Cache des prompts : début de message stable et assez long, point de cache envoyé à Claude, coût réduit."""

import random
from types import SimpleNamespace

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.claude_provider import ClaudeProvider
from llm.prompts import build_decision_request
from llm.provider import LLMRequest
from llm.service import LLMStats
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from world.house import House


def engine_at(hhmm):
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(2, hhmm), random.Random(1))
    engine.initialize()
    return engine


def test_debut_stable_et_assez_long_pour_le_cache():
    requests = []
    for hhmm in ("08:00", "19:30"):
        engine = engine_at(hhmm)
        pere = engine.agent_by_id("pere")
        requests.append(build_decision_request(pere, "Salon", engine.clock.label(), engine.options_for(pere)[:3],
                                               [], None, 500, engine.family_context([pere]),
                                               now=engine.clock.total_minutes, family=engine.agents))
    first, second = requests
    assert first.prefix == second.prefix and first.prompt != second.prompt   # même début, situation différente
    assert (len(first.system) + len(first.prefix)) / 4 > 512                  # minimum de cache de Claude Haiku 5.5
    assert "Julie" in first.prefix and "Stéphane" in first.prefix and "LE MONDE" in first.prefix


def test_point_de_cache_envoye_a_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "cle-de-test")
    provider = ClaudeProvider("claude-haiku-5-5")
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        usage = SimpleNamespace(input_tokens=40, output_tokens=12, cache_read_input_tokens=700,
                                cache_creation_input_tokens=0)
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text='{"ok": true}')])

    monkeypatch.setattr(provider.client.messages, "create", create)
    response = provider.complete(LLMRequest(kind="decision", system="S", prefix="FICHE STABLE", prompt="SITUATION"))
    content = seen["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "FICHE STABLE", "cache_control": {"type": "ephemeral"}}
    assert content[1]["text"] == "SITUATION"
    assert response.cache_read_tokens == 700 and response.input_tokens == 40


def test_cout_et_economies_du_cache():
    stats = LLMStats()
    stats.record_call(1_000_000, 0, cache_read=10_000_000, cache_write=1_000_000)
    # 1 M plein prix + 10 M lus à 0,1 + 1 M écrits à 1,25 = 3,25 M au prix d'entrée
    assert stats.cost(0.10, 0.50) == pytest.approx(0.325)
    assert stats.cache_savings(0.10) == pytest.approx((10 * 0.9 - 0.25) * 0.10)
