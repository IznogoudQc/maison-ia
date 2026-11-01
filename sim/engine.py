"""Orchestration des ticks de simulation."""

from __future__ import annotations

import random

from agents.agent import Agent
from sim.clock import SimClock
from sim.config import AppConfig
from world.house import House


class Engine:
    def __init__(self, config: AppConfig, house: House, agents: list[Agent], clock: SimClock,
                 rng: random.Random) -> None:
        self.config = config
        self.house = house
        self.agents = agents
        self.clock = clock
        self.rng = rng

    def tick(self) -> None:
        self.clock.advance()
        for agent in self.agents:
            if not agent.is_walking:
                agent.set_destination(self.house.random_tile(self.rng), self.house.is_walkable)
            agent.walk(self.config.sim.move_tiles_per_tick)
            room = self.house.room_at(agent.pos)
            if room is not None:
                agent.last_room = room
