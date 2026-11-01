"""Chargement et validation de config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class SimConfig(BaseModel):
    tick_minutes: int = 1
    base_ticks_per_second: float = 2.0
    speed_multipliers: list[float] = Field(default_factory=lambda: [1, 3, 10, 30])
    start_day: int = 0
    start_time: str = "06:00"
    move_tiles_per_tick: int = 3
    seed: int | None = 42


class DisplayConfig(BaseModel):
    pixel_scale: float = 2.0   # tuiles de 16 px agrandies de ce facteur
    fps: int = 60
    hud_width: int = 360


class LLMConfig(BaseModel):
    provider: Literal["mock", "claude", "ollama"] = "mock"
    claude_model: str = "claude-haiku-5-5"
    claude_effort: Literal["low", "medium", "high"] = "low"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    timeout_s: float = 30.0
    max_tokens: int = 1500
    max_calls_per_minute: int = 12      # minute réelle
    max_workers: int = 3
    decisions_enabled: bool = True
    decision_cooldown_minutes: int = 60   # minutes simulées entre deux décisions LLM d'un agent
    decision_max_wait_minutes: int = 20   # au-delà, choix déterministe (utile aux vitesses élevées)
    mock_latency_s: tuple[float, float] = (0.3, 1.2)
    mock_invalid_rate: float = 0.05       # part de réponses non JSON pour exercer le repli


class DialogueConfig(BaseModel):
    pair_cooldown_minutes: int = 120   # minutes simulées entre deux conversations d'une même paire
    max_participants: int = 3
    social_gain: float = 25.0
    line_display_s: float = 3.5        # secondes réelles par réplique affichée
    history_size: int = 300


class MemoryConfig(BaseModel):
    short_term_size: int = 30   # événements gardés par agent
    recall_count: int = 5       # souvenirs envoyés au LLM
    summary_every: int = 12     # nouveaux événements avant un résumé LLM
    max_summaries: int = 5


class EconomyConfig(BaseModel):
    enabled: bool = True
    start_money: float = 1500.0
    start_pantry: float = 30.0          # portions
    portion_price: float = 8.0
    meal_portions: float = 1.0
    snack_portions: float = 0.5
    weekly_bills: dict[str, float] = Field(default_factory=lambda: {
        "Hypothèque": 370.0, "Hydro-Québec": 50.0, "Internet et cellulaires": 55.0, "Assurances": 40.0,
    })
    bills_weekday: int = 4              # vendredi
    bills_time: str = "09:00"
    grocery_minutes: int = 90
    grocery_days: int = 7               # l'épicerie vise N jours de nourriture
    low_pantry_days: float = 2.0        # sous ce seuil, l'épicerie devient une option
    shop_hours: tuple[str, str] = ("08:00", "20:00")
    overtime_minutes: int = 180
    overtime_rate: float = 1.5
    overtime_below: float = 400.0       # heures sup proposées sous ce solde
    debt_fun_penalty_per_hour: float = 1.5


class AppConfig(BaseModel):
    sim: SimConfig = Field(default_factory=SimConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    dialogue: DialogueConfig = Field(default_factory=DialogueConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    economy: EconomyConfig = Field(default_factory=EconomyConfig)
    family_file: str = "data/family.yaml"
    save_file: str = "save.json"
    log_dir: str = "logs"


def load_config(path: str | Path = "config.yaml", required: bool = False) -> AppConfig:
    """Lit le YAML ; un fichier absent donne la config par défaut, sauf si required.

    required=True sert aux chemins donnés explicitement (--config) : une faute de frappe
    ne doit pas faire tourner la simulation en silence avec d'autres fichiers de sauvegarde.
    """
    path = Path(path)
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Fichier de configuration introuvable : {path.resolve()}")
        return AppConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)
