"""Économie du ménage : compte commun, garde-manger, épicerie et factures."""

from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, Field

from sim.clock import SimClock, parse_hhmm
from sim.config import EconomyConfig

# Portions consommées par personne et par jour : déjeuner, lunch, souper, une demi-collation
PORTIONS_PER_PERSON_DAY = 3.5
LEDGER_SIZE = 60
RESERVE_WEEKS = 2       # un achat n'est proposé que s'il reste deux semaines de dépenses en banque
CAR_GROCERY_DISCOUNT = 0.9  # en auto : épicerie en gros format


@dataclass(frozen=True)
class Purchase:
    id: str
    label: str            # « une piscine hors-terre »
    price: float
    weekly_cost: float    # frais récurrents ajoutés aux factures
    weekly_label: str
    benefit: str          # texte pour le LLM et l'interface


CATALOG: dict[str, Purchase] = {p.id: p for p in [
    Purchase("tondeuse", "une tondeuse", 300, 0, "", "permet de tondre la pelouse soi-même"),
    Purchase("bbq", "un BBQ", 450, 8, "Propane du BBQ", "soupers BBQ la fin de semaine"),
    Purchase("piscine", "une piscine hors-terre", 2500, 20, "Chlore de la piscine",
             "baignades : gros plaisir en famille"),
    Purchase("auto", "une auto usagée", 5000, 60, "Essence et assurance auto",
             "retour du travail plus tôt, épicerie plus rapide et moins chère"),
    Purchase("scie", "une scie à chaîne", 400, 5, "Essence de la scie à chaîne",
             "coupe les arbres deux fois plus vite"),
]}


class LedgerEntry(BaseModel):
    minute: int
    label: str
    amount: float


class Household(BaseModel):
    money: float = 0.0
    pantry: float = 0.0            # portions de nourriture
    last_bills_day: int = -1
    last_events_day: int = -1      # dernier jour où les événements aléatoires ont été tirés
    price_factor: float = 1.0      # inflation de l'épicerie (événements)
    purchases: list[str] = Field(default_factory=list)  # ids du CATALOG
    lawn: float = 20.0             # hauteur du gazon (0 = fraîchement tondu, 100 = jungle)
    last_lawn_day: int = -1
    last_fine_day: int = -100
    wood: int = 0                  # bûches coupées sur le terrain (feu, puis construction)
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

    def weekly_bill_items(self) -> dict[str, float]:
        """Factures fixes + frais récurrents des achats."""
        items = dict(self.config.weekly_bills)
        for item_id in self.household.purchases:
            item = CATALOG.get(item_id)
            if item and item.weekly_cost:
                items[item.weekly_label] = item.weekly_cost
        return items

    def weekly_bills(self) -> float:
        return round(sum(self.weekly_bill_items().values()), 2)

    # ------------------------------------------------------------------ achats

    def owns(self, item_id: str) -> bool:
        return item_id in self.household.purchases

    def reserve(self, alive: int) -> float:
        """Coussin à garder en banque : RESERVE_WEEKS semaines de factures et d'épicerie."""
        food_week = alive * PORTIONS_PER_PERSON_DAY * 7 * self.portion_price()
        return RESERVE_WEEKS * (self.weekly_bills() + food_week)

    def affordable(self, alive: int) -> list[Purchase]:
        if not self.enabled:
            return []
        budget = self.household.money - self.reserve(alive)
        return [p for p in CATALOG.values() if not self.owns(p.id) and p.price <= budget]

    def buy(self, minute: int, item_id: str, buyer: str) -> Purchase | None:
        item = CATALOG[item_id]
        if self.owns(item_id) or self.household.money < item.price:
            return None
        self.transaction(minute, f"Achat : {item.label} ({buyer})", -item.price)
        self.household.purchases.append(item_id)
        return item

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
        return round(self.config.portion_price * self.household.price_factor, 2)

    def buy_groceries(self, minute: int, alive: int, shopper: str, by_car: bool = False) -> tuple[int, float]:
        """Remplit le garde-manger pour grocery_days jours, dans la limite de l'argent disponible."""
        price = round(self.portion_price() * (CAR_GROCERY_DISCOUNT if by_car else 1.0), 2)
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
        owned = ", ".join(CATALOG[p].label for p in h.purchases if p in CATALOG) or "rien de spécial"
        text = (f"Argent du ménage : {h.money:,.0f} ${debt} ; garde-manger : {h.pantry:.0f} portions "
                f"(environ {self.pantry_days(alive):.1f} jour(s)) ; factures hebdomadaires : "
                f"{self.weekly_bills():,.0f} $ ; la famille possède : {owned}").replace(",", " ")
        if h.lawn >= 70:
            text += " ; la pelouse est très longue"
        return text
