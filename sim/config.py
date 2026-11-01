"""Chargement et validation de config.yaml."""

from __future__ import annotations

from pathlib import Path

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


class AppConfig(BaseModel):
    sim: SimConfig = Field(default_factory=SimConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
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
