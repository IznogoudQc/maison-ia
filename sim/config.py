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
    tile_size: int = 24
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


class AppConfig(BaseModel):
    sim: SimConfig = Field(default_factory=SimConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    dialogue: DialogueConfig = Field(default_factory=DialogueConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    family_file: str = "data/family.yaml"
    save_file: str = "save.json"
    log_dir: str = "logs"


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Lit le YAML ; un fichier absent donne la config par défaut."""
    path = Path(path)
    if not path.exists():
        return AppConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)
