"""Personnages lisses : images par direction et posture, taille enfant, éclairage, rendu dans la carte."""

import random

import pygame

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from ui import pawns
from ui.renderer import Renderer
from world.house import House


def test_images_par_direction_et_posture():
    pygame.init()
    family = load_family("data/family.yaml")
    adult, child = family[0], family[3]
    for direction in ("down", "up", "left", "right"):
        for sitting in (False, True):
            image = pawns.pawn_image(adult, direction, sitting, 40)
            assert image.get_height() == 40 and image.get_at((image.get_width() // 2, 30)).a > 0
    assert pawns.pawn_height(child) < pawns.pawn_height(adult)
    assert pawns.pawn_image(adult, "down", False, 40) is pawns.pawn_image(adult, "down", False, 40)  # en cache


def test_la_nuit_assombrit():
    pygame.init()
    image = pawns.pawn_image(load_family("data/family.yaml")[0], "down", False, 40)
    point = (image.get_width() // 2, 30)
    dark = pawns.lit(image, 0.5)
    assert sum(dark.get_at(point)[:3]) < sum(image.get_at(point)[:3])
    assert dark.get_at(point).a == image.get_at(point).a
    assert pawns.lit(image, 0.0) is image


def test_rendu_dans_la_carte():
    pygame.init()
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(1, "20:30"), random.Random(1))
    engine.initialize()
    renderer = Renderer(engine.house, 2.0, (800, 600))
    screen = pygame.Surface((800, 600))
    renderer.update_display(agents, 1 / 60)
    renderer.draw(screen, agents, agents[0].id, engine.clock.minute_of_day)
    assert len(renderer._pawn_jobs) == sum(1 for a in agents if not a.is_away and renderer._pose(a) != "lying")
