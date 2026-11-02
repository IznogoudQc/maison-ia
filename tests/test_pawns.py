"""Personnages lisses : images par direction et posture, taille enfant, éclairage, rendu dans la carte."""

import random

import pygame

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from ui import pawns, props
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
    kinds = [job[1] for job in renderer._pawn_jobs]
    lying = [a for a in agents if not a.is_away and renderer._pose(a) == "lying" and a.bed_id != "tente"]
    assert kinds.count("dormeur") == len(lying)
    assert kinds.count("pion") == sum(1 for a in agents if not a.is_away and renderer._pose(a) != "lying")


def test_meubles_et_arbres_lisses():
    pygame.init()
    house = House()
    keys = {obj.id: props.prop_key(obj) for obj in house.objects.values()}
    assert keys["lit_parents"][0] == "lit" and keys["canape"][0] == "canape" and keys["arbre_1"][0] == "arbre"
    assert all(key is not None for key in keys.values()), [i for i, k in keys.items() if k is None]  # tout est lisse
    for key in filter(None, keys.values()):
        image = props.prop_image(key, 2.0)
        x0, y0, x1, y1 = props.bounds(key)
        assert image.get_size() == (round((key[1] * 16 + x1 - x0) * 2), round((key[2] * 16 + y1 - y0) * 2))
        assert any(image.get_at((x, image.get_height() // 2)).a for x in range(image.get_width()))


def test_tout_le_catalogue_est_lisse():
    from sim.inventory import load_catalogue
    from world.house import InteractiveObject
    for item in load_catalogue().values():
        label = item.label.removeprefix("un ").removeprefix("une ").removeprefix("des ").capitalize()
        obj = InteractiveObject(f"objet_{item.id}", item.type, label, "Salon", (0, 0, *item.taille), [], item.qualite)
        assert props.prop_key(obj) is not None, item.id
    for model in ("compacte", "vus", "pickup", "moto", "vtt", "velo"):
        key = props.prop_key(InteractiveObject(f"vehicule_{model}_1", "vehicule", "Auto", "Cour", (0, 0, 2, 3), []))
        assert key == ("vehicule", 2, 3, model) and props.prop_image(key, 2.0).get_width() == (2 * 16 + 3) * 2


def test_elements_animes():
    from ui import living
    pygame.init()
    screen = pygame.Surface((300, 300))
    persona = load_family("data/family.yaml")[0]
    living.draw_dog(screen, (50, 50), 3.0, 1.2, -1, (0.3, None))
    living.draw_baby(screen, persona, (100, 50), 3.0, True)
    living.draw_swimmer(screen, persona, (150, 50), 3.0, 0.7)
    for name in ("telephone", "livre", "lego", "tondeuse", "marteau", "hache", "tasse"):
        living.draw_tool(screen, name, (60, 150), 3.0, 0.4, chainsaw=name == "hache")
    living.draw_flames(screen, (200, 150), 3.0, 0.4)
    living.draw_steam(screen, (250, 150), 3.0, 0.4)
    living.draw_ribbon(screen, (250, 250), 3.0)
    assert screen.get_at((50, 46)) != screen.get_at((5, 5))   # le chien est bien dessiné
