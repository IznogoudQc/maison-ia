"""Santé, mort, deuil, hôpital et fin de partie."""

import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House

DAY = 24 * 60


def make_engine(mortality: bool = True):
    config = load_config("config.yaml")
    config.health.mortality = mortality
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    eng = Engine(config, House(), agents, SimClock(5, "10:00"), random.Random(3), bus)  # samedi
    eng.initialize()
    return eng, events


def test_la_faim_use_la_sante_puis_elle_remonte():
    eng, _ = make_engine()
    agent = eng.agents[0]
    agent.needs.hunger = 0.0
    eng._update_health(agent, 60)
    assert agent.health == pytest.approx(100 - eng.config.health.starvation_per_hour)
    agent.needs.hunger, agent.needs.energy = 80.0, 80.0
    eng._update_health(agent, 60)
    assert agent.health == pytest.approx(100 - 2.0 + 1.5)


def test_deces_et_deuil_des_survivants():
    eng, events = make_engine()
    victim = eng.agent_by_id("pere")
    victim.health, victim.needs.hunger = 0.01, 0.0
    eng.tick()
    assert victim.dead and victim.status_label.startswith("†")
    deaths = [e for e in events if e.kind == "deces"]
    assert len(deaths) == 1 and deaths[0].data["cause"] == "de faim"
    survivors = [a for a in eng.agents if not a.dead]
    assert len(survivors) == 3 and eng.alive_count() == 3
    assert all(a.mood == "en deuil" for a in survivors)
    assert all("Stéphane nous a quittés" in a.memory.events[-1].text for a in survivors)
    assert not victim.is_available


def test_un_defunt_ne_bouge_plus_et_ne_jase_plus():
    eng, _ = make_engine()
    victim = eng.agent_by_id("ado")
    victim.health, victim.needs.hunger = 0.01, 0.0
    eng.tick()
    pos = victim.pos
    for _ in range(120):
        eng.tick()
    assert victim.pos == pos and victim.action is None
    other = eng.agent_by_id("enfant")
    assert all(o.target != "ado" for o in eng.options_for(other))


def test_fin_de_partie_quand_tout_le_monde_est_mort():
    eng, events = make_engine()
    for agent in eng.agents:
        agent.health, agent.needs.hunger = 0.01, 0.0
    eng.tick()
    assert eng.game_over and any(e.kind == "fin" for e in events)
    minute = eng.clock.total_minutes
    eng.tick()
    assert eng.clock.total_minutes == minute  # la simulation est figée


def test_mode_sans_mortalite_envoie_a_l_hopital():
    eng, events = make_engine(mortality=False)
    patient = eng.agent_by_id("mere")
    patient.health, patient.needs.hunger = 0.01, 0.0
    eng.tick()
    assert not patient.dead and patient.away_kind == "hopital"
    assert any(e.kind == "hopital" for e in events)
    while eng.clock.total_minutes < 5 * DAY + 10 * 60 + eng.config.health.hospital_days * DAY + 5:
        eng.tick()
    assert not patient.is_away and patient.health > 0


def test_sauvegarde_conserve_les_deces(tmp_path):
    eng, _ = make_engine()
    victim = eng.agent_by_id("enfant")
    victim.health, victim.needs.hunger = 0.01, 0.0
    eng.tick()
    eng.save_state(tmp_path / "save.json")
    other, _ = make_engine()
    other.load_state(tmp_path / "save.json")
    assert other.agent_by_id("enfant").dead and other.alive_count() == 3 and not other.game_over
