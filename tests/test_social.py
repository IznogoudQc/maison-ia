"""Vie sociale : répliques tour par tour, relations, bilan et promesses."""

import random
import time

import pytest

from agents.agent import Agent
from agents.persona import load_family
from agents.social import Promise, Relation
from llm.mock_provider import MockProvider
from llm.service import LLMService, StructuredResult
from llm.social_prompts import Debrief, Line, PromiseSpec, build_line_request, validate_line
from sim.clock import SimClock, parse_hhmm
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from sim.social import Conversation, PendingDebrief
from world.house import House

DAY = 24 * 60


@pytest.fixture
def setup():
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=5), 100_000, 2)
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(0, "06:00"), random.Random(3), bus, llm)
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


def make_free(engine, *ids):
    """Rend les agents présents, éveillés, sans action ni besoin pressant (indépendant du tirage)."""
    engine.economy.household.money = 5000.0   # ni heures sup ni épicerie pour les attirer ailleurs
    engine.economy.household.pantry = 200.0
    for agent_id in ids:
        agent = engine.agent_by_id(agent_id)
        agent.away_until = agent.away_label = agent.away_kind = None
        agent.drove = False
        agent.action, agent.path = None, []
        agent.pos = engine.house.random_tile(engine.rng, "Salon")
        for need in ("hunger", "energy", "hygiene", "social", "fun"):
            setattr(agent.needs, need, 80.0)
        agent.relations.clear()


# ---------------------------------------------------------------- réplique et relation


def test_replique_nettoyee_et_bornee():
    line = validate_line(Line(text="Stéphane : « Voyons donc. »", to="Julie", affection=9, tension=-7),
                         "Stéphane", {"mere": "Julie"})
    assert line.text == "Voyons donc." and line.to == "mere"
    assert (line.affection, line.tension) == (3, -3)
    with pytest.raises(ValueError):
        validate_line(Line(text="  "), "Stéphane", {"mere": "Julie"})


def test_relation_bornee_et_qui_revient_a_la_normale():
    relation = Relation()
    relation.change(affection=-80, tension=90, note="Elle m'a crié après")
    assert relation.affection == 0 and relation.tension == 100
    assert relation.mood == "en chicane" and "crié" in relation.describe()
    relation.drift(days=3, tension_decay=8)
    assert relation.tension == 76 and relation.affection > 0


def test_chacun_parle_avec_sa_propre_memoire(setup):
    engine, _ = setup
    pere, felix = engine.agent_by_id("pere"), engine.agent_by_id("enfant")
    engine.remember(pere, "SECRET-PERE : j'ai cabossé l'auto.", 9)
    engine.remember(felix, "SECRET-FELIX : j'ai caché les clés.", 9)
    memories, summary = engine.memories_for(pere, ["Félix"])
    request = build_line_request(pere, [felix], "Salon", engine.clock.label(), [], memories, summary,
                                 500, engine.clock.total_minutes, 0, 6)
    assert "SECRET-PERE" in request.prompt and "SECRET-FELIX" not in request.prompt


def test_conversation_tour_par_tour(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("21:00"))
    lines = [e for e in events if e.kind == "replique"]
    dialogues = [e for e in events if e.kind == "dialogue"]
    assert lines and dialogues and all(d.data["live"] for d in dialogues)
    assert all(len(d.data["lines"]) <= engine.config.dialogue.max_turns for d in dialogues)
    assert any(e.kind == "bilan" for e in events)
    assert any(m.text.startswith("Jasé avec") for a in engine.agents for m in a.memory.events)


def test_replique_change_le_ressenti_du_locuteur(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("19:00"))
    make_free(engine, "pere", "mere")
    pere = engine.agent_by_id("pere")
    conv = Conversation(99, ["pere", "mere"], "Salon", engine.clock.total_minutes, "pere")
    engine.social.conversations.append(conv)
    line = Line(text="T'as encore oublié l'épicerie!", to="mere", tension=3, affection=-2,
                thought="Je suis tanné de tout faire")
    engine.social._handle_line(conv, StructuredResult(value=line, ok=True, attempts=1))
    relation = pere.relation("mere")
    assert relation.tension == pytest.approx(18) and relation.affection == pytest.approx(63)
    assert relation.note == "Je suis tanné de tout faire"
    assert engine.agent_by_id("mere").relation("pere").tension == pytest.approx(15)  # pas réciproque
    assert any(e.kind == "replique" and e.data["to"] == "Julie" for e in events)


def test_paire_en_chicane_se_reparle_moins_souvent(setup):
    engine, _ = setup
    base = engine.config.dialogue.pair_cooldown_minutes
    assert engine.social.pair_cooldown("ado", "mere") == base
    engine.agent_by_id("ado").relation("mere").tension = 80
    assert engine.social.pair_cooldown("ado", "mere") == base * engine.config.dialogue.tense_cooldown_factor


def test_affection_donne_envie_d_aller_jaser(setup):
    engine, _ = setup
    run_until(engine, parse_hhmm("19:00"))
    make_free(engine, "pere", "enfant")
    pere = engine.agent_by_id("pere")
    def score(target):
        return next((o.score for o in engine.options_for(pere) if o.action == "jaser" and o.target == target), None)
    before = score("enfant")
    if before is None:
        pytest.skip("Félix pas disponible à cette heure")
    pere.relation("enfant").change(affection=30)
    assert score("enfant") > before


# ---------------------------------------------------------------- promesses


def debrief_with(engine, *specs):
    pending = PendingDebrief(None, ["pere", "enfant"], "Salon", [("Félix", "Tu joues avec moi?"),
                                                                ("Stéphane", "Demain, promis.")], {}, False)
    engine.social._apply_debrief(pending, StructuredResult(value=Debrief(importance=6, promises=list(specs)),
                                                           ok=True, attempts=1))


def test_bilan_cree_seulement_les_promesses_realistes(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("19:00"))  # lundi soir
    engine.social.promises.clear()  # celles que le mock a pu créer en jasant
    debrief_with(engine,
                 PromiseSpec(who=["Stéphane", "Félix"], by="Stéphane", action="jouer", time="19:30", day="demain"),
                 PromiseSpec(who=["Stéphane"], action="tele", time="10:00", day="demain"),   # au travail
                 PromiseSpec(who=["Félix"], action="voler", time="19:00", day="demain"))     # inconnue
    promises = engine.social.promises
    assert len(promises) == 1
    promise = promises[0]
    assert promise.people == ["pere", "enfant"] and promise.by == "pere"
    assert promise.minute == DAY + parse_hhmm("19:30")
    assert any(e.kind == "promesse" for e in events)
    assert any(m.text.startswith("Promis :") for m in engine.agent_by_id("enfant").memory.events)
    jase = [m for m in engine.agent_by_id("pere").memory.events if m.text.startswith("Jasé avec")]
    assert jase and jase[-1].importance == 6


def test_promesse_tenue(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("19:00"))
    engine.social.promises.clear()
    make_free(engine, "pere", "enfant")
    minute = engine.clock.total_minutes + 5
    engine.social.promises.append(Promise(id=50, people=["pere", "enfant"], by="pere", action="jouer",
                                          minute=minute, text="Lego avec Félix"))
    run_until(engine, minute + 30)
    promise = next(p for p in engine.social.promises if p.id == 50)
    assert promise.status == "kept"
    actions = {e.data["name"]: e.data["action"] for e in events
               if e.kind == "action" and e.minute >= minute and e.data["reason"].startswith("Promesse")}
    assert actions.get("Félix") == "jouer" and actions.get("Stéphane") == "jaser"  # papa jase à côté des Lego
    assert any(e.kind == "promesse_tenue" for e in events)


def test_promesse_brisee_fache_celui_qui_attendait(setup):
    engine, events = setup
    run_until(engine, parse_hhmm("19:00"))
    engine.social.promises.clear()
    make_free(engine, "pere", "enfant")
    pere = engine.agent_by_id("pere")
    pere.away_until, pere.away_label, pere.away_kind = engine.clock.total_minutes + 600, "travail", "travail"
    minute = engine.clock.total_minutes + 5
    engine.social.promises.append(Promise(id=51, people=["pere", "enfant"], by="pere", action="jouer",
                                          minute=minute, text="Lego avec Félix"))
    run_until(engine, minute + engine.config.dialogue.promise_window_minutes + 5)
    assert next(p for p in engine.social.promises if p.id == 51).status == "broken"
    relation = engine.agent_by_id("enfant").relation("pere")
    assert relation.tension > 15 and "pas tenu" in relation.note
    assert any("Stéphane n'a pas tenu sa promesse" in m.text for m in engine.agent_by_id("enfant").memory.events)
    assert any(e.kind == "promesse_brisee" and e.data["missing"] == ["Stéphane"] for e in events)


def test_sauvegarde_garde_relations_et_promesses(setup, tmp_path):
    engine, _ = setup
    engine.agent_by_id("ado").relation("mere").change(tension=40, note="Encore le téléphone")
    engine.social.promises.append(Promise(id=7, people=["ado"], by="ado", action="tondre",
                                          minute=DAY + 600, text="Léa tond le gazon"))
    engine.save_state(tmp_path / "save.json")
    config = load_config("config.yaml", scenario="maison")
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    other = Engine(config, House(), agents, SimClock(), random.Random(1), EventBus())
    other.load_state(tmp_path / "save.json")
    assert other.agent_by_id("ado").relation("mere").note == "Encore le téléphone"
    assert [p.text for p in other.social.promises] == ["Léa tond le gazon"]


def test_mode_scene_passe_aussi_par_le_bilan(setup):
    engine, events = setup
    engine.config.dialogue.mode = "scene"
    run_until(engine, parse_hhmm("21:00"))
    dialogues = [e for e in events if e.kind == "dialogue"]
    assert dialogues and not any(e.kind == "replique" for e in events)
    assert sum(e.kind == "bilan" for e in events) == len(dialogues)
