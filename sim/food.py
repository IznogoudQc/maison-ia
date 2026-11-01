"""Garde-manger en aliments (data/aliments.yaml) : panier d'épicerie, repas, péremption.

Le total household.pantry (portions) reste la référence pour le reste du jeu ; household.foods détaille
une partie de ces portions par aliment (le reste : des « restes maison » sans date).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

FOODS_FILE = Path("data/aliments.yaml")
FREEZER_FACTOR = 3


class Food(BaseModel):
    id: str
    label: str
    prix: float
    portions: float
    conserve: int = 7
    plaisir: float = 0.0
    congelable: bool = False
    styles: list[str] = Field(default_factory=lambda: ["equilibre"])

    @property
    def portion_price(self) -> float:
        return self.prix / self.portions


class FoodStock(BaseModel):
    food: str
    portions: float
    expires_day: int


def load_foods(path: Path = FOODS_FILE) -> dict[str, Food]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {f.id: f for f in (Food.model_validate(raw) for raw in data.get("aliments", []))}


FOODS = load_foods()


def basket(style: str, portions_wanted: float, budget: float, price_factor: float = 1.0) -> list[tuple[Food, int]]:
    """Paquets à acheter : on fait le tour des aliments du style jusqu'à couvrir les portions ou le budget."""
    choices = sorted((f for f in FOODS.values() if style in f.styles), key=lambda f: f.portion_price)
    if not choices:
        return []
    counts = {f.id: 0 for f in choices}
    got, spent = 0.0, 0.0
    while got < portions_wanted:
        progress = False
        for food in choices:
            price = food.prix * price_factor
            if got >= portions_wanted or spent + price > budget:
                continue
            counts[food.id] += 1
            got += food.portions
            spent += price
            progress = True
        if not progress:
            break
    return [(FOODS[i], n) for i, n in counts.items() if n]


def describe_stock(stocks: list[FoodStock], today: int) -> list[str]:
    """« lait : 6 portions (périme demain) », trié par date de péremption."""
    lines = []
    for stock in sorted(stocks, key=lambda s: s.expires_day):
        food = FOODS.get(stock.food)
        days = stock.expires_day - today
        when = "périme aujourd'hui" if days <= 0 else "périme demain" if days == 1 else f"{days} jours" if days < 30 else "longue durée"
        lines.append(f"{food.label if food else stock.food} : {stock.portions:.0f} portions ({when})")
    return lines
