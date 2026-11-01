"""Aliments : panier selon le budget, repas, péremption, congélateur, potager et poules."""

import pytest

from sim.config import EconomyConfig
from sim.economy import Economy
from sim.food import FOODS


def economy(money=1000.0, pantry=0.0):
    eco = Economy(EconomyConfig())
    eco.household.money, eco.household.pantry = money, pantry
    return eco


def test_catalogue_d_aliments():
    assert {"lait", "kraft_dinner", "tourtiere", "sirop_erable"} <= set(FOODS)


def test_panier_selon_le_budget():
    poor = economy(money=300)
    poor.buy_groceries(0, alive=2, shopper="Camille")
    assert {s.food for s in poor.household.foods} <= {f.id for f in FOODS.values() if "economique" in f.styles}
    rich = economy(money=9000)
    rich.buy_groceries(0, alive=2, shopper="Camille")
    assert any(s.food in ("tourtiere", "steak", "pouding_chomeur") for s in rich.household.foods)
    assert sum(s.portions for s in rich.household.foods) == pytest.approx(rich.household.pantry)


def test_on_mange_ce_qui_perime_en_premier():
    eco = economy()
    eco.add_food("cereales", 8, day=0)
    eco.add_food("lait", 6, day=0)
    assert eco.consume(2) and eco.last_eaten == ["lait"]
    assert eco.household.pantry == pytest.approx(12)


def test_peremption_et_congelateur():
    eco = economy()
    eco.add_food("poulet", 5, day=0)
    assert eco.spoil(day=10) == [("poulet", 5)] and eco.household.pantry == pytest.approx(0)
    eco.household.items.append(type("Freezer", (), {"item_id": "congelateur", "weekly": 0, "hydro": 0, "discount": 0})())
    eco.add_food("poulet", 5, day=0)
    assert eco.household.foods[0].expires_day == FOODS["poulet"].conserve * 3
