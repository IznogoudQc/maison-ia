"""Orchestration des ticks : besoins, horaire, choix et déroulement des actions."""

from __future__ import annotations

import json
import random
import time
from datetime import date
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path

from agents.actions import (
    ACTIONS,
    AWAY_ACTIONS,
    DAYTIME_HOURS,
    URGENT_THRESHOLD,
    Option,
    action_label,
    away_phrase,
    is_allowed,
    score_action,
)
from agents.agent import ActiveAction, Agent
from agents.memory import keywords
from agents.needs import NEED_LOW_WORDS, Needs
from agents.scheduler import Scheduler
from llm.prompts import (
    ActionDecision,
    Dialogue,
    EventStory,
    MemorySummary,
    build_decision_request,
    build_dialogue_request,
    build_story_request,
    build_summary_request,
    validate_decision,
    validate_dialogue,
    validate_story,
)
from llm.service import LLMService, StructuredResult
from sim.clock import SimClock, parse_hhmm
from sim.config import AppConfig
from sim.economy import CATALOG, Economy, Household
from sim.events import Event, EventBus
from sim.food import FOODS
from sim.architect import Architect
from sim.calendrier import Calendar
from sim.career import Careers
from sim.family import FamilyLife
from sim.portrait import Portraits
from sim.credit import Credit
from sim.garage import Garage
from sim.history import History
from sim.inventory import Inventory
from sim.mind import Mind
from sim.social import Social
from sim.random_events import RandomEvents
from world.house import House, InteractiveObject
from world.pathfinding import NEIGHBORS, manhattan

Pos = tuple[int, int]


@dataclass
class PendingDecision:
    future: Future[StructuredResult[ActionDecision]]
    options: list[Option]
    fallback: ActionDecision
    requested_minute: int


@dataclass
class PendingDialogue:
    future: Future[StructuredResult[Dialogue]]
    participant_ids: list[str]
    room: str
    minute: int


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


# Actions d'horaire qui laissent un souvenir
MEMORABLE_ACTIONS = {
    "souper": "Souper en famille.",
    "dejeuner": "Déjeuner avant la journée.",
    "cuisiner": "J'ai préparé le souper.",
    "dormir": "Au lit pour la nuit.",
}

LAWN_GROWTH_PER_DAY = 14.0
LAWN_MOW_FROM = 50.0       # tondre devient une option
LAWN_NEIGHBOR_AT = 85.0    # sans tondeuse : le jeune d'à côté tond (contre de l'argent)
NEIGHBOR_MOW_PRICE = 40.0
LAWN_FINE = 150.0          # pelouse à 100 : amende de la ville (au plus une fois par semaine)
CAR_COMMUTE_SAVING = 30    # minutes gagnées au retour du travail en auto
CAR_GROCERY_MINUTES = 60

FLANER_RADIUS = 10         # flâner : une case pas trop loin (sur un grand terrain)
WOOD_TARGET = 25           # bûches visées en réserve ; en dessous, couper devient pressant
WOOD_MAX = 60              # au-delà, on arrête de couper (la corde est pleine)
WOOD_YIELD = {"Érable": 6, "Sapin": 5, "Bouleau": 4}
SAW_FACTOR = 0.45          # avec la scie à chaîne, un arbre prend 45 % du temps
NO_ROOF_FUN_PER_HOUR = 1.0  # vivre sans toit use le moral, petit à petit
CUT_HOURS = (8 * 60, 19 * 60)
SICK_FORBIDDEN = {"couper", "construire", "tondre", "heures_sup", "engager"}  # trop dur quand on est malade
STORY_WAIT_SECONDS = 10.0  # secondes réelles : au-delà, la nouvelle paraît avec son texte fixe
BUILD_HOURS = (8 * 60, 20 * 60)   # on peut cogner jusqu'à 20 h (après le souper, l'été)
EVENING = 17 * 60
ENCOUNTER_RADIUS = 6       # dehors, on ne jase qu'avec quelqu'un d'assez proche

SAVE_VERSION = 4
# v1 : avant l'économie ; v2 : avant plans et réflexions ; v3 : avant les scénarios (monde « maison »)
SUPPORTED_SAVE_VERSIONS = {1, 2, 3, 4}


class Engine:
    def __init__(self, config: AppConfig, house: House, agents: list[Agent], clock: SimClock,
                 rng: random.Random, bus: EventBus | None = None, llm: LLMService | None = None) -> None:
        self.config = config
        self.house = house
        self.agents = agents
        self.clock = clock
        self.rng = rng
        self.bus = bus or EventBus()
        self.llm = llm
        self.calendar = Calendar(date.fromisoformat(config.world.date_depart), config.world.vacances_semaines)
        clock.calendar = self.calendar
        self.scheduler = Scheduler(self.calendar)
        self.careers = Careers(self)  # emploi, promotions, études, école (sim/career.py)
        self._calendar_day = -1   # dernier jour où le calendrier a été appliqué (maladie, paie des congés)
        self._rehouse_day = -1    # dernier soir où l'on a vérifié les places libres dans les lits
        self.pending_decisions: dict[str, PendingDecision] = {}
        self.pending_dialogues: list[PendingDialogue] = []
        self.pair_last_talk: dict[str, int] = {}  # paire -> minute absolue de la dernière conversation
        # agent -> (future du résumé, nombre d'événements couverts)
        self.pending_summaries: dict[str, tuple[Future[StructuredResult[MemorySummary]], int]] = {}
        self.economy = Economy(config.economy)
        self.random_events = RandomEvents(config.events)
        self.last_event: tuple[str, bool, int] | None = None  # (texte, bonne nouvelle, minute)
        self.game_over = False
        self.mind = Mind(self)
        self.social = Social(self)
        self.architect = Architect(self)
        self.family = FamilyLife(self)
        self.inventory = Inventory(self)
        self.garage = Garage(self)
        self.credit = Credit(self)
        self.history = History(self.bus)  # conversations, actions, pensées, événements
        self.portraits = Portraits(self)  # fiche personnage : humeur et avis, avec la voix de l'IA
        # Événements tirés dont le LLM écrit le récit : (événement, texte fixe, future, envoi en temps réel)
        self.pending_stories: list[tuple] = []

    # ------------------------------------------------------------------ utilitaires

    def alive_count(self) -> int:
        return sum(not a.dead for a in self.agents)

    def car_home(self) -> bool:
        """L'auto est achetée et personne n'est parti avec."""
        return bool(self.garage.at_home())

    def agent_by_id(self, agent_id: str) -> Agent | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def room_of(self, agent: Agent) -> str:
        return self.house.room_at(agent.pos) or agent.last_room or "Couloir"

    def publish(self, kind: str, **data) -> None:
        self.bus.publish(Event(kind, self.clock.total_minutes, data))

    def _occupied(self, exclude: Agent) -> set[Pos]:
        return {a.action.use_pos for a in self.agents
                if a is not exclude and not a.is_away and a.action and a.action.use_pos}

    def _free_spot(self, agent: Agent, obj: InteractiveObject) -> Pos | None:
        occupied = self._occupied(agent)
        free = [p for p in obj.use_positions if p not in occupied]
        return min(free, key=lambda p: manhattan(p, agent.pos)) if free else None

    def _object_spot(self, agent: Agent, kind: str) -> Pos | None:
        if kind == "lit":
            bed = self.house.objects.get(agent.bed_id) or self.house.objects.get(agent.persona.bed)
            candidates = [bed] if bed is not None else self.house.objects_of_kind("lit")
        else:
            candidates = self.house.objects_of_kind(kind)
        spots = [s for s in (self._free_spot(agent, o) for o in candidates) if s is not None]
        return min(spots, key=lambda p: manhattan(p, agent.pos)) if spots else None

    def _spot_near(self, agent: Agent, target: Agent) -> Pos | None:
        occupied = self._occupied(agent)
        tx, ty = target.pos
        spots = [(tx + dx, ty + dy) for dx, dy in NEIGHBORS]
        spots = [p for p in spots if self.house.is_walkable(p) and p not in occupied]
        return min(spots, key=lambda p: manhattan(p, agent.pos)) if spots else None

    # ------------------------------------------------------------------ initialisation

    def initialize(self) -> None:
        """Place les agents : au lit s'ils dorment à l'heure de départ, sinon à la cuisine."""
        for agent in self.agents:
            agent.needs = Needs(**{n: self.rng.uniform(55, 85) for n in Needs.model_fields})
            agent.pos = self.house.spawn_tile(self.rng)
            scheduled = self.scheduler.check(agent, self.clock)
            if scheduled and scheduled.action == "dormir":
                action = self.make_action(agent, "dormir", forced=True, until=scheduled.until)
                if action and action.use_pos:
                    agent.pos = action.use_pos
                    action.started = True
                    agent.action = action
            agent.last_room = self.house.room_at(agent.pos)
        self.family.initialize()
        self.careers.setup()

    # ------------------------------------------------------------------ actions

    def make_action(self, agent: Agent, name: str, target: str | None = None, forced: bool = False,
                    until: int | None = None, reason: str = "") -> ActiveAction | None:
        """Construit une action réalisable ou None (objet occupé, cible introuvable)."""
        definition = ACTIONS[name]
        target_name = target
        use_pos: Pos | None = None
        vehicle_id: str | None = None
        if name == "jaser":
            other = self.agent_by_id(target or "")
            if other is None or not other.is_available:
                return None
            target_name = other.name
            use_pos = self._spot_near(agent, other)
            if use_pos is None:
                return None
        elif name == "flaner":
            room = self.room_of(agent)
            nearby = [p for p in self.house.walkable_tiles(room) if manhattan(p, agent.pos) <= FLANER_RADIUS]
            use_pos = self.rng.choice(nearby) if nearby else agent.pos
        elif name in AWAY_ACTIONS:
            # Le véhicule libre le plus utile s'il y en a un ; sinon l'arrêt d'autobus, partagé par tous
            vehicle = self.garage.best_for(agent, "epicerie" if name == "epicerie" else "travail")
            if vehicle is not None:
                use_pos, vehicle_id = vehicle.uses[0], vehicle.object_id
            else:
                use_pos = self.house.objects_of_kind("porte")[0].use_positions[0]
        elif name == "acheter":
            item = CATALOG.get(target or "")
            if item is None or self.economy.owns(item.id):
                return None
            target_name = f"{item.label} ({item.price:,.0f} $)".replace(",", " ")
        elif name == "tondre":
            use_pos = self.rng.choice(self.house.lawn_tiles())
        elif name == "carriere":
            target_name = self.careers.target_name(target)
            if target_name is None:
                return None
        elif name in ("acheter_objet", "revendre"):
            if name == "acheter_objet":
                item = self.inventory.catalogue.get((target or "").split("|")[0])
                target_name = item.label if item else None
            else:
                target_name = self.inventory.target_name(target)
            if target_name is None:
                return None
        elif name == "soigner":
            baby = self.agent_by_id(target or "")
            if baby is None or baby.dead or baby.is_away:
                return None
            target_name = baby.name
            crib = self.house.objects.get(baby.bed or "")
            occupied = self._occupied(agent)
            spots = [p for p in (crib.use_positions if crib else []) if p not in occupied]
            if not spots:  # place devant le berceau prise : n'importe quelle case libre tout près
                bx, by = baby.pos
                spots = sorted((p for p in ((bx + dx, by + dy) for dx in range(-2, 3) for dy in range(-2, 3))
                                if self.house.is_walkable(p) and p not in occupied),
                               key=lambda p: manhattan(p, baby.pos))
            use_pos = spots[0] if spots else None
            if use_pos is None:
                return None
        elif name in ("construire", "engager"):
            room = self.architect.plan.room(target or "") if self.architect.plan else None
            if room is None:
                return None
            target_name = room.name.lower()
            if name == "construire":
                occupied = self._occupied(agent)
                spots = [p for p in room.interior_tiles() if self.house.is_walkable(p) and p not in occupied]
                if not spots:
                    return None
                use_pos = min(spots, key=lambda p: manhattan(p, agent.pos))
        elif name == "couper":
            found = self._nearest_tree(agent, clearing=target == "defrichage")
            if found is None:
                return None
            tree, use_pos = found
            target, target_name = tree.id, tree.label.lower()
        elif definition.object_kind is not None:
            use_pos = self._object_spot(agent, definition.object_kind)
            if use_pos is None:
                return None
        if name == "acheter_vehicule":
            model = self.garage.models.get(target or "")
            if model is None:
                return None
            target_name = model.label
        elif name == "emprunter":
            target_name = (target or "").split("|")[-1].replace("_", " ")
        elif name == "rembourser":
            loan = next((l for l in self.economy.household.loans if str(l.uid) == target), None)
            if loan is None:
                return None
            target_name = loan.label
        duration = definition.duration
        if name == "couper" and self.economy.owns("scie"):
            duration = round(duration * SAW_FACTOR)
        return ActiveAction(name=name, target=target, target_name=target_name, use_pos=use_pos,
                            remaining=duration, until_minute=until, forced=forced,
                            reason=reason, vehicle=vehicle_id)

    def _nearest_tree(self, agent: Agent, clearing: bool = False) -> tuple[InteractiveObject, Pos] | None:
        """Arbre le plus proche qu'on peut atteindre (par la lisière) et que personne d'autre ne coupe.

        clearing : seulement les arbres sur l'emplacement de la prochaine pièce ; s'ils sont encore hors
        d'atteinte, l'arbre accessible le plus proche de l'emplacement (on ouvre le chemin).
        """
        occupied = self._occupied(agent)
        taken = {a.action.target for a in self.agents
                 if a is not agent and a.action is not None and a.action.name == "couper"}
        trees = self.house.objects_of_kind("arbre")
        origin = agent.pos
        if clearing:
            wanted = self.architect.clearing_trees()
            ids = {t.id for t in wanted}
            reachable = [t for t in wanted if t.id not in taken and any(s not in occupied for s in t.use_positions)]
            if reachable:
                trees = reachable
            elif wanted:
                x0, y0 = wanted[0].rect[:2]
                origin = (x0, y0)  # aucun accessible : on coupe vers l'emplacement
                trees = [t for t in trees if t.id not in ids]
        best: tuple[int, InteractiveObject, Pos] | None = None
        for tree in trees:
            if tree.id in taken:
                continue
            for spot in tree.use_positions:
                if spot in occupied:
                    continue
                distance = manhattan(spot, origin)
                if best is None or distance < best[0]:
                    best = (distance, tree, spot)
        return (best[1], best[2]) if best else None

    def start_action(self, agent: Agent, action: ActiveAction) -> bool:
        agent.path = []
        if action.use_pos is not None and action.use_pos != agent.pos:
            if not agent.set_destination(action.use_pos, self.house.is_walkable):
                return False
        agent.action = action
        self.publish("action", agent=agent.id, name=agent.name, action=action.name,
                     label=action.label, forced=action.forced, reason=action.reason)
        if action.name in MEMORABLE_ACTIONS:
            self.remember(agent, MEMORABLE_ACTIONS[action.name], 1)
        self.mind.on_action_started(agent, action)
        return True

    def options_for(self, agent: Agent) -> list[Option]:
        """Actions possibles maintenant, triées par score décroissant."""
        favorites = agent.persona.favorite_actions
        room = self.room_of(agent)
        options: list[Option] = []
        for definition in ACTIONS.values():
            if not definition.selectable or not is_allowed(definition, agent.persona.keys, agent.needs):
                continue
            if definition.daytime_only and not DAYTIME_HOURS[0] <= self.clock.minute_of_day < DAYTIME_HOURS[1]:
                continue
            if definition.name == "jaser":
                base = score_action(definition, agent.needs, favorites)
                for other in self.agents:
                    if other is agent or not other.is_available:
                        continue
                    bonus = 1.3 if self.room_of(other) == room else 1.0
                    bonus *= agent.relation(other.id).chat_factor()
                    options.append(Option(action="jaser", target=other.id,
                                          label=action_label("jaser", other.name),
                                          score=round(base * bonus, 2)))
                continue
            if definition.object_kind and self._object_spot(agent, definition.object_kind) is None:
                continue
            if definition.name == "veiller" and (self.clock.minute_of_day < EVENING
                                                 or self.economy.household.wood < 1):
                continue  # une veillée, c'est le soir, et il faut une bûche
            if self.economy.enabled and not self._has_food_for(definition.name):
                continue
            score = score_action(definition, agent.needs, favorites)
            if definition.name == "flaner":
                score = max(score, 0.5)
            options.append(Option(action=definition.name, label=definition.label, score=score))
        options += self._economic_options(agent) + self._care_options(agent)
        if self.is_sick(agent):  # malade : on se repose, pas de gros travaux
            options = [o for o in options if o.action not in SICK_FORBIDDEN]
            if self._object_spot(agent, "lit") is not None:
                options.append(Option(action="sieste", label="se repose au lit (malade)", score=30.0))
        self.inventory.boost(agent, options)
        self.mind.boost(agent, options)
        options.sort(key=lambda o: (o.urgent, o.score), reverse=True)
        return options

    def _has_food_for(self, action: str) -> bool:
        return self.economy.household.pantry + 1e-9 >= self.economy.portions_for(action)

    def _economic_options(self, agent: Agent) -> list[Option]:
        """Tonte (dès 13 ans), puis épicerie, heures sup et achats (adultes seulement)."""
        eco = self.economy
        if not eco.enabled:
            return []
        options = self._yard_options(agent) + self._wood_options(agent) + self._building_options(agent)
        if not agent.persona.is_adult:
            return options
        options += self._purchase_options(agent) + self.inventory.options_for(agent) + self.garage.options_for(agent)
        options += self.credit.options_for(agent) + self.careers.options_for(agent)
        return options + self._money_options(agent)

    def _yard_options(self, agent: Agent) -> list[Option]:
        if self.house.layout.wild:
            return []  # terrain sauvage : pas de pelouse à tondre
        lawn = self.economy.household.lawn
        minute = self.clock.minute_of_day
        someone_mowing = any(a.action is not None and a.action.name == "tondre" for a in self.agents)
        if (agent.persona.age >= 13 and self.economy.owns("tondeuse") and lawn >= LAWN_MOW_FROM
                and not someone_mowing and 9 * 60 <= minute < 19 * 60):
            score = round(5 + (lawn - LAWN_MOW_FROM) / (100 - LAWN_MOW_FROM) * 25, 2)
            return [Option(action="tondre", label=f"tond la pelouse (gazon à {lawn:.0f} %)", score=score)]
        return []

    def _care_options(self, agent: Agent) -> list[Option]:
        """S'occuper d'un bébé (dès 13 ans) : d'autant plus pressant que son besoin est bas."""
        if agent.persona.age < 13:
            return []
        options = []
        # Un parent affamé ou épuisé se soigne d'abord (sinon il tomberait avant le bébé)
        self_first = agent.needs.lowest()[1] < URGENT_THRESHOLD
        for baby, need, value in self.family.babies_needing_care():
            if value >= 70:
                continue
            label = f"s'occupe de {baby.name} ({NEED_LOW_WORDS[need]})"
            options.append(Option(action="soigner", target=baby.id, label=label,
                                  score=round(5 + (100 - value) / 3, 2),
                                  urgent=value < URGENT_THRESHOLD + 5 and not self_first))
        return options

    def _wood_options(self, agent: Agent) -> list[Option]:
        """Terrain : couper du bois (dès 16 ans, de jour), d'autant plus pressant que la réserve est basse."""
        wood = self.economy.household.wood
        minute = self.clock.minute_of_day
        if not self.house.layout.wild or agent.persona.age < 16 or not self.family.heavy_work_ok(agent):
            return []
        if not CUT_HOURS[0] <= minute < CUT_HOURS[1] or not self.house.objects_of_kind("arbre"):
            return []
        clearing = self.architect.clearing_trees()
        if clearing:
            room = self.architect.clearing_room()
            label = f"défriche l'emplacement de la future {room.name.lower()} ({len(clearing)} arbres)"
            return [Option(action="couper", target="defrichage", label=label, score=16.0)]
        # Le chantier en cours fixe la réserve visée : il faut assez de bûches pour le finir
        missing = self.architect.wood_missing()
        target = max(WOOD_TARGET, wood + missing) if missing else WOOD_TARGET
        if wood >= (max(WOOD_MAX, target) if missing else WOOD_MAX):
            return []
        score = round(4 + max(0, target - wood) / target * 20, 2)
        tool = "à la scie à chaîne" if self.economy.owns("scie") else "à la hache"
        return [Option(action="couper", label=f"coupe un arbre {tool} (réserve : {wood} bûches)", score=score)]

    def _building_options(self, agent: Agent) -> list[Option]:
        """Terrain : lancer le chantier, y travailler, ou engager un entrepreneur."""
        architect = self.architect
        room = architect.site_room() if architect.active else None
        minute = self.clock.minute_of_day
        if room is None or room.contractor or agent.persona.age < 16 or not self.family.heavy_work_ok(agent):
            return []
        options: list[Option] = []
        name = room.name.lower()
        wood = self.economy.household.wood
        if BUILD_HOURS[0] <= minute < BUILD_HOURS[1] and wood >= 1:
            if room.materials_paid:
                label = f"travaille sur le chantier de la {name} ({room.fraction * 100:.0f} % fait)"
                bonus = 6 if architect.skill(agent) > 1 else 0
                options.append(Option(action="construire", target=room.id, label=label, score=12.0 + bonus))
            elif architect.can_afford_materials(room):
                label = (f"lance le chantier de la {name} ({room.materials_cost:.0f} $ de matériaux, "
                         f"{room.wood_needed} bûches, {room.work_needed:.0f} h de travail)")
                options.append(Option(action="construire", target=room.id, label=label, score=14.0))
        if agent.persona.is_adult and architect.can_hire(room):
            price, days = architect.quote(room)
            label = f"engage un entrepreneur pour finir la {name} ({price:.0f} $, ~{days} jours)"
            options.append(Option(action="engager", target=room.id, label=label, score=4.0))
        return options

    def _purchase_options(self, agent: Agent) -> list[Option]:
        """Achats permis seulement s'il reste un coussin de deux semaines de dépenses."""
        options = []
        allowed = self.house.layout.catalog
        for item in self.economy.affordable(self.alive_count()):
            if allowed is not None and item.id not in allowed:
                continue
            weekly = f", puis {item.weekly_cost:.0f} $/semaine" if item.weekly_cost else ""
            label = f"achète {item.label} ({item.price:,.0f} ${weekly}) : {item.benefit}".replace(",", " ")
            options.append(Option(action="acheter", target=item.id, label=label, score=6.0))
        return options

    def _money_options(self, agent: Agent) -> list[Option]:
        eco = self.economy
        cfg = eco.config
        open_from, open_to = (parse_hhmm(h) for h in cfg.shop_hours)
        minute = self.clock.minute_of_day
        if not open_from <= minute < open_to:
            return []
        options: list[Option] = []
        days = eco.pantry_days(self.alive_count())
        shopper_out = any(a.away_kind == "epicerie" or (a.action and a.action.name == "epicerie")
                          for a in self.agents if a is not agent)
        if days < cfg.low_pantry_days and eco.household.money >= eco.portion_price() and not shopper_out:
            label = (f"va faire l'épicerie (garde-manger : {eco.household.pantry:.0f} portions, "
                     f"{eco.household.money:.0f} $ en banque)")
            options.append(Option(action="epicerie", label=label, score=round(20 + (cfg.low_pantry_days - days) * 20, 2),
                                  urgent=days < 0.5))
        weekday = self.clock.weekday < 5 and not self.calendar.agent_off(agent, self.clock.day)
        laid_off = agent.unemployed_until is not None
        if eco.household.money < cfg.overtime_below and agent.persona.salary_per_day > 0 and weekday \
                and not laid_off and minute + cfg.overtime_minutes <= open_to:
            pay = self._overtime_pay(agent)
            label = f"part faire des heures supplémentaires (+{pay:.0f} $, {cfg.overtime_minutes // 60} h)"
            gap = (cfg.overtime_below - eco.household.money) / cfg.overtime_below
            options.append(Option(action="heures_sup", label=label, score=round(10 + gap * 30, 2)))
        return options

    def _overtime_pay(self, agent: Agent) -> float:
        cfg = self.economy.config
        return round(agent.persona.salary_per_day / 8 * cfg.overtime_rate * cfg.overtime_minutes / 60, 2)

    def pick_deterministic(self, agent: Agent, options: list[Option]) -> Option:
        """Option urgente ou besoin urgent : meilleure option ; sinon tirage pondéré parmi les 3 meilleures."""
        if options[0].urgent or agent.needs.lowest()[1] < URGENT_THRESHOLD:
            return options[0]
        top = options[:3]
        weights = [max(o.score, 0.01) for o in top]
        return self.rng.choices(top, weights=weights, k=1)[0]

    def _choose(self, agent: Agent) -> None:
        options = self.options_for(agent)
        if not options:
            return
        planned = self.mind.planned_option(agent, options)
        if planned is not None:
            option, item = planned
            note = f"Prévu : {item.note}" if item.note else "Comme prévu"
            action = self.make_action(agent, option.action, option.target, reason=note)
            if action is not None and self.start_action(agent, action):
                item.status = "done"
                return
            # Objet occupé : on fait autre chose et on retentera pendant la fenêtre du plan
        pick = self.pick_deterministic(agent, options)
        if self._should_ask_llm(agent, options) and self._request_decision(agent, options, pick):
            return
        self._start_option(agent, pick.action, pick.target, "", options)

    def _start_option(self, agent: Agent, name: str, target: str | None, reason: str,
                      options: list[Option]) -> None:
        """Démarre l'option voulue, ou à défaut la première autre option réalisable."""
        candidates = [(name, target, reason)] + [(o.action, o.target, "") for o in options]
        for cand_name, cand_target, cand_reason in candidates:
            action = self.make_action(agent, cand_name, cand_target, reason=cand_reason)
            if action and self.start_action(agent, action):
                return

    # ------------------------------------------------------------------ décisions LLM

    def memories_for(self, agent: Agent, about: list[str] | None = None) -> tuple[list[str], str | None]:
        """Souvenirs les plus utiles (fraîcheur, importance, lien avec about) + dernier résumé."""
        cfg = self.config.memory
        now = self.clock.total_minutes
        query = keywords(" ".join(t for t in (about or []) if t))
        events = agent.memory.retrieve(now, query, cfg.recall_count, cfg.recency_half_life_hours)
        return [e.formatted_at(now) for e in events], agent.memory.latest_summary

    # ------------------------------------------------------------------ mémoire

    def remember(self, agent: Agent, text: str, importance: int = 3, kind: str = "event") -> None:
        """Ajoute un souvenir ; importance de 1 (banal) à 10 (inoubliable)."""
        cfg = self.config.memory
        agent.memory.add(self.clock.total_minutes, self.clock.hhmm, text, cfg.short_term_size, importance,
                         kind, cfg.keep_from_importance, cfg.long_term_size)
        if agent.memory.since_summary >= cfg.summary_every and agent.id not in self.pending_summaries:
            self._request_summary(agent)

    def _request_summary(self, agent: Agent) -> None:
        if self.llm is None:
            return
        events = agent.memory.pending_for_summary()
        request = build_summary_request(agent, events, agent.memory.latest_summary, self.config.llm.max_tokens)
        # Repli sans LLM : les derniers événements mis bout à bout
        fallback = MemorySummary(summary=" ; ".join(e.split("] ", 1)[-1] for e in events[-3:])[:300])
        future = self.llm.try_submit(request, MemorySummary, fallback)
        if future is not None:
            self.pending_summaries[agent.id] = (future, len(events))

    def _poll_summaries(self) -> None:
        for agent_id, (future, covered) in list(self.pending_summaries.items()):
            if not future.done():
                continue
            del self.pending_summaries[agent_id]
            agent = self.agent_by_id(agent_id)
            try:
                result = future.result()
            except Exception as exc:
                result = StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
            if agent is None or result.value is None:
                continue
            agent.memory.add_summary(result.value.summary.strip(), covered, self.config.memory.max_summaries)
            self.publish("resume", agent=agent.id, name=agent.name, summary=result.value.summary,
                         ok=result.ok, error=result.error)

    def _should_ask_llm(self, agent: Agent, options: list[Option]) -> bool:
        cfg = self.config.llm
        return (self.llm is not None and cfg.decisions_enabled and len(options) >= 2
                and not options[0].urgent
                and agent.needs.lowest()[1] >= URGENT_THRESHOLD
                and self.clock.total_minutes - agent.last_decision_minute >= cfg.decision_cooldown_minutes)

    def _request_decision(self, agent: Agent, options: list[Option], pick: Option) -> bool:
        assert self.llm is not None
        top = options[:6]
        room = self.room_of(agent)
        present = [a.name for a in self.agents if a is not agent and a.is_available and self.room_of(a) == room]
        about = [room, *present, agent.plan.intention if agent.plan else "", agent.goal.text if agent.goal else ""]
        memories, summary = self.memories_for(agent, about)
        request = build_decision_request(agent, room, self.clock.label(), top,
                                         memories, summary, self.config.llm.max_tokens,
                                         self.family_context([agent]), self._prompt_meta(),
                                         now=self.clock.total_minutes, family=self.agents)
        names = {a.id: a.name for a in self.agents}
        fallback = ActionDecision(action=pick.action, target=pick.target, reason="")
        future = self.llm.try_submit(request, ActionDecision, fallback,
                                     lambda decision: validate_decision(decision, top, names))
        if future is None:  # limite d'appels par minute atteinte
            return False
        self.pending_decisions[agent.id] = PendingDecision(future, options, fallback, self.clock.total_minutes)
        agent.thinking = True
        agent.last_decision_minute = self.clock.total_minutes
        return True

    def _cancel_decision(self, agent: Agent) -> None:
        self.pending_decisions.pop(agent.id, None)
        agent.thinking = False

    def poll(self) -> None:
        """Appelé à chaque image (fil principal) : applique les réponses LLM arrivées."""
        self._poll_dialogues()
        self._poll_summaries()
        self.mind.poll()
        self._poll_stories()
        self.social.poll()
        self.architect.poll()
        self.family.poll()
        self.portraits.poll()
        for agent_id, pending in list(self.pending_decisions.items()):
            if not pending.future.done():
                continue
            del self.pending_decisions[agent_id]
            agent = self.agent_by_id(agent_id)
            if agent is None:
                continue
            agent.thinking = False
            try:
                result = pending.future.result()
            except Exception as exc:  # erreur inattendue dans le thread : on se rabat sur le repli
                result = StructuredResult(value=pending.fallback, ok=False, attempts=0, error=str(exc))
            decision = result.value or pending.fallback
            self.publish("decision", agent=agent.id, name=agent.name, action=decision.action,
                         target=decision.target, reason=decision.reason, ok=result.ok,
                         attempts=result.attempts, error=result.error)
            if agent.action is None and not agent.is_away:
                self._start_option(agent, decision.action, decision.target, decision.reason, pending.options)
                if result.ok and decision.reason and agent.action is not None:
                    self.remember(agent, f"J'ai décidé : {agent.action.label} (« {decision.reason} »)", 2)

    def _check_decision_timeout(self, agent: Agent) -> None:
        pending = self.pending_decisions.get(agent.id)
        if pending is None:
            agent.thinking = False
            return
        if self.clock.total_minutes - pending.requested_minute > self.config.llm.decision_max_wait_minutes:
            self._cancel_decision(agent)
            self.publish("decision", agent=agent.id, name=agent.name, action=pending.fallback.action,
                         target=pending.fallback.target, reason="", ok=False, attempts=0,
                         error="attente trop longue")
            self._start_option(agent, pending.fallback.action, pending.fallback.target, "", pending.options)

    # ------------------------------------------------------------------ boucle

    def tick(self) -> None:
        if self.game_over:
            return
        self.clock.advance()
        if self.economy.bills_due(self.clock):
            self._charge_bills()
        if self.economy.enabled and self.random_events.due(self.clock, self.economy.household):
            self._roll_events()
        household = self.economy.household
        yard_due = self.clock.minute_of_day >= 6 * 60 and household.last_lawn_day != self.clock.day
        if self.economy.enabled and not self.house.layout.wild and yard_due:
            self._daily_yard()
        if self.clock.minute_of_day >= 5 * 60 and self._calendar_day != self.clock.day:
            self._calendar_day = self.clock.day
            self._daily_calendar()
        if self.clock.minute_of_day >= 19 * 60 and self._rehouse_day != self.clock.day:
            self._rehouse_day = self.clock.day
            self.inventory.rehouse()   # avant le coucher : une place libre dans un vrai lit ne reste pas vide
        for agent in self.agents:
            self._update_agent(agent)
        self.social.update()
        self.architect.update()
        self.family.update()
        if self.economy.enabled:
            self.inventory.update()
        self._detect_encounters()

    def _roll_events(self) -> None:
        """Effets appliqués tout de suite ; le LLM raconte ensuite le fait (repli : le texte fixe)."""
        family = [a for a in self.agents if not a.dead]
        for event, text in self.random_events.roll(self, self.rng):
            if self.llm is not None and self.config.events.narrate:
                request = build_story_request(text, event.good, self.family_context(family),
                                              self.config.llm.max_tokens)
                future = self.llm.try_submit(request, EventStory, None,
                                             lambda story, base=text: validate_story(story, base))
                if future is not None:
                    self.pending_stories.append((event, text, future, time.monotonic()))
                    continue
            self._news(text, event.good, event.id)

    def _poll_stories(self) -> None:
        now = time.monotonic()  # temps réel : à vitesse x30, 30 minutes de jeu ne durent qu'une seconde
        for item in list(self.pending_stories):
            event, base, future, submitted = item
            if future.done():
                self.pending_stories.remove(item)
                try:
                    story = future.result().value
                except Exception:  # erreur inattendue dans le thread : le texte fixe
                    story = None
                self._news(story.text if story else base, event.good, event.id)
            elif now - submitted > STORY_WAIT_SECONDS:
                self.pending_stories.remove(item)
                self._news(base, event.good, event.id)  # le récit tarde : on n'attend pas

    def family_context(self, agents: list[Agent]) -> str:
        """Situation de la famille pour les prompts : argent, santé, chômage, deuils, dernière nouvelle."""
        now = self.clock.total_minutes
        lines = []
        if self.economy.enabled:
            lines.append(self.economy.summary(self.alive_count()) + ".")
            pantry = self.economy.pantry_lines(self.clock.day)
            if pantry:
                lines.append("Dans le garde-manger : " + " ; ".join(pantry[:8]) + ".")
            if self.house.layout.wild:
                trees = len(self.house.objects_of_kind("arbre"))
                roof = "" if self.has_roof() else " On vit encore sous la tente, sans maison."
                lines.append(f"Bois coupé en réserve : {self.economy.household.wood} bûches ; "
                             f"il reste {trees} arbres sur le terrain.{roof}")
                project = self.architect.context_line()
                if project:
                    lines.append(project)
        lines += self.calendar_lines(agents)
        lines += self.family.context_lines()
        for line in (self.careers.context_line(agents), self.inventory.context_line(), self.garage.context_line(),
                     self.credit.context_line()):
            if line:
                lines.append(line)
        departed = [a for a in self.agents if a.dead]
        if departed:
            names = ", ".join(f"{a.name} (jour {(a.died_minute or 0) // (24 * 60) + 1})" for a in departed)
            lines.append(f"Membres de la famille décédés : {names}.")
        for agent in agents:
            if agent.grieving_until is not None:
                lines.append(f"{agent.name} est en deuil.")
            if agent.unemployed_until is not None and now < agent.unemployed_until:
                days = -(-(agent.unemployed_until - now) // (24 * 60))
                lines.append(f"{agent.name} est en mise à pied, sans salaire, encore {days} jour(s).")
            if agent.health < 60:
                lines.append(f"{agent.name} est en mauvaise santé ({agent.health:.0f}/100).")
        if self.last_event and now - self.last_event[2] <= 2 * 24 * 60:
            lines.append(f"Nouvelle récente : {self.last_event[0]}")
        for promise in self.social.pending_for({a.id for a in agents}):
            lines.append(f"Promesse à tenir : {promise.text} ({self.social.when_label(promise.minute)}).")
        return "\n".join(lines)

    def _prompt_meta(self) -> dict:
        """Données structurées de la situation, utilisées par le provider mock."""
        return {
            "money": self.economy.household.money if self.economy.enabled else None,
            "pantry_days": self.economy.pantry_days(self.alive_count()) if self.economy.enabled else None,
            "departed": [a.name for a in self.agents if a.dead],
        }

    def _charge_bills(self) -> None:
        total = self.economy.charge_bills(self.clock)
        self.credit.charge()  # les paiements de prêts passent le même jour
        money = self.economy.household.money
        self.publish("factures", amount=-total, money=money, detail=self.economy.weekly_bill_items())
        for agent in self.agents:
            if agent.persona.is_adult:
                warning = " On est dans le rouge." if money < 0 else ""
                self.remember(agent, f"Les factures sont passées : {total:.0f} $ (solde {money:.0f} $).{warning}",
                              7 if money < 0 else 4)

    # ------------------------------------------------------------------ rencontres et dialogues

    def _talking_ids(self) -> set[str]:
        pending = {agent_id for p in self.pending_dialogues for agent_id in p.participant_ids}
        return pending | self.social.talking_ids()

    def _pair_ready(self, a: str, b: str) -> bool:
        last = self.pair_last_talk.get(pair_key(a, b))
        return last is None or self.clock.total_minutes - last >= self.social.pair_cooldown(a, b)

    def _detect_encounters(self) -> None:
        """Deux agents ou plus dans la même pièce, cooldown écoulé : on demande un dialogue."""
        if self.llm is None:
            return
        busy = self._talking_ids()
        by_room: dict[str, list[Agent]] = {}
        for agent in self.agents:
            room = self.house.room_at(agent.pos)
            if room is not None and agent.is_available and agent.id not in busy:
                by_room.setdefault(room, []).append(agent)

        for room, present in by_room.items():
            if room in self.house.outdoor_rooms:
                # Dehors (un grand terrain) : seulement les personnes à portée de voix
                present = [a for a in present
                           if any(b is not a and manhattan(a.pos, b.pos) <= ENCOUNTER_RADIUS for b in present)]
            if len(present) < 2:
                continue
            candidates = present[:]
            self.rng.shuffle(candidates)
            for first in candidates:
                group = [first]
                for other in candidates:
                    if other is first or len(group) >= self.config.dialogue.max_participants:
                        continue
                    if all(self._pair_ready(other.id, member.id) for member in group):
                        group.append(other)
                if len(group) >= 2:
                    self._request_dialogue(group, room)
                    break

    def _request_dialogue(self, group: list[Agent], room: str) -> bool:
        assert self.llm is not None
        if self.config.dialogue.mode == "tour_par_tour":
            if not self.social.start(group, room):
                return False
            self._mark_talk(group)
            return True
        memories, summaries = {}, {}
        for agent in group:
            about = [room, *(a.name for a in group if a is not agent)]
            memories[agent.id], summaries[agent.id] = self.memories_for(agent, about)
        request = build_dialogue_request(group, room, self.clock.label(), memories, summaries,
                                         self.config.llm.max_tokens, self.family_context(group),
                                         self._prompt_meta(), now=self.clock.total_minutes)
        names = {a.id: a.name for a in group}
        future = self.llm.try_submit(request, Dialogue, None, lambda d: validate_dialogue(d, names))
        if future is None:
            return False
        self._mark_talk(group)
        self.pending_dialogues.append(PendingDialogue(future, [a.id for a in group], room,
                                                      self.clock.total_minutes))
        return True

    def _mark_talk(self, group: list[Agent]) -> None:
        """Le cooldown démarre à la demande : évite de relancer la même paire pendant l'attente."""
        now = self.clock.total_minutes
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                self.pair_last_talk[pair_key(a.id, b.id)] = now

    def _poll_dialogues(self) -> None:
        for pending in [p for p in self.pending_dialogues if p.future.done()]:
            self.pending_dialogues.remove(pending)
            names = [a.name for a in (self.agent_by_id(i) for i in pending.participant_ids) if a]
            try:
                result = pending.future.result()
            except Exception as exc:
                result = StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
            if not result.ok or result.value is None:
                self.publish("dialogue_echec", room=pending.room, participants=names, error=result.error)
                continue
            lines = [line.model_dump() for line in result.value.lines]
            for agent_id in pending.participant_ids:
                agent = self.agent_by_id(agent_id)
                if agent is not None:
                    agent.needs.apply({"social": self.config.dialogue.social_gain})
            self.publish("dialogue", room=pending.room, participants=names, lines=lines,
                         time=self.clock.hhmm, attempts=result.attempts, mode="scene")
            # Le bilan écrit les souvenirs, ajuste les relations et relève les promesses
            self.social.request_debrief(pending.participant_ids, pending.room,
                                        [(l["speaker"], l["text"]) for l in lines], with_feelings=True)

    def _update_agent(self, agent: Agent) -> None:
        if agent.dead:
            return
        minutes = self.clock.tick_minutes
        now = self.clock.total_minutes
        if agent.grieving_until is not None and now >= agent.grieving_until:
            agent.grieving_until = None
        if agent.unemployed_until is not None and now >= agent.unemployed_until:
            agent.unemployed_until = None
            self.remember(agent, "La mise à pied est finie : retour au travail.", 5)
        if self._update_health(agent, minutes):
            return  # vient de mourir ou d'être hospitalisé

        if agent.is_away:
            agent.needs.decay(minutes, "away")
            if now >= (agent.away_until or 0):
                self._return_home(agent)
            return
        if agent.persona.stage == "bebe" and self.family.active:
            self.family.update_baby(agent)  # dort, part à la garderie (porté), attend les soins
            return

        agent.needs.decay(minutes, "sleeping" if agent.is_sleeping else "awake")
        if agent.is_sleeping:
            bed = self.house.object_at_spot(agent.pos)
            if bed is not None and bed.quality < 1:
                # Sous la tente, on dort moins bien qu'au chaud dans un lit
                agent.needs.apply({"energy": -12.0 * (1 - bed.quality) * minutes / 60})
        elif self.house.layout.wild and not self.has_roof():
            agent.needs.apply({"fun": -NO_ROOF_FUN_PER_HOUR * minutes / 60})
        if self.economy.in_debt and agent.persona.is_adult and not agent.is_sleeping:
            # Les dettes gâchent le moral des parents
            agent.needs.apply({"fun": -self.economy.config.debt_fun_penalty_per_hour * minutes / 60})

        scheduled = self.scheduler.check(agent, self.clock)
        if scheduled is not None:
            name = scheduled.action
            if name == "cuisiner" and self.clock.weekday >= 5 and "bbq" in self.house.objects:
                name = "bbq"  # la fin de semaine, le souper se fait sur le BBQ
            action = self.make_action(agent, name, scheduled.target, forced=True,
                                      until=scheduled.until)
            started = False
            if action is not None:
                if scheduled.target:
                    action.target_name = away_phrase(scheduled.target)
                started = self.start_action(agent, action)
            if started:
                self._cancel_decision(agent)
            else:
                # Objet occupé ou chemin bloqué : on retentera au prochain tick (dans la fenêtre)
                agent.fired.pop(scheduled.key, None)

        if not agent.is_sleeping:
            self.mind.update(agent)
        if agent.thinking:
            self._check_decision_timeout(agent)
        if agent.action is None and not agent.thinking:
            self._choose(agent)
        self._progress(agent, now)

    def _progress(self, agent: Agent, now: int) -> None:
        action = agent.action
        if action is None:
            return
        minutes = self.clock.tick_minutes

        if not action.started:
            agent.walk(self.config.sim.move_tiles_per_tick)
            room = self.house.room_at(agent.pos)
            if room is not None:
                agent.last_room = room
            if agent.path:
                return
            if action.use_pos is not None and agent.pos != action.use_pos:
                # Chemin interrompu (case prise entre-temps) : on recalcule ou on abandonne
                if not agent.set_destination(action.use_pos, self.house.is_walkable):
                    agent.action = None
                return
            action.started = True
            if action.name in AWAY_ACTIONS:
                self._leave(agent, action)
            elif not self._eat(agent, action.name) or not self._burn_wood(agent, action):
                agent.action = None
            elif action.name == "construire" and not self.architect.start_session(agent, action.target):
                agent.action = None  # plus de bois, ou pas les moyens d'acheter les matériaux
            return

        definition = ACTIONS[action.name]
        if definition.duration > 0:
            # Un baril d'eau lave moins bien qu'une douche, une tente repose moins qu'un lit
            spot = self.house.object_at_spot(agent.pos)
            quality = spot.quality if spot is not None else 1.0
            effects = {need: gain * quality if gain > 0 else gain for need, gain in definition.effects.items()}
            agent.needs.apply(effects, minutes / definition.duration)
        action.remaining -= minutes
        if action.until_minute is not None:
            done = now >= action.until_minute
        else:
            done = action.remaining <= 0
        if done:
            agent.action = None
            self._on_done(agent, action)

    def _on_done(self, agent: Agent, action: ActiveAction) -> None:
        """Effets de fin d'action sur le ménage (achat conclu, pelouse tondue)."""
        self.inventory.mark_used(action.use_pos)
        if action.name == "acheter" and action.target:
            self._buy(agent, action.target)
        elif action.name == "couper" and action.target:
            self._fell_tree(agent, action.target)
        elif action.name == "construire":
            self.architect.work(agent, action.target, ACTIONS["construire"].duration / 60)
        elif action.name == "engager":
            self.architect.hire(agent, action.target)
        elif action.name == "acheter_vehicule":
            self.garage.buy(agent, action.target)
        elif action.name == "emprunter":
            self.credit.borrow(agent, action.target)
        elif action.name == "rembourser":
            self.credit.repay(agent, action.target)
        elif action.name == "acheter_objet":
            self.inventory.buy(agent, action.target)
        elif action.name == "revendre":
            self.inventory.sell(agent, action.target)
        elif action.name == "carriere":
            self.careers.decide(agent, action.target)
        elif action.name == "devoirs":
            self.careers.homework(agent)
        elif action.name == "lire":
            self.careers.homework(agent, 0.4)
        elif action.name == "promener":
            self.inventory.walked(agent)
        elif action.name == "soigner":
            baby = self.agent_by_id(action.target or "")
            if baby is not None and not baby.dead:
                baby.needs.apply({"hunger": 45, "hygiene": 40, "social": 35, "fun": 30})
                self.remember(agent, f"J'ai pris soin de {baby.name} : biberon, couche, câlins.", 2)
        elif action.name == "tondre":
            self.economy.household.lawn = 0.0
            self.remember(agent, "J'ai tondu la pelouse. Ça sent l'été.", 2)

    def _buy(self, agent: Agent, item_id: str) -> None:
        item = self.economy.buy(self.clock.total_minutes, item_id, agent.name)
        if item is None:
            self.remember(agent, "Finalement, on n'avait pas les moyens de l'acheter.", 4)
            return
        if item_id in self.house.purchase_objects:
            self.house.add_object(self.house.purchase_objects[item_id])
        text = f"{agent.name} a acheté {item.label} ({item.price:,.0f} $) !".replace(",", " ")
        self.publish("achat", agent=agent.id, name=agent.name, item=item_id, amount=-item.price, text=text,
                     money=self.economy.household.money)
        for other in self.agents:
            if not other.dead:
                self.remember(other, text, 6)

    def _daily_yard(self) -> None:
        """Chaque matin, le gazon pousse ; trop long, le voisin tond (payant) ou la ville donne une amende."""
        household = self.economy.household
        household.last_lawn_day = self.clock.day
        household.lawn = min(100.0, household.lawn + LAWN_GROWTH_PER_DAY)
        now = self.clock.total_minutes
        if household.lawn >= LAWN_NEIGHBOR_AT and not self.economy.owns("tondeuse") \
                and household.money >= NEIGHBOR_MOW_PRICE:
            self.economy.transaction(now, "Le jeune d'à côté a tondu la pelouse", -NEIGHBOR_MOW_PRICE)
            household.lawn = 0.0
            self._news("Le jeune d'à côté a tondu la pelouse : 40 $.", good=False)
        elif household.lawn >= 100 and self.clock.day - household.last_fine_day >= 7:
            self.economy.transaction(now, "Amende de la ville : pelouse trop haute", -LAWN_FINE)
            household.last_fine_day = self.clock.day
            self._news("Amende de la ville : la pelouse est trop haute (150 $). Les voisins chialent.", good=False)

    def _news(self, text: str, good: bool, id_: str = "cour") -> None:
        """Nouvelle pour toute la famille ; hors pelouse (« cour »), chacun revoit son plan."""
        self.last_event = (text, good, self.clock.total_minutes)
        self.publish("evenement", id=id_, text=text, good=good, money=self.economy.household.money)
        prefix = "Bonne nouvelle : " if good else "Mauvaise nouvelle : "
        for agent in self.agents:
            if not agent.dead:
                self.remember(agent, prefix + text, 5 if good else 6)
        if id_ != "cour":
            self.mind.mark_stale(prefix + text)

    # ------------------------------------------------------------------ santé et mort

    def _update_health(self, agent: Agent, minutes: int) -> bool:
        """Faim ou épuisement à 0 : la santé baisse ; sinon elle remonte. True si la santé a lâché."""
        cfg = self.config.health
        if agent.away_kind == "hopital":
            return False
        damage = 0.0
        if agent.needs.hunger <= 0:
            damage += cfg.starvation_per_hour
        if agent.needs.energy <= 0:
            damage += cfg.exhaustion_per_hour
        if damage:
            agent.health = max(0.0, agent.health - damage * minutes / 60)
        elif agent.needs.hunger > 30 and agent.needs.energy > 20:
            agent.health = min(100.0, agent.health + cfg.regen_per_hour * minutes / 60)
        if agent.health > 0:
            return False
        if cfg.mortality:
            self._die(agent)
        else:
            self._hospitalize(agent)
        return True

    def _die(self, agent: Agent) -> None:
        now = self.clock.total_minutes
        cause = "de faim" if agent.needs.hunger <= 0 else "d'épuisement"
        self._cancel_decision(agent)
        agent.dead, agent.died_minute = True, now
        agent.action, agent.path = None, []
        agent.away_until = agent.away_label = agent.away_kind = None
        agent.grieving_until = None
        self.publish("deces", agent=agent.id, name=agent.name, cause=cause, day=self.clock.day + 1)
        grief_end = now + self.config.health.grief_days * 24 * 60
        for other in self.agents:
            if other.dead:
                continue
            other.grieving_until = grief_end
            other.needs.apply({"fun": -40, "social": -30})
            self.remember(other, f"{agent.name} nous a quittés ({cause}). Tout le monde a le cœur gros.", 10)
        self.mind.mark_stale(f"{agent.name} est mort {cause}.")
        if self.alive_count() == 0:
            self.game_over = True
            self.publish("fin", day=self.clock.day + 1, label=self.clock.label())

    def _hospitalize(self, agent: Agent) -> None:
        """Mode sans mortalité : quelques jours à l'hôpital (gratuit, merci la RAMQ), puis retour."""
        self._cancel_decision(agent)
        agent.action, agent.path = None, []
        agent.away_until = self.clock.total_minutes + self.config.health.hospital_days * 24 * 60
        agent.away_label, agent.away_kind, agent.away_pay = "hôpital", "hopital", 0.0
        agent.health = 50.0
        agent.needs.hunger = max(agent.needs.hunger, 70.0)
        agent.needs.energy = max(agent.needs.energy, 70.0)
        self.publish("hopital", agent=agent.id, name=agent.name)
        self.remember(agent, "J'ai perdu connaissance : direction l'hôpital.", 8)
        for other in self.agents:
            if other is not agent and not other.dead:
                self.remember(other, f"{agent.name} est à l'hôpital pour quelques jours.", 8)
        self.mind.mark_stale(f"{agent.name} est à l'hôpital.")

    def _burn_wood(self, agent: Agent, action: ActiveAction) -> bool:
        """Feu de camp : une veillée ou un souper sur le feu brûle une bûche. False si la veillée tombe à l'eau."""
        spot = self.house.object_at_spot(agent.pos)
        fire = action.name == "veiller" or (action.name == "cuisiner" and spot is not None and spot.id == "feu")
        if not fire or not self.economy.enabled:
            return True
        household = self.economy.household
        if household.wood >= 1:
            household.wood -= 1
            return True
        if action.name == "veiller":
            return False
        agent.needs.apply({"fun": -5})
        self.remember(agent, "Plus de bois sec : souper froid sur le réchaud.", 3)
        return True

    def fell_tree(self, tree_id: str) -> int:
        """L'arbre tombe (hache, scie ou grand vent) : des bûches pour la réserve, la lisière recule."""
        tree = self.house.remove_object(tree_id)
        if tree is None:
            return 0  # quelqu'un l'a abattu avant
        logs = WOOD_YIELD.get(tree.label, 5) + self.garage.wood_bonus()  # camionnette, VTT
        self.economy.household.wood += logs
        x, y = tree.rect[:2]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            neighbor = self.house.objects.get(f"arbre_{nx}_{ny}")
            if neighbor is not None:
                spots = [p for p in ((nx, ny + 1), (nx - 1, ny), (nx + 1, ny), (nx, ny - 1))
                         if self.house.is_walkable(p)]
                self.house.set_use_positions(neighbor, spots)
        return logs

    def _fell_tree(self, agent: Agent, tree_id: str) -> None:
        tree = self.house.objects.get(tree_id)
        logs = self.fell_tree(tree_id)
        if not logs or tree is None:
            return
        self.publish("coupe", agent=agent.id, name=agent.name, species=tree.label, logs=logs,
                     wood=self.economy.household.wood, trees=len(self.house.objects_of_kind("arbre")))
        self.remember(agent, f"J'ai abattu un {tree.label.lower()} : {logs} bûches de plus "
                             f"(réserve : {self.economy.household.wood}).", 2)

    # ------------------------------------------------------------------ calendrier : congés et maladie

    def is_sick(self, agent: Agent) -> bool:
        return agent.sick_until is not None and self.clock.total_minutes < agent.sick_until

    def calendar_lines(self, agents: list[Agent]) -> list[str]:
        """Pour les prompts : la date, le férié du jour, qui est en congé, les fériés qui s'en viennent."""
        day = self.clock.day
        holiday = self.calendar.holiday(day)
        lines = [f"Aujourd'hui : {self.calendar.label(day)}" + (f", {holiday} (congé)." if holiday else ".")]
        off = [f"{a.name} ({reason})" for a in agents if not a.dead
               and a.persona.schedule.away is not None and day % 7 in a.persona.schedule.away.days
               and (reason := self.calendar.agent_off(a, day))]
        if off:
            lines.append("En congé aujourd'hui : " + ", ".join(off) + ".")
        coming = [f"{name} ({self.calendar.label(d)})" for d, name in self.calendar.upcoming(day)]
        if coming:
            lines.append("Bientôt : " + ", ".join(coming) + ".")
        return lines

    def _daily_calendar(self) -> None:
        """Chaque matin : qui tombe malade ou guérit, la paie des congés payés, l'annonce des fériés."""
        day = self.clock.day
        now = self.clock.total_minutes
        cfg = self.config.health
        holiday = self.calendar.holiday(day)
        for agent in self.agents:
            if agent.dead or agent.is_away:
                continue
            if agent.sick_until is not None and now >= agent.sick_until:
                agent.sick_until = None
                self.remember(agent, "Ça va mieux : la grippe est passée.", 3)
            elif agent.sick_until is None and agent.persona.stage != "bebe" and                     (luck := random.Random(f"grippe:{agent.id}:{day}")).random() < cfg.sick_chance:
                # Tirage propre à la personne et au jour : la maladie ne décale pas le hasard du reste du jeu
                days = luck.choice((1, 1, 2, 3))
                agent.sick_until = (day + days) * 24 * 60 + 5 * 60
                agent.needs.apply({"energy": -20, "fun": -15})
                self.publish("malade", agent=agent.id, name=agent.name, days=days,
                             text=f"{agent.name} a la grippe : {days} jour(s) à la maison")
                self.remember(agent, f"Je file mal : la grippe. Je reste à la maison ({days} jour(s)).", 5)
            if holiday and agent.persona.stage != "bebe":
                self.remember(agent, f"C'est le {holiday} aujourd'hui : congé !", 3)
            self._pay_day_off(agent, day)
        if holiday:
            self.publish("conge", name=holiday, text=f"{holiday} : congé pour tout le monde")
        self.careers.daily(day)

    def _pay_day_off(self, agent: Agent, day: int) -> None:
        """Férié et vacances sont payés ; la maladie l'est quelques jours par année, ensuite non."""
        away = agent.persona.schedule.away
        salary = agent.persona.salary_per_day
        if not self.economy.enabled or salary <= 0 or away is None or day % 7 not in away.days:
            return
        now = self.clock.total_minutes
        if (agent.unemployed_until is not None and now < agent.unemployed_until) or \
                (agent.parental_leave_until is not None and now < agent.parental_leave_until):
            return
        reason = self.calendar.agent_off(agent, day)
        if reason is None:
            return
        if reason == "malade":
            year = str(self.calendar.date(day).year)
            used = agent.sick_paid.get(year, 0)
            if used >= self.config.health.sick_paid_days:
                self.remember(agent, "Encore malade : cette journée-là n'est pas payée.", 4)
                return
            agent.sick_paid[year] = used + 1
            reason = "congé de maladie"
        self.economy.transaction(now, f"Paie de {agent.name} ({reason})", salary)
        self.publish("paie", agent=agent.id, name=agent.name, amount=salary, source="conge",
                     money=self.economy.household.money)

    def has_roof(self) -> bool:
        """Au moins une pièce intérieure (le terrain du départ n'en a aucune)."""
        return any(name not in self.house.outdoor_rooms for name in self.house.rooms)

    def _eat(self, agent: Agent, action_name: str) -> bool:
        """Prend la nourriture du garde-manger au début d'un repas ; False si le frigo est vide."""
        portions = self.economy.portions_for(action_name)
        if self.economy.consume(portions):
            self._meal_pleasure(agent, action_name)
            return True
        self.publish("frigo_vide", agent=agent.id, name=agent.name, action=action_name)
        self.remember(agent, "Le frigo est vide, rien à manger.", 6)
        return False

    def _meal_pleasure(self, agent: Agent, action_name: str) -> None:
        """Un bon repas remonte le moral (surtout un plat préféré), un repas plate le baisse."""
        eaten = [FOODS[f] for f in getattr(self.economy, "last_eaten", []) if f in FOODS]
        if not eaten or action_name not in ACTIONS or not ACTIONS[action_name].effects.get("hunger"):
            return
        pleasure = sum(f.plaisir for f in eaten) / len(eaten)
        favorite = next((f for f in eaten if f.id in agent.persona.aime), None)
        if favorite is not None:
            pleasure += 5
            if action_name == "souper":
                self.remember(agent, f"Du {favorite.label} pour souper : mon préféré !", 2)
        agent.needs.apply({"fun": pleasure})

    def _leave(self, agent: Agent, action: ActiveAction) -> None:
        now = self.clock.total_minutes
        cfg = self.economy.config
        vehicle = self.garage.get(action.vehicle)
        agent.drove = (vehicle is not None and agent.pos in vehicle.uses
                       and vehicle.object_id not in self.garage.in_use())
        model = self.garage.model(vehicle) if agent.drove else None
        if model is not None:
            agent.vehicle = vehicle.object_id
            if model.plaisir:
                agent.needs.apply({"fun": model.plaisir})
        if action.name == "epicerie":
            minutes = model.epicerie_minutes if model is not None and model.epicerie else cfg.grocery_minutes
            agent.away_until, agent.away_label, agent.away_kind = now + minutes, "épicerie", "epicerie"
            agent.away_pay = 0.0
        elif action.name == "heures_sup":
            agent.away_until = now + cfg.overtime_minutes
            agent.away_label, agent.away_kind = "travail (heures sup)", "heures_sup"
            agent.away_pay = self._overtime_pay(agent)
        else:
            salary = agent.persona.salary_per_day
            agent.away_until = action.until_minute
            if model is not None and agent.away_until is not None:
                agent.away_until -= model.trajet  # pas d'autobus à attendre au retour
            agent.away_label = action.target or "travail"
            agent.away_kind = "travail" if salary > 0 else "ecole"
            agent.away_pay = salary
            if agent.away_label == "garderie" and self.economy.enabled:
                self.economy.transaction(now, f"Garderie ({agent.name})", -self.config.life.daycare_fee)
            # Le lunch vient du garde-manger ; sans lunch, on rentre affamé
            if self.economy.enabled and not self.economy.consume(self.economy.config.meal_portions):
                agent.needs.apply({"hunger": -25})
                self.remember(agent, "Parti sans lunch : le frigo était vide.", 5)
        agent.action = None
        agent.path = []
        self.publish("depart", agent=agent.id, name=agent.name, label=agent.away_label)
        self.remember(agent, f"Je pars {away_phrase(agent.away_label)}.", 1)

    def _return_home(self, agent: Agent) -> None:
        vehicle = self.garage.get(agent.vehicle) if agent.drove else None
        by_car = vehicle is not None and self.garage.model(vehicle).epicerie
        agent.pos = vehicle.uses[0] if vehicle is not None else self.house.objects["porte"].use_positions[0]
        agent.last_room = self.house.room_at(agent.pos)
        label, kind, pay = agent.away_label, agent.away_kind, agent.away_pay
        agent.away_until = None
        agent.away_label = None
        agent.away_kind = None
        agent.away_pay = 0.0
        agent.drove, agent.vehicle = False, None
        self.publish("retour", agent=agent.id, name=agent.name, label=label)
        place = label or "travail"
        origin = f"de l'{place}" if away_phrase(place).startswith("à l'") else f"du {place}"
        self.remember(agent, f"De retour {origin}.", 1)
        if not self.economy.enabled:
            return
        now = self.clock.total_minutes
        if pay > 0:
            what = "Heures sup" if kind == "heures_sup" else "Paie"
            self.economy.transaction(now, f"{what} de {agent.name}", pay)
            self.publish("paie", agent=agent.id, name=agent.name, amount=pay, source=kind,
                         money=self.economy.household.money)
        if kind == "epicerie":
            bought, cost = self.economy.buy_groceries(now, self.alive_count(), agent.name, by_car=by_car)
            self.publish("epicerie", agent=agent.id, name=agent.name, portions=bought, amount=-cost,
                         money=self.economy.household.money)
            if bought:
                self.remember(agent, f"Épicerie faite : {bought} portions pour {cost:.0f} $.", 2)
            else:
                self.remember(agent, "Pas assez d'argent pour faire l'épicerie...", 7)

    # ------------------------------------------------------------------ sauvegarde

    def save_state(self, path: str | Path) -> None:
        """Écrit l'état complet (horloge, agents, cooldowns, compteurs LLM) en JSON."""
        data: dict = {
            "version": SAVE_VERSION,
            "total_minutes": self.clock.total_minutes,
            "agents": {a.id: a.model_dump(mode="json") for a in self.agents},
            "pair_last_talk": self.pair_last_talk,
            "household": self.economy.household.model_dump(mode="json"),
            "social": self.social.to_dict(),
            "world": {"scenario": self.house.layout.name, "removed": sorted(self.house.removed)},
            "construction": self.architect.to_dict(),
            "family": self.family.to_dict(),
            "history": self.history.to_list(),
        }
        if self.llm is not None:
            stats = self.llm.stats
            data["llm_stats"] = {"calls": stats.calls, "input_tokens": stats.input_tokens,
                                 "output_tokens": stats.output_tokens}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def load_state(self, path: str | Path) -> None:
        """Restaure une sauvegarde ; les agents absents du fichier gardent leur état initial."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") not in SUPPORTED_SAVE_VERSIONS:
            raise ValueError(f"Version de sauvegarde non prise en charge : {data.get('version')}")
        world = data.get("world", {"scenario": "maison", "removed": []})
        if world["scenario"] != self.house.layout.name:
            raise ValueError(f"sauvegarde du scénario « {world['scenario']} », "
                             f"pas « {self.house.layout.name} »")
        self.clock.total_minutes = data["total_minutes"]
        for obj_id in world.get("removed", []):
            self.house.remove_object(obj_id)
        if "household" in data:  # avant les pièces : leurs meubles évitent les objets achetés
            self.economy.household = Household.model_validate(data["household"])
        self.architect.load_dict(data.get("construction"))
        self.pair_last_talk = dict(data.get("pair_last_talk", {}))
        for item_id in self.economy.household.purchases:
            if item_id in self.house.purchase_objects:
                self.house.add_object(self.house.purchase_objects[item_id])
        self.history.load_list(data.get("history"))
        self.family.load_dict(data.get("family"))  # recrée d'abord les enfants nés dans la partie
        saved = data.get("agents", {})
        for index, agent in enumerate(self.agents):
            if agent.id in saved:
                # Remplacement en place : le moteur, le rendu et les bulles partagent cette liste
                self.agents[index] = Agent.model_validate({**saved[agent.id], "persona": agent.persona})
        self.family.after_load()
        self.careers.setup()   # carrières sauvegardées : salaire et horaire de la fiche ; sinon, celles de départ
        self.inventory.restore()
        self.inventory.rehouse()
        self.garage.restore()
        self.pending_decisions.clear()
        self.pending_dialogues.clear()
        self.pending_summaries.clear()
        self.mind.clear()
        self.pending_stories.clear()
        self.social.clear()
        self.social.load_dict(data.get("social", {}))
        self.game_over = self.alive_count() == 0
        if self.llm is not None and "llm_stats" in data:
            for key, value in data["llm_stats"].items():
                setattr(self.llm.stats, key, value)
