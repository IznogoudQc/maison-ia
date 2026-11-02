"""Saisons : neige et pelletage, chauffage, Halloween, Noël, temps des sucres, février, rendu de l'hiver."""

import os
import random
from datetime import date

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.seasons import foliage_of, season_of, snow_season
from world.house import House
from world.terrain import build_house


def make(when: date, start="04:50", scenario="maison"):
    config = load_config("config.yaml", scenario=scenario)
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    first = date.fromisoformat(config.world.date_depart)
    house = House() if scenario == "maison" else build_house("terrain", 60, 50, 42, 0.1)
    engine = Engine(config, house, agents, SimClock((when - first).days, start), random.Random(1), bus, None)
    engine.initialize()
    engine.visitors.known.clear()   # pas de visite ni de fête au hasard
    return engine, events


def test_saisons_et_feuillage():
    assert season_of(date(2026, 7, 1)) == "ete" and season_of(date(2027, 1, 15)) == "hiver"
    assert season_of(date(2026, 10, 1)) == "automne" and season_of(date(2027, 4, 10)) == "printemps"
    assert foliage_of(date(2026, 10, 5)) == "automne" and foliage_of(date(2026, 12, 5)) == "nu"
    assert foliage_of(date(2027, 5, 20)) == "printemps" and foliage_of(date(2026, 8, 1)) == "ete"
    assert snow_season(date(2027, 1, 3)) and not snow_season(date(2026, 7, 3))


def test_neige_qui_s_accumule_et_pelletage():
    engine, events = make(date(2026, 12, 1))
    seasons = engine.seasons
    while seasons.snow < 25:
        for _ in range(24 * 60 // engine.clock.tick_minutes):
            engine.tick()
    assert seasons.driveway >= 0 and "neige au sol" in engine.dialogue_context(engine.agents)
    seasons.driveway = 40
    engine.clock.total_minutes = engine.clock.day * 24 * 60 + 10 * 60
    marc = engine.agent_by_id("pere")
    marc.action = None
    options = engine.options_for(marc)
    assert any(o.action == "pelleter" for o in options)
    assert not any(o.action == "pelleter" for o in engine.options_for(engine.agent_by_id("enfant")))
    action = engine.make_action(marc, "pelleter", None)
    assert engine.start_action(marc, action)
    for _ in range(120):
        engine.tick()
        if seasons.driveway == 0:
            break
    assert seasons.driveway == 0 and any("pelleté" in e.text for e in marc.memory.events)


def test_chauffage_et_gazon_qui_dort():
    engine, _ = make(date(2027, 1, 10))
    money = engine.economy.household.money
    lawn = engine.economy.household.lawn
    for _ in range(30 // engine.clock.tick_minutes + 2):
        engine.tick()
    ledger = [e.label for e in engine.economy.household.ledger]
    assert "Chauffage (électricité)" in ledger and engine.economy.household.money < money
    assert engine.economy.household.lawn == lawn


def test_halloween_et_noel():
    engine, events = make(date(2026, 10, 31), start="17:55")
    for _ in range(10):
        engine.tick()
    felix = engine.agent_by_id("enfant")
    assert any("bonbons" in e.text for e in felix.memory.events) and any(e.kind == "fete_saison" for e in events)
    engine, events = make(date(2026, 12, 24), start="18:55")
    for _ in range(10):
        engine.tick()
    assert any("Réveillon" in e.text for e in engine.agent_by_id("mere").memory.events)
    assert any(e.label == "Cadeaux de Noël" for e in engine.economy.household.ledger)


def test_cabane_a_sucre_la_fin_de_semaine():
    engine, events = make(date(2027, 3, 27), start="10:55")   # un samedi du temps des sucres
    assert engine.clock.weekday >= 5
    for _ in range(10):
        engine.tick()
    assert any("cabane à sucre" in e.text for e in engine.agent_by_id("mere").memory.events)
    assert "temps des sucres" in engine.dialogue_context(engine.agents)


def test_blues_de_fevrier():
    engine, _ = make(date(2027, 2, 10), start="20:00")
    other, _ = make(date(2027, 5, 10), start="20:00")
    for e in (engine, other):
        e.seasons.weather_day = e.clock.day
        julie = e.agent_by_id("mere")
        julie.away_until, julie.action, julie.needs.fun = None, None, 50.0
        for _ in range(60):
            e.seasons.update()
    assert engine.agent_by_id("mere").needs.fun < other.agent_by_id("mere").needs.fun == 50.0
    assert "février" in engine.dialogue_context(engine.agents)


def test_terrain_sous_la_tente_on_gele():
    engine, events = make(date(2027, 1, 5), scenario="terrain")
    for _ in range(30 // engine.clock.tick_minutes + 2):
        engine.tick()
    assert engine.seasons.cold and any(e.kind == "froid" for e in events)


def test_sauvegarde_des_saisons(tmp_path):
    engine, _ = make(date(2026, 12, 15))
    engine.seasons.snow, engine.seasons.driveway, engine.seasons.done = 33.0, 20.0, {"noel": 2026}
    path = tmp_path / "save.json"
    engine.save_state(path)
    other, _ = make(date(2026, 12, 15))
    other.load_state(path)
    assert other.seasons.snow == 33.0 and other.seasons.done == {"noel": 2026}


def test_rendu_de_l_hiver():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from ui import props
    from ui.renderer import Renderer
    pygame.init()
    pygame.display.set_mode((10, 10))
    house = House()
    renderer = Renderer(house, 1.0, (320, 240))
    renderer.set_season("nu", 40, 40)
    surf = pygame.Surface((320, 240))
    renderer.draw(surf, [], None, 12 * 60)
    assert renderer._bg_key()[2] == 3
    bare = props.prop_image(("arbre", 1, 1, "Érable", "nu", True, 0), 2.0)
    leafy = props.prop_image(("arbre", 1, 1, "Érable", "ete", False, 0), 2.0)
    assert bare.get_size() == leafy.get_size()
    assert pygame.image.tobytes(bare, "RGBA") != pygame.image.tobytes(leafy, "RGBA")
