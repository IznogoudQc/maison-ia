"""Historique persistant et écran Journal : alimentation, filtres, sauvegarde, export HTML."""

import random
import time

import pygame
import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import EventBus
from ui.journal import JournalScreen
from world.house import House


@pytest.fixture(scope="module")
def played():
    """Une journée de la famille Gagnon avec le LLM simulé."""
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=3), 100_000, 2)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(0, "06:00"), random.Random(3), EventBus(), llm)
    engine.initialize()
    while engine.clock.total_minutes < parse_hhmm("22:00"):
        engine.tick()
        deadline = time.monotonic() + 1
        while (engine.pending_decisions or engine.pending_dialogues or engine.pending_summaries
               or engine.mind.busy() or engine.social.busy()) and time.monotonic() < deadline:
            engine.poll()
            time.sleep(0.0003)
    yield engine
    llm.shutdown()


def test_l_historique_garde_les_quatre_sortes_de_moments(played):
    categories = {e.category for e in played.history.entries}
    assert {"conversation", "action", "pensee"} <= categories
    talk = next(e for e in played.history.entries if e.category == "conversation")
    assert len(talk.who) >= 2 and talk.lines and " : " in talk.lines[0]
    assert not any(e.category == "action" and "dort" in e.title and not e.lines for e in played.history.entries)


def test_filtres_par_onglet_personne_et_mot(played):
    history = played.history
    julie = history.filtered(person="Julie")
    assert julie and all("Julie" in e.who for e in julie)
    plans = history.filtered("pensee")
    assert plans and all(e.category == "pensee" for e in plans)
    word = plans[0].title.split()[0].lower()
    assert all(word in e.text() for e in history.filtered(search=word))


def test_sauvegarde_et_export_html(played, tmp_path):
    played.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, House(), agents, SimClock(), random.Random(1), EventBus())
    other.load_state(tmp_path / "save.json")
    assert len(other.history.entries) == len(played.history.entries)
    page = other.history.export_html(tmp_path / "chronique.html").read_text(encoding="utf-8")
    assert "<h2>Jour 1" in page and "Conversations" in page


def test_ecran_journal_au_clavier(played, tmp_path):
    screen = JournalScreen(played.history, tmp_path / "chronique.html")
    key = lambda k, u="": pygame.event.Event(pygame.KEYDOWN, key=k, unicode=u)  # noqa: E731
    assert not screen.handle_key(key(pygame.K_TAB))   # fermé : le jeu garde la touche
    screen.toggle()
    assert screen.handle_key(key(pygame.K_TAB)) and screen.tab == 1
    screen.handle_key(key(pygame.K_p))
    assert screen.person is not None
    screen.handle_key(key(pygame.K_SLASH, "/"))
    for char in "jas":
        screen.handle_key(key(pygame.K_a, char))
    assert screen.typing and screen.search == "jas"
    screen.handle_key(key(pygame.K_RETURN))
    screen.handle_key(key(pygame.K_e, "e"))
    assert (tmp_path / "chronique.html").exists() and "exportée" in screen.message
    screen.handle_key(key(pygame.K_ESCAPE))
    assert not screen.open
