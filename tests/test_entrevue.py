"""Entrevue : poser une question à un personnage, lui souffler une idée, l'écran de saisie (touche T)."""

import random
import time

import pygame

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from ui.interview import InterviewScreen
from world.house import House


def make():
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 1000, 1)
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(2, "19:00"), random.Random(1), bus, llm)
    engine.initialize()
    return engine, events, llm


def wait(engine, agent_id):
    deadline = time.monotonic() + 3
    while engine.interviews.busy(agent_id) and time.monotonic() < deadline:
        engine.poll()
        time.sleep(0.005)


def test_question_repondue_avec_ses_souvenirs():
    engine, events, llm = make()
    julie = engine.agent_by_id("mere")
    engine.remember(julie, "Léa a claqué la porte de sa chambre.", 7)
    before = len(julie.memory.events)
    seen = []
    submit = engine.llm.try_submit
    engine.llm.try_submit = lambda request, *a, **k: seen.append(request) or submit(request, *a, **k)
    exchange = engine.interviews.ask(julie, "Comment ça va avec Léa ?")
    assert exchange is not None and engine.interviews.busy(julie.id)
    assert engine.interviews.ask(julie, "Autre chose ?") is None             # une question à la fois
    assert "Léa a claqué la porte" in seen[0].prompt and seen[0].prefix.startswith("QUI JE SUIS")
    wait(engine, julie.id)
    assert "Léa a claqué la porte" in exchange.answer
    assert len(julie.memory.events) == before                                 # une question ne laisse pas de souvenir
    assert any(e.kind == "entrevue" for e in events)
    entry = next(e for e in engine.history.entries if e.title == "Entrevue avec Julie")
    assert entry.lines[0] == "Toi : Comment ça va avec Léa ?"
    llm.shutdown()


def test_idee_soufflee_reste_en_tete():
    engine, events, llm = make()
    pere = engine.agent_by_id("pere")
    engine.interviews.ask(pere, "organiser un souper avec les voisins", whisper=True)
    assert any("organiser un souper" in m.text and m.importance == 6 for m in pere.memory.events)
    assert pere.plan_stale and "souper" in pere.plan_stale
    wait(engine, pere.id)
    assert any(m.text.startswith("Je me suis dit") for m in pere.memory.events)
    assert any(e.kind == "souffle" for e in events)
    llm.shutdown()


def test_ecran_de_saisie():
    pygame.init()
    engine, _, llm = make()
    screen = InterviewScreen(engine)
    key = lambda k: pygame.event.Event(pygame.KEYDOWN, key=k, unicode="")  # noqa: E731
    assert not screen.handle_key(key(pygame.K_a))
    screen.show("ado")
    screen.handle_text("t")                                                    # la touche qui a ouvert l'écran
    for char in "Ça va, Léa ?":
        screen.handle_text(char)
    assert screen.text == "Ça va, Léa ?"
    screen.handle_key(key(pygame.K_TAB))
    assert screen.whisper
    screen.handle_key(key(pygame.K_TAB))
    screen.handle_key(key(pygame.K_RETURN))
    assert screen.text == "" and engine.interviews.history("ado")
    surface = pygame.Surface((1000, 640))
    screen.draw(surface, surface.get_rect())
    screen.handle_key(key(pygame.K_ESCAPE))
    assert not screen.open
    llm.shutdown()
