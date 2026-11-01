"""Décroissance des besoins, bornes et humeur."""

import pytest

from agents.needs import RATES_PER_HOUR, Needs


def test_decroissance_une_heure_eveille():
    needs = Needs(hunger=80, energy=80, hygiene=80, social=80, fun=80)
    needs.decay(60, "awake")
    for name, rate in RATES_PER_HOUR["awake"].items():
        assert getattr(needs, name) == pytest.approx(80 + rate)


def test_decroissance_proportionnelle_au_temps():
    a, b = Needs(), Needs()
    a.decay(30)
    a.decay(30)
    b.decay(60)
    assert a.as_dict() == pytest.approx(b.as_dict())


def test_bornes_0_et_100():
    needs = Needs(hunger=1, energy=99)
    needs.decay(600, "awake")
    assert needs.hunger == 0
    needs.decay(600, "sleeping")
    assert needs.energy == 100


def test_sommeil_recupere_l_energie_sans_loisir_perdu():
    needs = Needs(energy=20, fun=50)
    needs.decay(8 * 60, "sleeping")
    assert needs.energy > 90
    assert needs.fun == 50


def test_absence_augmente_le_social():
    needs = Needs(social=40)
    needs.decay(120, "away")
    assert needs.social > 40


def test_apply_fraction_etale_l_effet():
    needs = Needs(hunger=10)
    for _ in range(10):
        needs.apply({"hunger": 50}, 0.1)
    assert needs.hunger == pytest.approx(60)


def test_lowest_et_humeur():
    needs = Needs(hunger=10, energy=90, hygiene=90, social=90, fun=90)
    assert needs.lowest() == ("hunger", 10)
    assert "faim" in needs.mood()
    assert Needs(hunger=95, energy=95, hygiene=95, social=95, fun=95).mood() == "excellente"
