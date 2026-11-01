"""Événements aléatoires et situation familiale transmise au LLM."""

import json
import random

import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.prompts import build_decision_request, build_dialogue_request
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.random_events import EVENTS
from world.house import House

DAY = 24 * 60


def make_engine(frequency: float = 1.0, day: int = 0):
    config = load_config("config.yaml")
    config.events.frequency = frequency
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    eng = Engine(config, House(), agents, SimClock(day, "06:00"), random.Random(5), bus)
    eng.initialize()
    return eng, events


def run_until(eng, minute):
    while eng.clock.total_minutes < minute:
        eng.tick()


def test_frequence_zero_aucun_evenement():
    eng, events = make_engine(frequency=0.0)
    run_until(eng, 7 * DAY)
    # Les nouvelles de la cour (tonte, amende) ne sont pas aléatoires
    assert not any(e.kind == "evenement" and e.data["id"] != "cour" for e in events)


def test_au_plus_deux_evenements_par_jour_et_un_tirage_par_jour():
    eng, events = make_engine(frequency=100.0)
    run_until(eng, 3 * DAY)
    per_day: dict[int, int] = {}
    for e in events:
        if e.kind == "evenement":
            per_day[e.minute // DAY] = per_day.get(e.minute // DAY, 0) + 1
    assert per_day and all(count <= 2 for count in per_day.values())
    assert all(e.minute % DAY >= parse_hhmm("08:30") for e in events if e.kind == "evenement")


def test_mise_a_pied_empeche_d_aller_travailler():
    eng, events = make_engine(frequency=0.0)
    pere = eng.agent_by_id("pere")
    pere.unemployed_until = 2 * DAY
    run_until(eng, parse_hhmm("18:00"))
    # Il peut sortir faire l'épicerie, mais pas aller travailler
    assert not any(e.kind == "depart" and e.data["name"] == "Stéphane" and e.data["label"] == "travail"
                   for e in events)
    assert not any(e.kind == "paie" and e.data["name"] == "Stéphane" for e in events)
    assert all(o.action != "heures_sup" for o in eng.options_for(pere))
    run_until(eng, 2 * DAY + 1)
    assert pere.unemployed_until is None


def test_hausse_de_prix():
    eng, _ = make_engine()
    hike = next(e for e in EVENTS if e.id == "hausse_epicerie")
    text = hike.apply(eng, random.Random(0))
    assert eng.economy.portion_price() == pytest.approx(8.64)
    assert "8 %" in text


def test_evenement_memorise_par_toute_la_famille():
    eng, events = make_engine(frequency=100.0)
    run_until(eng, parse_hhmm("08:31"))
    news = [e for e in events if e.kind == "evenement"]
    assert news
    for agent in eng.agents:
        assert any("nouvelle" in m.text.lower() for m in agent.memory.events)


def test_contexte_familial_et_prompts():
    eng, _ = make_engine(frequency=0.0)
    eng.economy.household.money = -120.0
    eng.agent_by_id("pere").unemployed_until = eng.clock.total_minutes + 3 * DAY
    victim = eng.agent_by_id("enfant")
    victim.health, victim.needs.hunger = 0.01, 0.0
    eng.tick()
    mere = eng.agent_by_id("mere")
    context = eng.family_context([mere, eng.agent_by_id("pere")])
    assert "DETTE" in context and "Félix" in context and "mise à pied" in context and "deuil" in context

    request = build_decision_request(mere, "Cuisine", eng.clock.label(), eng.options_for(mere)[:3], [], None,
                                     500, context, eng._prompt_meta())
    assert "FAMILLE" in request.prompt and request.meta["departed"] == ["Félix"]
    dialogue = build_dialogue_request([mere, eng.agent_by_id("ado")], "Cuisine", eng.clock.label(), {}, {},
                                      500, context, eng._prompt_meta())
    assert "SITUATION DE LA FAMILLE" in dialogue.prompt


def test_mock_parle_du_deuil_et_de_l_argent():
    eng, _ = make_engine(frequency=0.0)
    group = [eng.agent_by_id("mere"), eng.agent_by_id("ado")]
    meta = {"money": -50.0, "pantry_days": 0.2, "departed": ["Félix"]}
    request = build_dialogue_request(group, "Salon", "midi", {}, {}, 500, "contexte", meta)
    provider = MockProvider((0.0, 0.0), 0.0, seed=1)
    texts = " ".join(line["text"] for _ in range(30)
                     for line in json.loads(provider.complete(request).text)["lines"])
    assert "Félix" in texts
    assert any(word in texts for word in ("budget", "rouge", "pauvres", "dépanneur", "ceinture"))
