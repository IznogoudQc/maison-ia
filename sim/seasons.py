"""Saisons du Québec : neige à pelleter, chauffage, temps des sucres, Halloween, Noël et blues de février.

La date vient du calendrier (sim/calendrier.py) : partie commencée en juin, l'hiver arrive en décembre.
Chaque matin, la météo du jour est tirée (reproductible) : en saison de neige, il neige parfois ; la neige
s'accumule au sol et dans l'entrée, qu'il faut pelleter (dès 13 ans). Le chauffage coûte de l'argent à la
maison, et des bûches au terrain (sans bûches ou sous la tente, on gèle). Le rendu suit : feuilles
colorées l'automne, arbres nus l'hiver, terrain blanc sous la neige.
"""

from __future__ import annotations

import random
from datetime import date
from typing import TYPE_CHECKING

from agents.actions import Option

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

HEATING_PER_DAY = {11: 4.0, 12: 8.0, 1: 10.0, 2: 9.0, 3: 6.0, 4: 3.0}   # maison : $ de chauffage par jour
LOGS_PER_DAY = {11: 1, 12: 2, 1: 2, 2: 2, 3: 1}                         # terrain : bûches au poêle par jour
SNOW_CHANCE = 0.35            # par jour, en saison de neige
SHOVEL_FROM = 25              # l'entrée est à pelleter à partir de cette hauteur (cm)
SHOVEL_HOURS = (7 * 60, 19 * 60)
STORM_CM = 15                 # une bordée qui fait jaser
BLUES_FUN_PER_HOUR = 1.0      # février (et le froid) : le moral baisse plus vite
SUGAR_SEASON = ((3, 20), (4, 20))
CABANE_PRICE = 25.0           # par personne : sortie à la cabane à sucre (maison)
GIFTS_PER_PERSON = 60.0       # cadeaux de Noël
SEASON_LABELS = {"hiver": "l'hiver", "printemps": "le printemps", "ete": "l'été", "automne": "l'automne"}


def season_of(day: date) -> str:
    """hiver, printemps, ete, automne (dates usuelles des équinoxes et solstices)."""
    key = (day.month, day.day)
    if key >= (12, 21) or key < (3, 20):
        return "hiver"
    if key < (6, 21):
        return "printemps"
    if key < (9, 22):
        return "ete"
    return "automne"


def foliage_of(day: date) -> str:
    """Feuillage des arbres : ete, automne (couleurs), nu (novembre à avril), printemps (vert tendre)."""
    key = (day.month, day.day)
    if (9, 20) <= key <= (10, 31):
        return "automne"
    if key >= (11, 1) or key <= (4, 30):
        return "nu"
    if key <= (6, 10):
        return "printemps"
    return "ete"


def snow_season(day: date) -> bool:
    return day.month in (12, 1, 2) or (day.month == 11 and day.day >= 20) or (day.month == 3 and day.day <= 25)


def sugar_season(day: date) -> bool:
    return SUGAR_SEASON[0] <= (day.month, day.day) <= SUGAR_SEASON[1]


class Seasons:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.snow = 0.0              # cm au sol
        self.driveway = 0.0          # cm dans l'entrée (à pelleter)
        self.cold = False            # pas de chauffage aujourd'hui (terrain : tente ou plus de bûches)
        self.weather_day = -1
        self.done: dict[str, int] = {}   # fête de saison -> dernière année faite (Halloween, Noël, cabane)

    @property
    def today(self) -> date:
        return self.engine.calendar.date(self.engine.clock.day)

    @property
    def foliage(self) -> str:
        return foliage_of(self.today)

    # ------------------------------------------------------------------ chaque minute

    def update(self) -> None:
        engine = self.engine
        clock = engine.clock
        if clock.minute_of_day >= 5 * 60 and self.weather_day != clock.day:
            self.weather_day = clock.day
            self._daily(clock.day)
        today = self.today
        minute = clock.minute_of_day
        if (today.month, today.day) == (10, 31) and minute >= 18 * 60:
            self._once("halloween", self._halloween)
        if (today.month, today.day) == (12, 24) and minute >= 19 * 60:
            self._once("noel", self._christmas)
        if sugar_season(today) and clock.weekday >= 5 and minute >= 11 * 60:
            self._once("sucres", self._sugar_shack)
        if today.month == 2 or self.cold:
            hours = clock.tick_minutes / 60
            loss = BLUES_FUN_PER_HOUR * hours * (2 if self.cold else 1)
            for agent in engine.agents:
                if agent.is_available and not agent.is_sleeping:
                    agent.needs.apply({"fun": -loss})
                if self.cold and not agent.dead and not agent.is_away:
                    agent.needs.apply({"energy": -1.5 * hours})

    def _once(self, key: str, action) -> None:
        year = self.today.year
        if self.done.get(key) != year:
            self.done[key] = year
            action()

    def _daily(self, day: int) -> None:
        engine = self.engine
        today = engine.calendar.date(day)
        luck = random.Random(f"meteo:{day}")
        if snow_season(today) and luck.random() < SNOW_CHANCE:
            cm = luck.randint(3, 30)
            self.snow = min(120.0, self.snow + cm)
            self.driveway = min(120.0, self.driveway + cm)
            if cm >= STORM_CM:
                engine.publish("neige", cm=cm, text=f"Bordée de neige : {cm} cm cette nuit !")
                for agent in engine.agents:
                    if agent.is_available:
                        engine.remember(agent, f"Il est tombé {cm} cm de neige cette nuit : tout est blanc.", 4)
        elif not snow_season(today):
            melt = 25.0 if today.month in (3, 4, 11) else 60.0
            self.snow = max(0.0, self.snow - melt)
            self.driveway = max(0.0, self.driveway - melt)
        elif today.month == 3:
            self.snow = max(0.0, self.snow - 4)   # le soleil de mars commence à faire fondre
        self._heat(today)

    def _heat(self, today: date) -> None:
        engine = self.engine
        now = engine.clock.total_minutes
        was_cold, self.cold = self.cold, False
        if not engine.economy.enabled:
            return
        if not engine.house.layout.wild:
            cost = HEATING_PER_DAY.get(today.month, 0.0)
            if cost:
                engine.economy.transaction(now, "Chauffage (électricité)", -cost)
            return
        logs = LOGS_PER_DAY.get(today.month, 0)
        if not logs:
            return
        household = engine.economy.household
        if not engine.has_roof():
            self.cold = today.month in (12, 1, 2)
        elif household.wood >= logs:
            household.wood -= logs
        else:
            household.wood = 0
            self.cold = True
        if self.cold and not was_cold:
            text = ("On gèle sous la tente : il faut une maison avant le gros de l'hiver."
                    if not engine.has_roof() else "Plus de bûches pour le poêle : la maison est froide.")
            engine.publish("froid", text=text)
            for agent in engine.agents:
                if not agent.dead:
                    engine.remember(agent, text, 6)

    # ------------------------------------------------------------------ fêtes de saison

    def _halloween(self) -> None:
        engine = self.engine
        for kid in engine.agents:
            if kid.is_available and kid.persona.stage in ("enfant", "ado"):
                kid.needs.apply({"fun": 40, "hunger": 10})
                engine.remember(kid, "J'ai passé l'Halloween déguisé dans le quartier : un plein sac de bonbons !", 6)
            elif kid.is_available and kid.persona.is_adult:
                engine.remember(kid, "Soir d'Halloween : citrouille sur la galerie et bonbons à la porte.", 4)
        engine.publish("fete_saison", text="Halloween : déguisements et bonbons !")

    def _christmas(self) -> None:
        engine = self.engine
        present = [a for a in engine.agents if not a.dead and not a.is_away]
        for agent in present:
            agent.needs.apply({"fun": 30, "social": 30})
            engine.remember(agent, "Réveillon de Noël en famille : tourtière, cadeaux et chansons.", 7)
        if engine.economy.enabled and present:
            engine.economy.transaction(engine.clock.total_minutes, "Cadeaux de Noël", -GIFTS_PER_PERSON * len(present))
        engine.publish("fete_saison", text="Joyeux Noël ! Réveillon en famille.")

    def _sugar_shack(self) -> None:
        engine = self.engine
        present = [a for a in engine.agents if a.is_available]
        if not present:
            return
        if engine.house.layout.wild and engine.house.objects_of_kind("erabliere"):
            text = "C'est le temps des sucres : l'eau d'érable coule à la cabane du terrain !"
        else:
            text = "Sortie à la cabane à sucre : oreilles de crisse, tire sur la neige et danse en ligne."
            if engine.economy.enabled:
                engine.economy.transaction(engine.clock.total_minutes, "Cabane à sucre",
                                           -CABANE_PRICE * len(present))
        for agent in present:
            agent.needs.apply({"fun": 25, "hunger": 30, "social": 15})
            engine.remember(agent, text, 6)
        engine.publish("fete_saison", text=text)

    # ------------------------------------------------------------------ pelletage

    def options_for(self, agent: Agent) -> list[Option]:
        engine = self.engine
        if (self.driveway < SHOVEL_FROM or agent.persona.age < 13 or agent.visitor
                or not SHOVEL_HOURS[0] <= engine.clock.minute_of_day < SHOVEL_HOURS[1]
                or any(a.action is not None and a.action.name == "pelleter" for a in engine.agents)):
            return []
        score = round(6 + min(self.driveway, 80) / 3, 2)
        return [Option(action="pelleter", label=f"pellette l'entrée ({self.driveway:.0f} cm)", score=score)]

    def shovel_spot(self) -> tuple[int, int]:
        house = self.engine.house
        tiles = [p for p in house.walkable_tiles() if house.is_outdoor(p) and house.surface_at(p) is not None]
        if tiles:
            return self.engine.rng.choice(tiles)
        return house.objects_of_kind("porte")[0].use_positions[0]

    def shoveled(self, agent: Agent) -> None:
        self.driveway = 0.0
        self.engine.remember(agent, "J'ai pelleté l'entrée. Mon dos s'en souvient.", 2)

    def boost(self, options: list[Option]) -> None:
        """Temps des sucres : la cabane du terrain attire tout le monde."""
        if sugar_season(self.today):
            for option in options:
                if option.action == "sucres":
                    option.score = round(option.score * 3, 2)

    def lawn_grows(self) -> bool:
        return foliage_of(self.today) != "nu" and self.snow <= 0

    # ------------------------------------------------------------------ prompts, rendu, sauvegarde

    def context_line(self) -> str:
        today = self.today
        parts = [f"Saison : {SEASON_LABELS[season_of(today)]}"]
        if self.snow >= 5:
            parts.append(f"{self.snow:.0f} cm de neige au sol")
        if self.driveway >= SHOVEL_FROM:
            parts.append("l'entrée est à pelleter")
        if self.cold:
            parts.append("on gèle, pas de chauffage")
        if today.month == 2:
            parts.append("février est long, on manque de soleil")
        if sugar_season(today):
            parts.append("c'est le temps des sucres")
        if today.month == 10 and today.day >= 20:
            parts.append("l'Halloween s'en vient")
        if today.month == 12 and 10 <= today.day <= 24:
            parts.append("Noël approche")
        return " ; ".join(parts) + "."

    def hud_line(self) -> str:
        line = f"Saison : {SEASON_LABELS[season_of(self.today)]}"
        if self.snow >= 1:
            line += f"   Neige : {self.snow:.0f} cm"
        if self.driveway >= SHOVEL_FROM:
            line += " (entrée à pelleter)"
        return line

    def to_dict(self) -> dict:
        return {"snow": self.snow, "driveway": self.driveway, "cold": self.cold, "weather_day": self.weather_day,
                "done": self.done}

    def load_dict(self, data: dict | None) -> None:
        data = data or {}
        self.snow = float(data.get("snow", 0.0))
        self.driveway = float(data.get("driveway", 0.0))
        self.cold = bool(data.get("cold", False))
        self.weather_day = int(data.get("weather_day", -1))
        self.done = {k: int(v) for k, v in data.get("done", {}).items()}
