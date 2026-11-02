"""Mémoire v2 : familles de mots, réflexion en deux étapes avec sources, conclusion de fond, déclenchement par
importance, écran Flux de mémoire."""

import random
import time

import pygame

from agents.agent import Agent
from agents.memory import Memory, keywords
from agents.persona import load_family
from llm.mind_prompts import Insight, Reflection, validate_reflection
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.mind import REFLECT_THRESHOLD
from ui.portrait import PortraitScreen
from world.house import House


def make():
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 1000, 1)
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(2, "14:00"), random.Random(1), bus, llm)
    engine.initialize()
    engine.economy.add_food("lait", 20, engine.clock.day)
    return engine, events, llm


def wait(engine):
    deadline = time.monotonic() + 3
    while engine.mind.pending_reflections and time.monotonic() < deadline:
        engine.poll()
        time.sleep(0.005)


def test_familles_de_mots():
    assert "#argent" in keywords("Le budget est serré") & keywords("Ma paie rentre vendredi")
    assert "#travail" in keywords("Une offre de job") and "#ecole" in keywords("Faire mes devoirs")
    memory = Memory()
    for minute, text in enumerate(["Souper en famille.", "On a parlé du budget.", "Partie de hockey.",
                                   "Douche chaude.", "Au lit."]):
        memory.add(minute * 60, "10:00", text, importance=3)
    recalled = memory.retrieve(400, keywords("Ma paie est arrivée"), count=3)
    assert any("budget" in e.text for e in recalled)                         # même thème, autre mot


def test_validation_sources_et_conclusion_de_fond():
    reflection = Reflection(questions=["Pourquoi on se chicane ?"], important=[2],
                            insights=[Insight(text="Je suis à boutte.", importance=6, sources=[1, 9, 2])],
                            deep=Insight(text="Je dois ralentir.", importance=5, sources=[2, 7]))
    ok = validate_reflection(reflection, event_count=3, catalog=[], names={}, previous_count=4)
    assert ok.insights[0].sources == [1, 2] and ok.deep.sources == [2] and ok.deep.importance == 8
    no_previous = validate_reflection(reflection, event_count=3, catalog=[], names={}, previous_count=0)
    assert no_previous.deep is None


def test_journee_chargee_fait_reflechir_tout_de_suite():
    engine, events, llm = make()
    julie = engine.agent_by_id("mere")
    for text in ("Prime au travail !", "Chicane avec Léa.", "Félix est malade."):
        engine.remember(julie, text, 8)
    for text in ("Constat un.", "Constat deux.", "Constat trois."):
        engine.remember(julie, text, 5, kind="reflection")
    julie.memory.importance_since_reflection = REFLECT_THRESHOLD
    seen = []
    submit = engine.llm.try_submit
    engine.llm.try_submit = lambda request, *a, **k: seen.append(request) or submit(request, *a, **k)
    engine.mind.update(julie)
    assert julie.id in engine.mind.pending_reflections and julie.memory.importance_since_reflection == 0
    request = seen[0]
    assert "ÉTAPE 1" in request.prompt and "MES CONSTATS DES DERNIERS JOURS" in request.prompt
    assert "l'argent, la maison" not in request.system and "Dans le garde-manger" not in request.prompt
    wait(engine)
    reflection = next(e for e in events if e.kind == "reflexion")
    assert reflection.data["questions"] and reflection.data["deep"]
    assert any(m.text.startswith("Au fond :") for m in julie.memory.events)
    llm.shutdown()


def test_ecran_flux_de_memoire():
    pygame.init()
    engine, _, llm = make()
    engine.remember(engine.agent_by_id("pere"), "Un beau souvenir.", 7)
    engine.memories_for(engine.agent_by_id("pere"), ["souvenir"])
    screen = PortraitScreen(engine)
    screen.show("pere")
    screen.handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m, unicode="m"))
    assert screen.memory_view and engine.last_recall["pere"]
    surface = pygame.Surface((1000, 640))
    screen.draw(surface, surface.get_rect())
    llm.shutdown()
