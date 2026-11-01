"""Infobulle au survol : objets achetés, mobilier, arbres, personnages."""

import os
import random

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from agents.agent import Agent  # noqa: E402
from agents.persona import load_family  # noqa: E402
from sim.clock import SimClock  # noqa: E402
from sim.config import load_config  # noqa: E402
from sim.engine import Engine  # noqa: E402
from ui.renderer import Renderer  # noqa: E402
from ui.sprites import TILE  # noqa: E402
from ui.tooltip import describe  # noqa: E402
from world.house import House  # noqa: E402
from world.terrain import build_house  # noqa: E402


def setup(scenario="maison"):
    pygame.init()
    config = load_config("config.yaml", scenario=scenario)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    house = House() if scenario == "maison" else build_house("terrain", 120, 80, 42)
    engine = Engine(config, house, agents, SimClock(5, "10:00"), random.Random(1))
    engine.initialize()
    renderer = Renderer(engine.house, 1.0)
    return engine, renderer


def mouse_on(tile):
    return tile[0] * TILE + TILE // 2, tile[1] * TILE + TILE // 2


def test_objet_achete_nom_utilite_et_prix():
    engine, renderer = setup()
    engine.economy.household.money = 10_000
    engine.inventory.buy(engine.agents[0], "piano|Salon|")
    owned = engine.economy.household.items[0]
    lines = describe(engine, renderer, mouse_on(owned.rect[:2]))
    assert lines[0].startswith("Piano") and "musique" in lines[1] and "3000 $" in lines[2]


def test_mobilier_et_arbre():
    engine, renderer = setup("terrain")
    tent = engine.house.objects["tente"]
    assert "dormir" in describe(engine, renderer, mouse_on(tent.rect[:2]))[1]
    tree = next(o for o in engine.house.objects.values() if o.kind == "arbre")
    assert "bûches" in describe(engine, renderer, mouse_on(tree.rect[:2]))[1]
