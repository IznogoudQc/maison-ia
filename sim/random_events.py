"""Événements aléatoires quotidiens : coups durs et bonnes nouvelles."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sim.clock import MINUTES_PER_DAY, SimClock, parse_hhmm
from sim.config import EventsConfig

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.economy import Household
    from sim.engine import Engine

MAX_EVENTS_PER_DAY = 2


@dataclass(frozen=True)
class RandomEvent:
    id: str
    probability: float                                   # chance par jour
    good: bool
    apply: Callable[[Engine, random.Random], str | None]  # texte de l'événement, ou None s'il ne s'applique pas


def _laid_off(agent: Agent, now: int) -> bool:
    return agent.unemployed_until is not None and now < agent.unemployed_until


def _employed(engine: Engine) -> list[Agent]:
    now = engine.clock.total_minutes
    return [a for a in engine.agents if not a.dead and a.persona.salary_per_day > 0 and not _laid_off(a, now)]


def _layoff(engine: Engine, rng: random.Random) -> str | None:
    workers = _employed(engine)
    if not workers:
        return None
    agent = rng.choice(workers)
    days = rng.randint(5, 10)
    agent.unemployed_until = engine.clock.total_minutes + days * MINUTES_PER_DAY
    return f"Mise à pied pour {agent.name} : {days} jours sans salaire."


SURPRISE_BILLS = [
    ("Le dentiste de Félix", 250), ("Le plombier pour le chauffe-eau", 450),
    ("Des bottes d'hiver pour les enfants", 180), ("Une amende de stationnement", 75),
    ("Le vétérinaire pour le chat du voisin qu'on garde", 120),
]


def _surprise_bill(engine: Engine, rng: random.Random) -> str | None:
    choices = list(SURPRISE_BILLS)
    if "auto" in getattr(engine.economy.household, "purchases", []):
        choices.append(("La réparation de l'auto", 800))
    label, amount = rng.choice(choices)
    engine.economy.transaction(engine.clock.total_minutes, label, -amount)
    return f"Facture imprévue : {label[0].lower() + label[1:]} ({amount} $)."


def _price_hike(engine: Engine, rng: random.Random) -> str | None:
    household = engine.economy.household
    household.price_factor = round(household.price_factor * 1.08, 4)
    price = f"{engine.economy.portion_price():.2f}".replace(".", ",")
    return f"Le prix de l'épicerie a augmenté de 8 % (portion à {price} $)."


def _bonus(engine: Engine, rng: random.Random) -> str | None:
    workers = _employed(engine)
    if not workers:
        return None
    agent = rng.choice(workers)
    amount = rng.choice((250, 400, 500))
    engine.economy.transaction(engine.clock.total_minutes, f"Prime de {agent.name}", amount)
    return f"Prime au travail pour {agent.name} : +{amount} $."


def _tax_refund(engine: Engine, rng: random.Random) -> str | None:
    engine.economy.transaction(engine.clock.total_minutes, "Remboursement d'impôt", 600)
    return "Remboursement d'impôt : +600 $."


def _babysitting(engine: Engine, rng: random.Random) -> str | None:
    if engine.clock.weekday < 5:
        return None
    sitter = next((a for a in engine.agents if not a.dead and 13 <= a.persona.age < 18), None)
    if sitter is None:
        return None
    engine.economy.transaction(engine.clock.total_minutes, f"Gardiennage de {sitter.name}", 40)
    return f"{sitter.name} a gardé les enfants des voisins : +40 $ pour la famille."


def _grandma(engine: Engine, rng: random.Random) -> str | None:
    engine.economy.transaction(engine.clock.total_minutes, "Chèque de grand-maman", 100)
    return "Grand-maman a envoyé un chèque de 100 $."


EVENTS: list[RandomEvent] = [
    RandomEvent("mise_a_pied", 0.015, False, _layoff),
    RandomEvent("facture_imprevue", 0.06, False, _surprise_bill),
    RandomEvent("hausse_epicerie", 0.03, False, _price_hike),
    RandomEvent("prime", 0.03, True, _bonus),
    RandomEvent("impot", 0.01, True, _tax_refund),
    RandomEvent("gardiennage", 0.25, True, _babysitting),
    RandomEvent("grand_maman", 0.01, True, _grandma),
]


class RandomEvents:
    def __init__(self, config: EventsConfig) -> None:
        self.config = config

    def due(self, clock: SimClock, household: Household) -> bool:
        return (self.config.enabled and clock.minute_of_day >= parse_hhmm(self.config.check_time)
                and household.last_events_day != clock.day)

    def roll(self, engine: Engine, rng: random.Random) -> list[tuple[RandomEvent, str]]:
        """Tire les événements du jour (au plus MAX_EVENTS_PER_DAY) et applique leurs effets."""
        engine.economy.household.last_events_day = engine.clock.day
        happened: list[tuple[RandomEvent, str]] = []
        for event in rng.sample(EVENTS, len(EVENTS)):
            if rng.random() >= event.probability * self.config.frequency:
                continue
            text = event.apply(engine, rng)
            if text:
                happened.append((event, text))
            if len(happened) >= MAX_EVENTS_PER_DAY:
                break
        return happened
