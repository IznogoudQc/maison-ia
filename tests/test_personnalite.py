"""Personnalités qui évoluent : conclusions de fond -> trait ajouté, renforcé ou retiré ; prompts, fiche, sauvegarde."""

import random
import time

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.personality_prompts import PersonalityChange, validate_change
from llm.prompts import family_roster, persona_block
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, Event, EventBus
from ui.portrait import character_rows, personality_rows
from world.house import House


def make(llm=None):
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(12, "21:00"), random.Random(1), bus, llm)
    engine.initialize()
    engine.visitors.known.clear()
    return engine, events


def test_validation_du_changement():
    ok = validate_change(PersonalityChange(change="Renforcer", kind="qualité", trait="Organisée"),
                         ["organisée"], ["impatiente"])
    assert ok.change == "renforcer" and ok.trait == "organisée"
    with pytest.raises(ValueError):
        validate_change(PersonalityChange(change="retirer", kind="defaut", trait="jalouse"), [], ["impatiente"])
    with pytest.raises(ValueError):
        validate_change(PersonalityChange(change="ajouter", kind="defaut", trait="impatiente"), [], ["impatiente"])
    assert validate_change(PersonalityChange(change="aucun"), [], []).change == "aucun"


def test_ajouter_renforcer_retirer():
    engine, events = make()
    julie = engine.agent_by_id("mere")
    base_q, base_d = list(julie.persona.qualites), list(julie.persona.defauts)
    engine.personalities.apply(julie, PersonalityChange(change="ajouter", kind="qualite", trait="patiente",
                                                        reason="Les chicanes m'ont appris à respirer."))
    assert julie.qualites == base_q + ["patiente"] and julie.persona.qualites == base_q   # la fiche reste intacte
    engine.personalities.apply(julie, PersonalityChange(change="renforcer", kind="qualite", trait="patiente"))
    assert "patiente (de plus en plus)" in persona_block(julie)
    engine.personalities.apply(julie, PersonalityChange(change="retirer", kind="defaut", trait=base_d[0]))
    assert base_d[0] not in julie.defauts
    assert any(e.kind == "personnalite" for e in events)
    assert any("je deviens patiente" in e.text for e in julie.memory.events)
    assert "patiente (de plus en plus)" in character_rows(julie)[2][0]
    rows = personality_rows(engine, julie)
    assert rows[1][0] == "Évolution du caractère" and len(rows) == 5 and base_d[0] in rows[2][0]
    # le reste de la famille voit aussi les traits à jour
    assert "patiente" in family_roster(engine.agents, exclude=engine.agent_by_id("pere"))


def test_trois_conclusions_de_fond_puis_l_ia_decide():
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 1000, 1)
    engine, events = make(llm)
    marc = engine.agent_by_id("pere")
    first = marc.qualites[0]
    for text in ("Je tiens à ma famille.", "Je travaille trop.", "Je veux être là pour les enfants."):
        engine.bus.publish(Event("reflexion", engine.clock.total_minutes,
                                 {"agent": "pere", "name": marc.name, "deep": text}))
    assert "pere" in engine.personalities.pending
    deadline = time.monotonic() + 3
    while engine.personalities.pending and time.monotonic() < deadline:
        engine.poll()
        time.sleep(0.005)
    assert marc.personality.stronger.get(first) == 1 and marc.personality.history[-1].change == "renforcer"
    assert marc.personality.last_change_day == engine.clock.day and len(marc.personality.evidence) == 1
    engine.bus.publish(Event("reflexion", 0, {"agent": "pere", "deep": "Encore."}))
    engine.bus.publish(Event("reflexion", 0, {"agent": "pere", "deep": "Et encore."}))
    assert "pere" not in engine.personalities.pending          # une semaine entre deux changements
    llm.shutdown()


def test_sauvegarde_de_la_personnalite(tmp_path):
    engine, _ = make()
    julie = engine.agent_by_id("mere")
    engine.personalities.apply(julie, PersonalityChange(change="ajouter", kind="defaut", trait="rancunière"))
    path = tmp_path / "save.json"
    engine.save_state(path)
    other, _ = make()
    other.load_state(path)
    assert "rancunière" in other.agent_by_id("mere").defauts
