"""Fêtes et rumeurs : invitation de bouche à oreille, invités qui arrivent, rumeur qui circule et se déforme."""

import random
import time

import sim.gossip as G
from agents.agent import Agent
from agents.persona import load_family
from llm.gossip_prompts import PartyIdea, validate_party
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, Event, EventBus
from sim.gossip import Rumor
from world.house import House


def make(llm=None, day=5, start="11:00"):
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(day, start), random.Random(1), bus, llm)
    engine.initialize()
    engine.visitors.planned_day, engine.visitors.planned = engine.clock.day, None   # pas de visite au hasard
    return engine, events


def talk(engine, *ids):
    names = [engine.agent_by_id(i).name for i in ids]
    engine.bus.publish(Event("dialogue", engine.clock.total_minutes, {"participants": names, "lines": []}))


def test_validation_de_la_fete():
    idea = validate_party(PartyIdea(title=" BBQ ", hour=30, guests=["voisin", "inconnu", "voisin"]), {"voisin"})
    assert idea.title == "BBQ" and idea.hour == 20 and idea.guests == ["voisin"]


def test_fete_invitation_et_deroulement():
    engine, events = make()
    gossip = engine.gossip
    julie, marc = engine.agent_by_id("mere"), engine.agent_by_id("pere")
    gossip._create(julie, engine.clock.day, "", PartyIdea(title="BBQ des voisins", hour=12, guests=["voisin"]))
    assert any(e.kind == "fete_prevue" for e in events)
    assert "BBQ des voisins" in engine.dialogue_context([julie]) and "BBQ" not in engine.dialogue_context([marc])
    talk(engine, "mere", "pere")
    assert "pere" in gossip.party.known_by and any("BBQ des voisins" in e.text for e in marc.memory.events)
    for _ in range(61):
        engine.tick()
    assert gossip.party.status == "en_cours" and engine.visitors.known["voisin"] in engine.visitors.present
    lea = engine.agent_by_id("ado")
    if lea.is_available:
        assert any("Surprise" in e.text for e in lea.memory.events)
    for _ in range(200):
        engine.tick()
    assert gossip.party is None and gossip.past_parties[-1].title == "BBQ des voisins"
    assert any(e.kind == "fin_fete" for e in events)
    assert any(e.title.startswith("C'est la fête") for e in engine.history.entries)


def test_tirage_des_fetes_le_milieu_de_semaine():
    engine, _ = make()
    for day in range(5, 40):
        engine.clock.total_minutes = day * 24 * 60 + 9 * 60
        engine.gossip._maybe_plan(day)
        if engine.gossip.party is not None:
            break
    party = engine.gossip.party
    assert party is not None and party.day > day and party.host in {a.id for a in engine.agents}


def test_rumeur_circule_sans_la_personne_visee():
    engine, events = make()
    gossip = engine.gossip
    gossip.rng = random.Random(3)
    marc = engine.agent_by_id("pere")
    engine.remember(marc, "Léa est rentrée en retard hier soir sans rien dire.", 7)
    gossip._start_rumor([marc, engine.agent_by_id("mere")])
    rumor = gossip.rumors[0]
    assert rumor.subject == "ado" and "ado" not in rumor.versions
    assert any(e.kind == "rumeur" for e in events)
    assert "rumeur" in engine.dialogue_context([marc, engine.agent_by_id("enfant")])
    assert "rumeur" not in engine.dialogue_context([marc, engine.agent_by_id("ado")])


def test_rumeur_decouverte_fache():
    engine, events = make()
    gossip = engine.gossip
    gossip.rng = random.Random(0)
    gossip.rumors = [Rumor(subject="ado", subject_name="Léa", origin="pere", minute=engine.clock.total_minutes,
                           versions={"pere": "Léa a un chum en cachette."})]
    before = engine.agent_by_id("ado").relation("pere").tension
    for _ in range(40):
        talk(engine, "pere", "ado")
    lea = engine.agent_by_id("ado")
    assert lea.relation("pere").tension > before and any(e.kind == "rumeur_decouverte" for e in events)


def test_rumeur_deformee_par_l_ia(monkeypatch):
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 1000, 1)
    engine, _events = make(llm)
    gossip = engine.gossip
    monkeypatch.setattr(G, "RUMOR_DISTORT", 1.0)
    monkeypatch.setattr(G, "RUMOR_PASS", 1.0)
    monkeypatch.setattr(G, "RUMOR_START", 0.0)
    gossip.rumors = [Rumor(subject="ado", subject_name="Léa", origin="pere", minute=engine.clock.total_minutes,
                           versions={"pere": "Léa a raté son examen."})]
    talk(engine, "pere", "mere")
    deadline = time.monotonic() + 3
    while gossip.pending_rumors and time.monotonic() < deadline:
        engine.poll()
        time.sleep(0.005)
    rumor = gossip.rumors[0]
    assert rumor.versions["mere"].startswith("Paraît que") and rumor.distortions == 1
    llm.shutdown()


def test_sauvegarde_fete_et_rumeurs(tmp_path):
    engine, _ = make()
    julie = engine.agent_by_id("mere")
    engine.gossip._create(julie, engine.clock.day + 2, "", PartyIdea(title="Soirée jeux", hour=19))
    engine.gossip.rumors = [Rumor(subject="ado", subject_name="Léa", origin="pere", minute=engine.clock.total_minutes,
                                  versions={"pere": "x"})]
    path = tmp_path / "save.json"
    engine.save_state(path)
    other, _ = make()
    other.load_state(path)
    assert other.gossip.party.title == "Soirée jeux" and other.gossip.rumors[0].subject == "ado"
