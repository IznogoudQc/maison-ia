"""Vie intérieure : mémoire pondérée, plan du matin, réflexion du soir, objectif."""

import random
import time

import pytest

from agents.agent import Agent
from agents.memory import Memory
from agents.persona import load_family
from agents.plan import DayPlan, PlanItem
from llm.mind_prompts import PlanEntry, PlanResponse, validate_plan
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House

DAY = 24 * 60


@pytest.fixture
def setup():
    config = load_config("config.yaml")
    config.events.frequency = 0.0
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=2), 100_000, 2)
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(0, "06:00"), random.Random(8), bus, llm)
    engine.initialize()
    yield engine, events
    llm.shutdown()


def run_until(engine: Engine, minute: int) -> None:
    while engine.clock.total_minutes < minute:
        engine.tick()
        deadline = time.monotonic() + 1.0
        while (engine.pending_decisions or engine.pending_dialogues or engine.pending_summaries
               or engine.mind.busy() or engine.social.busy()) and time.monotonic() < deadline:
            engine.poll()
            time.sleep(0.0005)


# ---------------------------------------------------------------- mémoire


def test_souvenir_important_et_pertinent_rappele_malgre_son_age():
    memory = Memory()
    memory.add(0, "08:00", "Grand-maman est tombée malade, on a eu peur.", importance=9)
    for i in range(20):
        memory.add(DAY * 3 + i, "09:00", f"Regardé la télé {i}.", importance=1)
    recalled = memory.retrieve(DAY * 3 + 30, {"maman"}, count=4)
    assert any("Grand-maman" in e.text for e in recalled)
    assert recalled[-1].text == "Regardé la télé 19."  # le plus récent est toujours là


def test_memoire_longue_garde_seulement_les_souvenirs_marquants():
    memory = Memory()
    memory.add(0, "08:00", "Mise à pied annoncée.", max_events=3, importance=8)
    memory.add(1, "08:01", "Collation.", max_events=3, importance=1)
    for i in range(5):
        memory.add(2 + i, "08:02", f"Banal {i}", max_events=3, importance=2)
    assert [e.text for e in memory.long_term] == ["Mise à pied annoncée."]


def test_constat_repete_se_renforce_sans_doublon():
    memory = Memory()
    memory.add_belief("L'argent m'inquiète.", 5, 10)
    memory.add_belief("Félix grandit vite.", 3, 20)
    memory.add_belief("L'argent m'inquiète.", 7, 30)
    assert [b.text for b in memory.beliefs] == ["Félix grandit vite.", "L'argent m'inquiète."]
    assert memory.beliefs[-1].importance == 7


# ---------------------------------------------------------------- plan


def test_plages_libres_hors_travail(setup):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    monday = engine.mind.free_slots(pere, 0)
    assert all(not (start < parse_hhmm("16:45") and end > parse_hhmm("07:20")) for start, end in monday)
    saturday = engine.mind.free_slots(pere, 5)
    assert any(start <= parse_hhmm("10:00") < end for start, end in saturday)


def test_plan_invalide_filtre_et_cible_par_prenom(setup):
    engine, _ = setup
    pere = engine.agent_by_id("pere")
    catalog = engine.mind.catalog(pere)
    slots = engine.mind.free_slots(pere, 0)
    names = {a.id: a.name for a in engine.agents}
    response = PlanResponse(plan=[
        PlanEntry(time="10:00", action="tele"),             # au travail : refusé
        PlanEntry(time="19:30", action="voler", note="?"),  # action inconnue : refusée
        PlanEntry(time="20:00", action="jaser", target="Félix"),
    ])
    plan = validate_plan(response, catalog, slots, names)
    assert [(e.time, e.action, e.target) for e in plan.plan] == [("20:00", "jaser", "enfant")]
    with pytest.raises(ValueError):
        validate_plan(PlanResponse(plan=[PlanEntry(time="10:00", action="tele")]), catalog, slots, names)


def test_chacun_recoit_un_plan_au_reveil(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("07:00"))
    plans = [e for e in events if e.kind == "plan"]
    assert {e.data["name"] for e in plans} == {a.name for a in engine.agents}
    assert all(a.plan is not None and a.plan.day == 0 and a.plan.items for a in engine.agents)


def test_activite_prevue_choisie_sans_appel_llm(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("19:00"))
    pere = engine.agent_by_id("pere")
    pere.action = None
    pere.needs.hunger = pere.needs.energy = pere.needs.hygiene = pere.needs.social = pere.needs.fun = 80
    item = PlanItem(minute=engine.clock.minute_of_day, action="telephone", note="texter ma sœur")
    pere.plan = DayPlan(day=0, items=[item])
    calls = engine.llm.stats.calls
    engine._choose(pere)
    assert pere.action is not None and pere.action.name == "telephone"
    assert pere.action.reason == "Prévu : texter ma sœur"
    assert item.status == "done" and engine.llm.stats.calls == calls


def test_urgence_passe_avant_le_plan(setup):
    engine, _ = setup
    run_until(engine, parse_hhmm("19:00"))
    pere = engine.agent_by_id("pere")
    pere.action = None
    pere.needs.hunger = 5
    pere.plan = DayPlan(day=0, items=[PlanItem(minute=engine.clock.minute_of_day, action="lire")])
    engine._choose(pere)
    assert pere.action is not None and pere.action.name == "collation"


def test_activite_trop_en_retard_devient_manquee(setup):
    engine, _ = setup
    run_until(engine, parse_hhmm("19:00"))
    felix = engine.agent_by_id("enfant")
    felix.plan = DayPlan(day=0, items=[PlanItem(minute=parse_hhmm("15:00"), action="jouer")])
    engine.mind.update(felix)
    assert felix.plan.items[0].status == "missed"
    assert "Pas eu le temps" in felix.memory.events[-1].text


def test_nouvelle_importante_fait_refaire_le_plan(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("07:00"))
    engine._news("Mise à pied de Stéphane.", good=False, id_="mise_a_pied")
    run_until(engine, parse_hhmm("07:10"))
    replans = [e for e in events if e.kind == "plan" and e.data["replan"]]
    assert replans
    assert all(a.plan.replans == 1 for a in engine.agents if a.name in {e.data["name"] for e in replans})


# ---------------------------------------------------------------- réflexion et objectif


def test_reflexion_au_coucher_donne_un_constat(setup):
    engine, events = setup
    run_until(engine, DAY + parse_hhmm("00:30"))
    reflections = [e for e in events if e.kind == "reflexion"]
    assert {e.data["name"] for e in reflections} == {a.name for a in engine.agents}
    for agent in engine.agents:
        assert agent.memory.beliefs
        assert agent.reflected_day == 0
        assert any(e.kind == "reflection" for e in agent.memory.events)


def test_objectif_rend_l_option_plus_attirante(setup):
    engine, _ = setup
    run_until(engine, parse_hhmm("19:00"))
    from agents.plan import Goal
    felix = engine.agent_by_id("enfant")
    before = {(o.action, o.target): o.score for o in engine.options_for(felix)}
    felix.goal = Goal(text="flâner dans la cour", action="flaner", until=engine.clock.total_minutes + 60)
    after = {(o.action, o.target): o.score for o in engine.options_for(felix)}
    assert after[("flaner", None)] > before[("flaner", None)]


def test_sauvegarde_garde_plan_constats_et_memoire_longue(setup, tmp_path):
    engine, _ = setup
    run_until(engine, DAY + parse_hhmm("07:00"))
    engine.save_state(tmp_path / "save.json")
    other_cfg = load_config("config.yaml")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(other_cfg.family_file)]
    other = Engine(other_cfg, House(), agents, SimClock(), random.Random(1), EventBus())
    other.load_state(tmp_path / "save.json")
    for before, after in zip(engine.agents, other.agents):
        assert after.plan == before.plan
        assert after.memory.beliefs == before.memory.beliefs
        assert after.memory.long_term == before.memory.long_term
