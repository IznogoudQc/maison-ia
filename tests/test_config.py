"""Chargement de config.yaml."""

import pytest

from sim.config import AppConfig, load_config


def test_fichier_absent_par_defaut_donne_la_config_par_defaut(tmp_path):
    assert load_config(tmp_path / "absent.yaml") == AppConfig()


def test_fichier_absent_exige_leve_une_erreur(tmp_path):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        load_config(tmp_path / "absent.yaml", required=True)


def test_fichier_present_est_lu(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("save_file: ailleurs.json\nllm:\n  provider: ollama\n", encoding="utf-8")
    config = load_config(path, required=True)
    assert config.save_file == "ailleurs.json"
    assert config.llm.provider == "ollama"
