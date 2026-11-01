"""Fiche personnage : qualités et défauts, causes de l'humeur, avis sur chacun, voix de l'IA, écran P."""

import random
import time

import pygame
import pytest

from agents.agent import Agent
from agents.persona import load_family
from llm.mock_provider import MockProvider
from llm.portrait_prompts import OpinionLine, PortraitText, validate_portrait
from llm.prompts import persona_block
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import EventBus
from ui.portrait import PortraitScreen, character_rows
from world.house import House


@pytest.fixture
def setup():
    pygame.init()
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=2), 100_000, 2)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(2, "18:00"), random.Random(1), EventBus(), llm)
    engine.initialize()
    yield engine
    llm.shutdown()


def wait(engine):
    deadline = time.monotonic() + 3
    while engine.portraits.pending and time.monotonic() < deadline:
        engine.poll()
        time.sleep(0.005)


@pytest.mark.parametrize("scenario", ["maison", "terrain"])
def test_chacun_a_des_qualites_et_des_defauts(scenario):
    config = load_config("config.yaml", scenario=scenario)
    for persona in load_family(config.family_file):
        assert len(persona.qualites) >= 2 and len(persona.defauts) >= 2, persona.id
        agent = Agent(persona=persona, pos=(0, 0))
        block = persona_block(agent)
        assert "Qualités :" in block and "Défauts" in block
        assert any("Défauts" in text for text, _ in character_rows(agent))


def test_causes_de_l_humeur(setup):
    engine = setup
    julie, lea = engine.agent_by_id("mere"), engine.agent_by_id("ado")
    julie.needs.hunger, julie.needs.fun = 10, 95
    engine.economy.household.money = -300
    julie.relation("ado").tension = 75
    julie.relation("pere").affection = 90
    engine.remember(julie, "Léa a claqué la porte de sa chambre.", 7)
    causes = dict(engine.portraits.causes(julie))
    assert causes["Faim (satiété 10/100)"] == -1
    assert causes["Du plaisir aujourd'hui"] == 1
    assert causes["On est dans le rouge (-300 $)"] == -1
    assert causes["En chicane avec Léa"] == -1 and causes["Très proche de Stéphane"] == 1
    assert causes["Léa a claqué la porte de sa chambre."] == 0
    assert "On est dans le rouge (-300 $)" not in dict(engine.portraits.causes(lea))  # pas son souci


def test_avis_calcules_puis_voix_de_l_ia(setup):
    engine = setup
    julie = engine.agent_by_id("mere")
    julie.relation("ado").tension = 75
    plain = {o.other.name: o.text for o in engine.portraits.opinions(julie)}
    assert plain["Léa"] == "En chicane avec Léa." and set(plain) == {"Stéphane", "Léa", "Félix"}
    engine.portraits.request(julie)
    assert engine.portraits.thinking(julie)
    wait(engine)
    assert engine.portraits.feeling(julie)
    voiced = {o.other.name: o.text for o in engine.portraits.opinions(julie)}
    assert "nerfs" in voiced["Léa"]
    engine.portraits.request(julie)  # encore frais : pas de nouvel appel
    assert not engine.portraits.thinking(julie)


def test_validation_du_portrait():
    with pytest.raises(ValueError):
        validate_portrait(PortraitText(ressenti="  "), ["Léa"])
    ok = validate_portrait(PortraitText(ressenti="Ça va.", opinions=[OpinionLine(name="léa", text="Elle m'épuise."),
                                                                     OpinionLine(name="Bob", text="?")]), ["Léa"])
    assert [(o.name, o.text) for o in ok.opinions] == [("Léa", "Elle m'épuise.")]


def test_le_bebe_herite_des_parents(setup):
    engine = setup
    parents = [engine.agent_by_id("pere"), engine.agent_by_id("mere")]
    inherited = engine.family._inherit(parents, "defauts")
    assert len(inherited) == 2
    assert inherited[0] in parents[0].persona.defauts and inherited[1] in parents[1].persona.defauts


def test_ecran_fiche(setup):
    engine = setup
    screen = PortraitScreen(engine)
    key = lambda k: pygame.event.Event(pygame.KEYDOWN, key=k, unicode="")  # noqa: E731
    assert not screen.handle_key(key(pygame.K_TAB))
    screen.show("ado")
    assert screen.open and screen.agent_id == "ado"
    surface = pygame.Surface((960, 640))
    for _ in range(4):
        screen.draw(surface, surface.get_rect())
        screen.handle_key(key(pygame.K_TAB))
    assert screen.agent_id == "ado"
    screen.handle_key(key(pygame.K_p))
    assert not screen.open
