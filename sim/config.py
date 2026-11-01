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
    pixel_scale: float | Literal["auto"] = "auto"   # tuiles de 16 px agrandies de ce facteur
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
    mode: Literal["tour_par_tour", "scene"] = "tour_par_tour"  # un appel par réplique, ou un pour tout
    max_turns: int = 6                 # répliques au plus en mode tour par tour
    max_minutes: int = 45              # conversation abandonnée au-delà (minutes simulées)
    tense_cooldown_factor: float = 2.0  # paire en chicane : cooldown multiplié
    tension_decay_per_day: float = 8.0
    promise_window_minutes: int = 60   # retard toléré pour tenir une promesse
    promise_max_days: int = 3          # une promesse vise au plus N jours plus tard


class MemoryConfig(BaseModel):
    short_term_size: int = 30   # événements gardés par agent
    recall_count: int = 5       # souvenirs envoyés au LLM
    summary_every: int = 12     # nouveaux événements avant un résumé LLM
    max_summaries: int = 5
    long_term_size: int = 40          # souvenirs marquants gardés après la mémoire courte
    keep_from_importance: int = 6     # importance minimale pour la mémoire longue (1-10)
    recency_half_life_hours: float = 24.0  # fraîcheur d'un souvenir divisée par 2 toutes les N heures
    max_beliefs: int = 6              # constats tirés des réflexions du soir


class MindConfig(BaseModel):
    plans_enabled: bool = True          # plan de la journée au réveil
    reflections_enabled: bool = True    # réflexion au coucher (constats + objectif du lendemain)
    plan_item_window_minutes: int = 90  # retard toléré avant qu'une activité prévue soit « manquée »
    max_replans_per_day: int = 2        # nouveau plan après un imprévu (nouvelle, décès...)
    goal_boost: float = 1.5             # poids de l'option visée par l'objectif du soir


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


class HealthConfig(BaseModel):
    mortality: bool = True              # False : santé à 0 => quelques jours d'hôpital au lieu de la mort
    starvation_per_hour: float = 2.0    # perte de santé quand la faim est à 0 (~2 jours avant la mort)
    exhaustion_per_hour: float = 1.0    # perte de santé quand l'énergie est à 0
    regen_per_hour: float = 1.5         # récupération quand on mange et dort assez
    hospital_days: int = 3
    grief_days: int = 3


class EventsConfig(BaseModel):
    enabled: bool = True
    check_time: str = "08:30"           # tirage quotidien des événements
    frequency: float = 1.0              # multiplicateur des probabilités (0 = jamais, 2 = deux fois plus)
    narrate: bool = True                # le LLM raconte l'événement (les chiffres restent ceux du moteur)


class LifeConfig(BaseModel):
    """Vie de famille (scénario terrain) : vieillir, avoir des enfants, les voir grandir."""
    enabled: bool = True
    days_per_year: float = 7.0          # un an passe en N jours simulés
    pregnancy_days: float = 5.0         # 9 mois ≈ 0,75 an
    conception_days: tuple[float, float] = (1.0, 4.0)  # délai entre « on essaie » et la grossesse
    min_happiness: float = 60.0         # bonheur moyen (besoins et santé) des deux pour en parler
    min_affection: float = 70.0         # affection mutuelle minimale
    talk_every_days: int = 7            # au plus une discussion « bébé » par semaine
    max_children: int = 4
    parental_leave_years: float = 1.0   # congé parental (RQAP) pendant la première année
    leave_pay_rate: float = 0.7         # prestations : 70 % du salaire
    daycare_fee: float = 9.0            # garderie subventionnée, par jour


class TerrainConfig(BaseModel):
    """Scénario « terrain » : un couple, une tente et un lot boisé à bâtir."""
    width: int = 120
    height: int = 80
    seed: int | None = None             # None = sim.seed
    tree_density: float = 1.0
    family_file: str = "data/couple.yaml"
    start_money: float = 3000.0
    start_pantry: float = 20.0
    weekly_bills: dict[str, float] = Field(default_factory=lambda: {
        "Taxes du terrain": 35.0, "Cellulaires": 45.0, "Assurances": 15.0,
    })
    instant_build: bool = False   # essai : une pièce se bâtit dès que son emplacement est dégagé


class WorldConfig(BaseModel):
    scenario: Literal["maison", "terrain"] = "maison"
    terrain: TerrainConfig = Field(default_factory=TerrainConfig)


class AppConfig(BaseModel):
    sim: SimConfig = Field(default_factory=SimConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    dialogue: DialogueConfig = Field(default_factory=DialogueConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    economy: EconomyConfig = Field(default_factory=EconomyConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    mind: MindConfig = Field(default_factory=MindConfig)
    world: WorldConfig = Field(default_factory=WorldConfig)
    life: LifeConfig = Field(default_factory=LifeConfig)
    family_file: str = "data/family.yaml"
    save_file: str = "save.json"
    log_dir: str = "logs"


def load_config(path: str | Path = "config.yaml", required: bool = False,
                scenario: str | None = None) -> AppConfig:
    """Lit le YAML ; un fichier absent donne la config par défaut, sauf si required.

    required=True sert aux chemins donnés explicitement (--config) : une faute de frappe
    ne doit pas faire tourner la simulation en silence avec d'autres fichiers de sauvegarde.
    scenario force le scénario (tests indépendants du choix fait dans config.yaml).
    """
    path = Path(path)
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Fichier de configuration introuvable : {path.resolve()}")
        config = AppConfig()
    else:
        config = AppConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if scenario is not None:
        config.world.scenario = scenario
    return apply_scenario(config)


def apply_scenario(config: AppConfig) -> AppConfig:
    """Scénario « terrain » : famille, argent de départ et factures propres au terrain."""
    if config.world.scenario == "terrain":
        terrain = config.world.terrain
        config.family_file = terrain.family_file
        config.economy.start_money = terrain.start_money
        config.economy.start_pantry = terrain.start_pantry
        config.economy.weekly_bills = dict(terrain.weekly_bills)
    return config
