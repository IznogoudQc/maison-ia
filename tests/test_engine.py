"""Simulation headless avec le provider mock : horaire, dialogues, sauvegarde."""

import random
import time

import pytest

from agents.agent import Agent
from agents.persona import load_family
from agents.scheduler import is_sleep_time
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House


@pytest.fixture
def setup():
    config = load_config("config.yaml")
    config.llm.max_calls_per_minute = 100_000
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 100_000, 2)
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    clock = SimClock(0, "06:00")  # lundi
    engine = Engine(config, House(), agents, clock, random.Random(4), bus, llm)
    engine.initialize()
    yield engine, events, config
    llm.shutdown()


def run_until(engine: Engine, total_minutes: int) -> None:
    while engine.clock.total_minutes < total_minutes:
        engine.tick()
        deadline = time.monotonic() + 1.0
        while (engine.pending_decisions or engine.pending_dialogues or engine.pending_summaries) \
                and time.monotonic() < deadline:
            engine.poll()
            time.sleep(0.0005)


def test_fenetre_de_sommeil():
    wake, sleep = parse_hhmm("06:30"), parse_hhmm("22:45")
    assert is_sleep_time(parse_hhmm("23:00"), wake, sleep)
    assert is_sleep_time(parse_hhmm("03:00"), wake, sleep)
    assert not is_sleep_time(parse_hhmm("12:00"), wake, sleep)
    # Coucher après minuit
    assert is_sleep_time(parse_hhmm("01:00"), parse_hhmm("07:00"), parse_hhmm("00:30"))
    assert not is_sleep_time(parse_hhmm("23:50"), parse_hhmm("07:00"), parse_hhmm("00:30"))


def test_journee_type_d_un_lundi(setup):
    engine, events, _ = setup
    run_until(engine, parse_hhmm("23:40"))
    kinds = [e.kind for e in events]
    # Travail et école seulement : un adulte peut aussi sortir faire l'épicerie
    daily = [e for e in events if e.kind in ("depart", "retour") and e.data["label"] in ("travail", "école")]
    assert len(daily) == 8
    soupers = [e for e in events if e.kind == "action" and e.data["action"] == "souper"]
    assert len(soupers) == 4
    assert "dialogue" in kinds
    assert all(agent.is_sleeping for agent in engine.agents)
    assert all(agent.memory.events for agent in engine.agents)


def test_cooldown_par_paire(setup):
    engine, events, config = setup
    run_until(engine, parse_hhmm("23:40"))
    last: dict[frozenset, int] = {}
    for event in (e for e in events if e.kind == "dialogue"):
        people = event.data["participants"]
        for i, a in enumerate(people):
            for b in people[i + 1:]:
                pair = frozenset((a, b))
                if pair in last:
                    # Demande au plus tôt au cooldown ; la réponse arrive dans la même minute (mock sans latence)
                    assert event.minute - last[pair] >= config.dialogue.pair_cooldown_minutes
                last[pair] = event.minute


def test_sauvegarde_et_chargement(setup, tmp_path):
    engine, _, config = setup
    run_until(engine, parse_hhmm("19:00"))
    path = tmp_path / "save.json"
    engine.save_state(path)

    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, House(), agents, SimClock(), random.Random(0))
    other.initialize()
    other.load_state(path)
    assert other.clock.total_minutes == engine.clock.total_minutes
    assert other.pair_last_talk == engine.pair_last_talk
    for before, after in zip(engine.agents, other.agents):
        assert after.model_dump() == before.model_dump()
