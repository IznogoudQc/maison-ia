"""Lot G3 : nouveaux objets (activités, dessins, récoltes) et le chien à promener."""

import random

import pygame
import pytest

from agents.actions import ACTIONS
from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import EventBus
from sim.food import FOODS
from sim.inventory import load_catalogue
from ui import living, sprites
from world.house import House, InteractiveObject


@pytest.fixture
def engine():
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(5, "16:00"), random.Random(1), EventBus())
    engine.initialize()
    engine.economy.household.money = 50_000.0
    return engine


def buy(engine, target):
    engine.economy.household.last_item_day = -1
    engine.inventory.buy(engine.agent_by_id("pere"), target)
    return engine.economy.household.items[-1]


def test_chaque_type_a_une_activite_et_un_dessin():
    kinds = {a.object_kind for a in ACTIONS.values()}
    for item in load_catalogue().values():
        if item.type not in ("deco", "lit"):
            assert item.type in kinds, item.id
            assert item.type in sprites.KIND_DRAWERS, item.id
        if item.recolte:
            assert item.recolte in FOODS, item.id


def test_les_nouveaux_objets_se_dessinent():
    pygame.init()
    surf = pygame.Surface((200, 200))
    for item in load_catalogue().values():
        label = item.label.removeprefix("un ").removeprefix("une ").removeprefix("des ").capitalize()
        w, h = item.taille
        sprites.draw_object(surf, InteractiveObject(item.id, item.type, label, "Salon", (1, 1, w, h), [], 1.0))
    living.draw_dog(surf, (50, 50), 3.0, 1.3, -1)


def test_babyfoot_ouvre_une_activite(engine):
    pere = engine.agent_by_id("pere")
    owned = buy(engine, "babyfoot|Salon|")
    assert owned.item_id == "babyfoot" and owned.object_id in engine.house.objects
    pere.action = None
    assert any(o.action == "babyfoot" for o in engine.options_for(pere))


def test_la_ruche_donne_du_miel(engine):
    buy(engine, "ruche|exterieur|")
    engine.economy.household.last_harvest_day = -1
    engine.inventory.update()
    assert any(s.food == "miel" for s in engine.economy.household.foods)


def test_le_chien_veut_sa_marche(engine):
    pere = engine.agent_by_id("pere")
    buy(engine, "chien|exterieur|")
    household = engine.economy.household
    household.dog_walk_day = engine.clock.day - 1  # pas encore sorti aujourd'hui
    pere.action = None
    walk = next(o for o in engine.options_for(pere) if o.action == "promener")
    assert "attend sa marche" in walk.label and walk.score > 14
    engine.inventory.walked(pere)
    assert engine.inventory.dog_walked_today()
    assert "eu sa marche" in engine.inventory.context_line()


def test_chien_oublie_fait_un_degat(engine):
    buy(engine, "chien|exterieur|")
    household = engine.economy.household
    household.dog_walk_day = engine.clock.day - 3
    household.last_harvest_day = -1
    engine.clock.total_minutes = engine.clock.day * 24 * 60 + 8 * 60
    engine.inventory.update()
    mere = engine.agent_by_id("mere")
    assert any("dégât" in m.text for m in mere.memory.events)
    engine.inventory._dog_check()  # le même matin : un seul dégât
    assert sum("dégât" in m.text for m in mere.memory.events) == 1
