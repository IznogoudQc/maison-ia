"""Chronique illustrée : captures aux moments marquants, page HTML de la semaine écrite par l'IA, sommaire."""

import random
import time

from agents.agent import Agent
from agents.persona import load_family
from llm.chronicle_prompts import ChronicleText, Paragraph, validate_chronicle
from llm.mock_provider import MockProvider
from llm.service import LLMService
from sim.clock import SimClock
from sim.config import load_config
from sim.engine import Engine
from sim.events import ALL, EventBus
from world.house import House


def make(tmp_path, llm=None, day=7, start="10:00"):
    config = load_config("config.yaml", scenario="maison")
    config.events.frequency = 0.0
    bus = EventBus()
    events = []
    bus.subscribe(ALL, events.append)
    agents = [Agent(persona=p, pos=(0, 0)) for p in load_family(config.family_file)]
    engine = Engine(config, House(), agents, SimClock(day, start), random.Random(1), bus, llm)
    engine.initialize()
    engine.visitors.planned_day, engine.visitors.planned = engine.clock.day, None
    engine.chronicle.out_dir = tmp_path / "chroniques"
    return engine, events


def test_validation_de_la_chronique():
    text = ChronicleText(title=" Titre ", paragraphs=[Paragraph(text="a", image=1), Paragraph(text="b", image=1),
                                                       Paragraph(text="c", image=9)])
    ok = validate_chronicle(text, 2)
    assert ok.title == "Titre" and [p.image for p in ok.paragraphs] == [1, None, None]


def test_capture_demandee_aux_moments_marquants(tmp_path):
    engine, _ = make(tmp_path)
    chronicle = engine.chronicle
    assert chronicle.snapshot_request() is None
    engine.visitors.arrive(engine.visitors.known["grandmere"], 60)
    caption = chronicle.snapshot_request()
    assert caption and "Ginette" in caption
    chronicle.add_snapshot("a.png", caption)
    engine.publish("neige", text="Bordée de neige : 20 cm cette nuit !")
    assert chronicle.snapshot_request() is None              # trois heures entre deux captures
    engine.clock.total_minutes += 200
    engine.publish("neige", text="Bordée de neige : 20 cm cette nuit !")
    assert chronicle.snapshot_request().startswith("Bordée")


def test_capture_de_fin_de_journee(tmp_path):
    engine, _ = make(tmp_path, start="18:25")
    for _ in range(10):
        engine.tick()
    assert engine.chronicle.snapshot_request().startswith("Fin de journée")


def test_page_de_la_semaine_par_l_ia(tmp_path):
    llm = LLMService(MockProvider((0.0, 0.0), 0.0, seed=1), 1000, 1)
    engine, events = make(tmp_path, llm, day=13, start="20:00")
    chronicle = engine.chronicle
    engine.publish("fete", title="BBQ", text="C'est la fête : « BBQ des voisins »")
    chronicle.add_snapshot("semaine_2_1.png", "C'est la fête : « BBQ des voisins »")
    for _ in range(12 * 60 // engine.clock.tick_minutes):       # on passe au lundi matin
        engine.tick()
    deadline = time.monotonic() + 3
    while chronicle.pending is not None and time.monotonic() < deadline:
        engine.poll()
        time.sleep(0.005)
    page = chronicle.latest()
    assert page is not None and page.exists() and page.name == "semaine_2.html"
    content = page.read_text(encoding="utf-8")
    assert "<img src='semaine_2_1.png'" in content and "BBQ des voisins" in content
    assert "semaine_2.html" in (page.parent / "index.html").read_text(encoding="utf-8")
    assert any(e.kind == "chronique" for e in events)
    llm.shutdown()


def test_page_sans_ia_et_texte_echappe(tmp_path):
    engine, _ = make(tmp_path, day=7)
    engine.publish("evenement", id="x", text="<script>alert(1)</script> Facture surprise", good=False, money=0)
    engine.chronicle.write_week(1)
    content = engine.chronicle.latest().read_text(encoding="utf-8")
    assert "<script>" not in content and "&lt;script&gt;" in content


def test_sauvegarde_de_la_chronique(tmp_path):
    engine, _ = make(tmp_path)
    engine.chronicle.add_snapshot("x.png", "légende")
    engine.chronicle.last_week = 3
    path = tmp_path / "save.json"
    engine.save_state(path)
    other, _ = make(tmp_path)
    other.load_state(path)
    assert other.chronicle.last_week == 3 and other.chronicle.snapshots[0].caption == "légende"
