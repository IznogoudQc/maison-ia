"""Parsing des réponses JSON du LLM et validation métier."""

import pytest

from agents.actions import Option
from llm.prompts import (
    ActionDecision,
    Dialogue,
    DialogueLine,
    MemorySummary,
    validate_decision,
    validate_dialogue,
)
from llm.service import ParseError, parse_json_response

# ---------------------------------------------------------------- cas valides


def test_json_simple():
    decision = parse_json_response('{"action": "tele", "target": null, "reason": "relaxer"}', ActionDecision)
    assert decision == ActionDecision(action="tele", target=None, reason="relaxer")


def test_json_dans_un_bloc_de_code():
    text = '```json\n{"summary": "Belle journée."}\n```'
    assert parse_json_response(text, MemorySummary).summary == "Belle journée."


def test_json_entoure_de_texte():
    text = 'Voici ma réponse : {"lines": [{"speaker": "Léa", "text": "Genre."}]} Bonne journée!'
    dialogue = parse_json_response(text, Dialogue)
    assert dialogue.lines[0].speaker == "Léa"


def test_champs_optionnels_par_defaut():
    assert parse_json_response('{"action": "lire"}', ActionDecision).reason == ""


# ---------------------------------------------------------------- cas invalides


@pytest.mark.parametrize("text", [
    "",
    "Je sais pas trop.",
    '{"action": "tele", "reason": }',          # JSON cassé
    '{"action": "tele"',                        # accolade manquante
])
def test_json_invalide(text):
    with pytest.raises(ParseError):
        parse_json_response(text, ActionDecision)


def test_champ_obligatoire_manquant():
    with pytest.raises(ParseError):
        parse_json_response('{"target": "mere"}', ActionDecision)


def test_mauvais_type():
    with pytest.raises(ParseError):
        parse_json_response('{"lines": "bonjour"}', Dialogue)


def test_dialogue_vide_refuse():
    with pytest.raises(ParseError):
        parse_json_response('{"lines": []}', Dialogue)


# ---------------------------------------------------------------- validation métier

OPTIONS = [
    Option(action="tele", label="regarde la télé", score=3.0),
    Option(action="jaser", target="mere", label="va jaser avec Julie", score=2.0),
    Option(action="jaser", target="ado", label="va jaser avec Léa", score=1.0),
]
NAMES = {"mere": "Julie", "ado": "Léa", "pere": "Stéphane"}


def test_decision_valide():
    result = validate_decision(ActionDecision(action="TELE", reason=" j'ai le goût "), OPTIONS, NAMES)
    assert result.action == "tele" and result.target is None and result.reason == "j'ai le goût"


def test_decision_cible_par_prenom():
    result = validate_decision(ActionDecision(action="jaser", target="Léa"), OPTIONS, NAMES)
    assert result.target == "ado"


def test_decision_action_hors_options():
    with pytest.raises(ValueError):
        validate_decision(ActionDecision(action="danser"), OPTIONS, NAMES)


def test_decision_cible_inconnue_ambigue():
    with pytest.raises(ValueError):
        validate_decision(ActionDecision(action="jaser", target="pere"), OPTIONS, NAMES)


def test_dialogue_locuteurs_normalises_et_inconnus_ecartes():
    dialogue = Dialogue(lines=[
        DialogueLine(speaker="julie", text="Bon, on se grouille."),
        DialogueLine(speaker="Grand-maman", text="Coucou!"),
        DialogueLine(speaker="ado", text="Ok boomer."),
    ])
    result = validate_dialogue(dialogue, {"mere": "Julie", "ado": "Léa"})
    assert [line.speaker for line in result.lines] == ["Julie", "Léa"]


def test_dialogue_sans_participant_reconnu():
    dialogue = Dialogue(lines=[DialogueLine(speaker="Inconnu", text="Allô")])
    with pytest.raises(ValueError):
        validate_dialogue(dialogue, {"mere": "Julie"})
