"""Point d'entrée : boucle pygame de la simulation Maison IA."""

from __future__ import annotations

import random

import pygame

from agents.agent import Agent
from agents.persona import load_family
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from ui import theme
from ui.hud import Hud
from ui.renderer import Renderer
from world.house import House

SPEED_KEYS = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3}
MAX_TICKS_PER_FRAME = 60


def main() -> None:
    config = load_config("config.yaml")
    rng = random.Random(config.sim.seed)

    house = House()
    personas = load_family(config.family_file)
    agents = [Agent(persona=p, pos=house.random_tile(rng)) for p in personas]
    clock = SimClock(config.sim.start_day, config.sim.start_time, config.sim.tick_minutes)
    engine = Engine(config, house, agents, clock, rng)

    pygame.init()
    pygame.display.set_caption("Maison IA — famille Gagnon")
    renderer = Renderer(house, config.display.tile_size)
    map_w, map_h = renderer.size
    screen = pygame.display.set_mode((map_w + config.display.hud_width, map_h))
    hud = Hud(pygame.Rect(map_w, 0, config.display.hud_width, map_h))
    frame_clock = pygame.time.Clock()

    speed_index = 0
    paused = False
    selected_id: str | None = None
    tick_accumulator = 0.0
    running = True

    while running:
        dt = frame_clock.tick(config.display.fps) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key in SPEED_KEYS:
                    speed_index = min(SPEED_KEYS[event.key], len(config.sim.speed_multipliers) - 1)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if event.pos[0] < map_w:
                    clicked = renderer.agent_at(agents, event.pos)
                    selected_id = clicked.id if clicked else None

        speed = config.sim.speed_multipliers[speed_index]
        if not paused:
            tick_accumulator += dt * config.sim.base_ticks_per_second * speed
            ticks = 0
            while tick_accumulator >= 1.0 and ticks < MAX_TICKS_PER_FRAME:
                engine.tick()
                tick_accumulator -= 1.0
                ticks += 1
            tick_accumulator = min(tick_accumulator, 1.0)  # évite la spirale de rattrapage

        renderer.update_display(agents, dt)
        screen.fill(theme.BACKGROUND)
        renderer.draw(screen, agents, selected_id)
        hud.draw(screen, clock, speed, paused)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
