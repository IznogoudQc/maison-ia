"""Écran Maison (touche I) : objets, véhicules, garde-manger, prêts et dépenses."""

import random

import pygame
import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.economy import Loan
from sim.engine import Engine
from sim.events import EventBus
from ui.household import TABS, HouseholdScreen
from world.house import House


@pytest.fixture
def engine():
    pygame.init()
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(5, "10:00"), random.Random(1), EventBus())
    engine.initialize()
    household = engine.economy.household
    household.money = 40_000.0
    pere = engine.agent_by_id("pere")
    for target in ("ruche|exterieur|", "chien|exterieur|", "panneaux_solaires|exterieur|"):
        household.last_item_day = -1
        engine.inventory.buy(pere, target)
    engine.garage.buy(pere, "compacte")
    engine.economy.add_food("steak", 4, engine.clock.day)
    household.loans.append(Loan(uid=1, purpose="vehicule", label="l'auto compacte", principal=6000, balance=4500,
                                rate=0.079, weeks_left=40, payment=120, missed=1))
    return engine


def texts(screen):
    return " | ".join(text for text, _ in screen.rows())


def test_chaque_onglet_resume_la_maison(engine):
    screen = HouseholdScreen(engine)
    expected = ["Ruche", "Compacte", "steaks", "Dossier de crédit", "Solde"]
    for tab, word in enumerate(expected):
        screen.tab = tab
        assert word.lower() in texts(screen).lower(), TABS[tab]
    screen.tab = 0
    assert "miel par jour" in texts(screen) and "chien" in texts(screen).lower()
    screen.tab = 2
    assert "préféré de Stéphane" in texts(screen)
    screen.tab = 3
    assert "1 paiement(s) manqué(s)" in texts(screen) and "4 500 $" in texts(screen)
    screen.tab = 4
    page = texts(screen)
    assert "Paiements de prêts : +120 $" in page and "Économie : des panneaux solaires : -30 $" in page


def test_clavier_et_dessin(engine):
    screen = HouseholdScreen(engine)
    key = lambda k: pygame.event.Event(pygame.KEYDOWN, key=k, unicode="")  # noqa: E731
    assert not screen.handle_key(key(pygame.K_TAB))   # fermé : le jeu garde la touche
    screen.toggle()
    surface = pygame.Surface((900, 600))
    for _ in TABS:
        screen.draw(surface, surface.get_rect())
        assert screen.handle_key(key(pygame.K_TAB))
    assert screen.tab == 0
    screen.handle_key(key(pygame.K_LEFT))
    assert screen.tab == len(TABS) - 1
    screen.handle_key(key(pygame.K_i))
    assert not screen.open


def test_maison_vide(engine):
    household = engine.economy.household
    household.items.clear()
    household.loans.clear()
    engine.garage.owned.clear()
    screen = HouseholdScreen(engine)
    assert "Rien d'acheté" in texts(screen)
    screen.tab = 1
    assert "autobus" in texts(screen)
    screen.tab = 3
    assert "Aucun prêt" in texts(screen)
