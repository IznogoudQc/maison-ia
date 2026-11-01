"""Économie du ménage : compte commun, garde-manger, épicerie et factures."""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from sim.clock import SimClock, parse_hhmm
from sim.config import EconomyConfig

# Portions consommées par personne et par jour : déjeuner, lunch, souper, une demi-collation
PORTIONS_PER_PERSON_DAY = 3.5
LEDGER_SIZE = 60


class LedgerEntry(BaseModel):
    minute: int
    label: str
    amount: float


class Household(BaseModel):
    money: float = 0.0
    pantry: float = 0.0            # portions de nourriture
    last_bills_day: int = -1
    ledger: list[LedgerEntry] = Field(default_factory=list)


class Economy:
    def __init__(self, config: EconomyConfig, household: Household | None = None) -> None:
        self.config = config
        self.household = household or Household(money=config.start_money, pantry=config.start_pantry)

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    # ------------------------------------------------------------------ argent

    def transaction(self, minute: int, label: str, amount: float) -> None:
        self.household.money = round(self.household.money + amount, 2)
        self.household.ledger.append(LedgerEntry(minute=minute, label=label, amount=round(amount, 2)))
        del self.household.ledger[:-LEDGER_SIZE]

    @property
    def in_debt(self) -> bool:
        return self.enabled and self.household.money < 0

    def weekly_bills(self) -> float:
        return round(sum(self.config.weekly_bills.values()), 2)

    def bills_due(self, clock: SimClock) -> bool:
        return (self.enabled and clock.weekday == self.config.bills_weekday
                and clock.minute_of_day >= parse_hhmm(self.config.bills_time)
                and self.household.last_bills_day != clock.day)

    def charge_bills(self, clock: SimClock) -> float:
        total = self.weekly_bills()
        self.transaction(clock.total_minutes, "Factures de la semaine", -total)
        self.household.last_bills_day = clock.day
        return total

    # ------------------------------------------------------------------ nourriture

    def portions_for(self, action: str) -> float:
        """Portions consommées par une action (0 si elle ne mange rien)."""
        if action in ("souper", "dejeuner"):
            return self.config.meal_portions
        if action == "collation":
            return self.config.snack_portions
        return 0.0

    def consume(self, portions: float) -> bool:
        """Retire des portions du garde-manger ; False (rien retiré) s'il n'y en a pas assez."""
        if not self.enabled or portions <= 0:
            return True
        if self.household.pantry + 1e-9 < portions:
            return False
        self.household.pantry = round(self.household.pantry - portions, 2)
        return True

    def pantry_days(self, alive: int) -> float:
        """Jours de nourriture restants pour la famille."""
        return self.household.pantry / max(1.0, alive * PORTIONS_PER_PERSON_DAY)

    def portion_price(self) -> float:
        return self.config.portion_price

    def buy_groceries(self, minute: int, alive: int, shopper: str) -> tuple[int, float]:
        """Remplit le garde-manger pour grocery_days jours, dans la limite de l'argent disponible."""
        price = self.portion_price()
        wanted = alive * PORTIONS_PER_PERSON_DAY * self.config.grocery_days - self.household.pantry
        affordable = math.floor(max(0.0, self.household.money) / price)
        bought = max(0, min(math.ceil(wanted), affordable))
        cost = round(bought * price, 2)
        if bought:
            self.household.pantry = round(self.household.pantry + bought, 2)
            self.transaction(minute, f"Épicerie ({shopper})", -cost)
        return bought, cost

    # ------------------------------------------------------------------ affichage et prompts

    def summary(self, alive: int) -> str:
        h = self.household
        debt = " (DETTE)" if h.money < 0 else ""
        return (f"Argent du ménage : {h.money:,.0f} ${debt} ; garde-manger : {h.pantry:.0f} portions "
                f"(environ {self.pantry_days(alive):.1f} jour(s)) ; factures hebdomadaires : "
                f"{self.weekly_bills():,.0f} $").replace(",", " ")
