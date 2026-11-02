"""Calendrier québécois : fériés, école, vacances de la construction, maladie, paie des congés."""

import random
from datetime import date

import pytest

from agents.agent import Agent
from agents.persona import load_family
from sim.calendrier import Calendar, construction_holiday, easter, holidays, school_break
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House

FETE_NATIONALE = 9      # le jour 0 est le lundi 15 juin 2026 : le mercredi 24 juin est le jour 9


def make(day: int, hhmm: str):
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    config.world.date_depart = "2026-06-15"
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(day, hhmm), random.Random(1), bus)
    engine.initialize()
    engine.economy.household.money = 5000.0
    return engine, events


def run_until(engine, minute_of_day: int) -> None:
    target = engine.clock.day * 24 * 60 + minute_of_day
    while engine.clock.total_minutes < target:
        engine.tick()


def test_feries_et_calendrier_scolaire():
    days = holidays(2026)
    assert days[date(2026, 6, 24)] == "Fête nationale" and days[date(2026, 4, 3)] == "Vendredi saint"
    assert days[date(2026, 5, 18)] == "Journée nationale des patriotes"
    assert days[date(2026, 9, 7)] == "fête du Travail" and days[date(2026, 10, 12)] == "Action de grâce"
    assert holidays(2029)[date(2029, 7, 2)] == "fête du Canada (reportée)"      # le 1er juillet 2029 est un dimanche
    assert easter(2027) == date(2027, 3, 28)
    assert construction_holiday(2026) == (date(2026, 7, 20), date(2026, 7, 31))
    assert school_break(date(2026, 7, 10)) == "vacances d'été" and school_break(date(2026, 12, 28)) == "congé des Fêtes"
    assert school_break(date(2026, 3, 4)) == "semaine de relâche" and school_break(date(2026, 10, 2)) == "journée pédagogique"
    assert school_break(date(2026, 4, 6)) == "lundi de Pâques" and school_break(date(2026, 9, 15)) is None
    calendar = Calendar(date(2026, 6, 17))                                       # ramené au lundi 15 juin
    assert calendar.label(0) == "lundi 15 juin 2026" and calendar.holiday(FETE_NATIONALE) == "Fête nationale"
    assert calendar.vacation(35) and not calendar.vacation(30)                  # le 20 juillet est le jour 35


def test_ferie_chome_et_paye():
    engine, events = make(FETE_NATIONALE, "04:50")
    pere = engine.agent_by_id("pere")
    run_until(engine, parse_hhmm("09:00"))
    assert not pere.is_away                                                     # personne au travail
    paid = [e for e in engine.economy.household.ledger if "Fête nationale" in e.label]
    assert [e.amount for e in paid] == [200.0, 165.0]                          # les deux parents payés
    assert any(e.kind == "conge" for e in events)
    assert "Fête nationale (congé)" in engine.family_context(engine.agents)
    assert engine.clock.date_label() == "24 juin 2026 · Fête nationale"


def test_l_ecole_finit_avant_le_travail():
    engine, _ = make(FETE_NATIONALE - 1, "04:50")                               # mardi 23 juin
    run_until(engine, parse_hhmm("09:00"))
    assert engine.agent_by_id("pere").is_away and not engine.agent_by_id("ado").is_away
    assert "Léa (vacances d'été)" in engine.family_context(engine.agents)


def test_malade_reste_a_la_maison_et_se_repose():
    engine, events = make(1, "04:50")
    pere = engine.agent_by_id("pere")
    pere.sick_until = (1 + 2) * 24 * 60 + 5 * 60
    pere.sick_paid = {"2026": 1}
    run_until(engine, parse_hhmm("09:00"))
    assert not pere.is_away and engine.is_sick(pere)
    assert sum("congé de maladie" in e.label for e in engine.economy.household.ledger) == 1
    assert pere.sick_paid["2026"] == 2
    pere.action = None
    actions = {o.action: o for o in engine.options_for(pere)}
    assert "sieste" in actions and "heures_sup" not in actions
    engine._calendar_day = -1
    engine.clock.total_minutes += 24 * 60                                       # le lendemain : plus payé
    engine._daily_calendar()
    assert sum("congé de maladie" in e.label for e in engine.economy.household.ledger) == 1
    assert any("pas payée" in m.text for m in pere.memory.events)
