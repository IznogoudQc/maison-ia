"""Événements aléatoires quotidiens : coups durs et bonnes nouvelles, selon le scénario et la situation.

Chaque événement dit dans quels scénarios il peut arriver (maison, terrain) et à quelle condition
(un chantier en cours, un bébé, une grosse réserve de bois...). Le tirage ne considère que ceux qui
collent à la situation ; l'effet chiffré est appliqué par le moteur, le texte peut ensuite être
raconté par le LLM (voir Engine._roll_events).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sim.clock import MINUTES_PER_DAY, SimClock, parse_hhmm
from sim.config import EventsConfig

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.economy import Household
    from sim.engine import Engine
    from world.building import PlannedRoom

MAX_EVENTS_PER_DAY = 2
BOTH = ("maison", "terrain")
TERRAIN = ("terrain",)


@dataclass(frozen=True)
class RandomEvent:
    id: str
    probability: float                                   # chance par jour
    good: bool
    apply: Callable[[Engine, random.Random], str | None]  # texte de l'événement, ou None s'il ne s'applique pas
    scenarios: tuple[str, ...] = BOTH
    condition: Callable[[Engine], bool] | None = None     # situation requise pour être tiré


# ---------------------------------------------------------------- faits sur la situation


def _laid_off(agent: Agent, now: int) -> bool:
    return agent.unemployed_until is not None and now < agent.unemployed_until


def _employed(engine: Engine) -> list[Agent]:
    now = engine.clock.total_minutes
    return [a for a in engine.agents if not a.dead and a.persona.salary_per_day > 0 and not _laid_off(a, now)
            and (a.parental_leave_until is None or now >= a.parental_leave_until)]


def _site(engine: Engine) -> PlannedRoom | None:
    """Pièce en chantier (bâtie par la famille, pas par un entrepreneur)."""
    room = engine.architect.site_room()
    return room if room is not None and room.status == "chantier" and not room.contractor else None


def _has_kitchen(engine: Engine) -> bool:
    plan = engine.architect.plan
    return plan is not None and any(r.type == "cuisine" and r.status == "bati" for r in plan.rooms)


def _babies_home(engine: Engine) -> list[Agent]:
    return [a for a in engine.agents if not a.dead and not a.is_away and a.persona.stage == "bebe"]


def _newborn(engine: Engine) -> Agent | None:
    """Enfant né il y a quelques jours, pas encore fêté par la parenté."""
    gifted = engine.economy.household.gifted
    return next((a for a in engine.family.children() if (a.age_years or 0) < 0.4 and a.id not in gifted), None)


# ---------------------------------------------------------------- événements des deux scénarios


def _layoff(engine: Engine, rng: random.Random) -> str | None:
    workers = _employed(engine)
    if not workers:
        return None
    agent = rng.choice(workers)
    days = rng.randint(5, 10)
    agent.unemployed_until = engine.clock.total_minutes + days * MINUTES_PER_DAY
    return f"Mise à pied pour {agent.name} : {days} jours sans salaire."


SURPRISE_BILLS = {  # (libellé, montant) selon le scénario
    "maison": [("Le dentiste de Félix", 250), ("Le plombier pour le chauffe-eau", 450),
               ("Des bottes d'hiver pour les enfants", 180), ("Une amende de stationnement", 75),
               ("Le vétérinaire pour le chat du voisin qu'on garde", 120)],
    "terrain": [("Le dentiste", 220), ("Un cellulaire échappé dans le lac", 300),
                ("La réparation du réchaud de camping", 90), ("Des bottes de travail neuves", 160),
                ("Une lame de rechange pour la scie", 70)],
}


def _surprise_bill(engine: Engine, rng: random.Random) -> str | None:
    choices = list(SURPRISE_BILLS.get(engine.house.layout.name, SURPRISE_BILLS["maison"]))
    if "auto" in engine.economy.household.purchases:
        choices.append(("La réparation de l'auto", 800))
    label, amount = rng.choice(choices)
    engine.economy.transaction(engine.clock.total_minutes, label, -amount)
    return f"Facture imprévue : {label[0].lower() + label[1:]} ({amount} $)."


def _price_hike(engine: Engine, rng: random.Random) -> str | None:
    household = engine.economy.household
    household.price_factor = round(household.price_factor * 1.08, 4)
    price = f"{engine.economy.portion_price():.2f}".replace(".", ",")
    return f"Le prix de l'épicerie a augmenté de 8 % (portion à {price} $)."


def _bonus(engine: Engine, rng: random.Random) -> str | None:
    workers = _employed(engine)
    if not workers:
        return None
    agent = rng.choice(workers)
    amount = rng.choice((250, 400, 500))
    engine.economy.transaction(engine.clock.total_minutes, f"Prime de {agent.name}", amount)
    return f"Prime au travail pour {agent.name} : +{amount} $."


def _tax_refund(engine: Engine, rng: random.Random) -> str | None:
    engine.economy.transaction(engine.clock.total_minutes, "Remboursement d'impôt", 600)
    return "Remboursement d'impôt : +600 $."


def _babysitting(engine: Engine, rng: random.Random) -> str | None:
    if engine.clock.weekday < 5:
        return None
    sitter = next((a for a in engine.agents if not a.dead and 13 <= a.persona.age < 18), None)
    if sitter is None:
        return None
    engine.economy.transaction(engine.clock.total_minutes, f"Gardiennage de {sitter.name}", 40)
    return f"{sitter.name} a gardé les enfants des voisins : +40 $ pour la famille."


def _grandma(engine: Engine, rng: random.Random) -> str | None:
    engine.economy.transaction(engine.clock.total_minutes, "Chèque de grand-maman", 100)
    babies = _babies_home(engine)
    if babies:
        return f"Grand-maman est venue voir {babies[0].name} : des tricots et un chèque de 100 $."
    return "Grand-maman a envoyé un chèque de 100 $."


def _sunny_day(engine: Engine, rng: random.Random) -> str | None:
    for agent in engine.agents:
        if not agent.dead:
            agent.needs.apply({"fun": 15})
    return "Une magnifique journée d'été : tout le monde est de bonne humeur."


# ---------------------------------------------------------------- événements du terrain


def _storm(engine: Engine, rng: random.Random) -> str | None:
    site = _site(engine)
    if not engine.has_roof():
        for agent in engine.agents:
            if not agent.dead:
                agent.needs.apply({"energy": -15, "fun": -10})
        return "Gros orage cette nuit : la tente a pris l'eau, personne n'a bien dormi."
    if site is not None and site.progress > 0:
        lost = round(min(3.0, site.progress), 1)
        site.progress -= lost
        return f"Un orage a arraché la bâche du chantier de la {site.name.lower()} : {lost:g} heures de travail à refaire."
    return None


def _fallen_tree(engine: Engine, rng: random.Random) -> str | None:
    trees = [t for t in engine.house.objects_of_kind("arbre") if t.use_positions]
    if not trees:
        return None
    tree = rng.choice(trees)
    logs = engine.fell_tree(tree.id)
    return f"Le vent a jeté un {tree.label.lower()} par terre : {logs} bûches gratuites."


def _site_theft(engine: Engine, rng: random.Random) -> str | None:
    site = _site(engine)
    if site is None or not site.materials_paid:
        return None
    loss = round(site.materials_cost * 0.15, -1)
    engine.economy.transaction(engine.clock.total_minutes, f"Matériaux volés : {site.name.lower()}", -loss)
    return f"Des voleurs sont passés sur le chantier de la {site.name.lower()} : {loss:.0f} $ de matériaux à racheter."


def _work_bee(engine: Engine, rng: random.Random) -> str | None:
    site = _site(engine)
    if site is None:
        return None
    hours = min(4.0, max(0.0, site.work_needed - site.progress - 0.5))
    if hours <= 0:
        return None
    site.progress += hours
    return f"Corvée entre voisins : {hours:g} heures de travail gratuites sur la {site.name.lower()}."


def _raccoons(engine: Engine, rng: random.Random) -> str | None:
    household = engine.economy.household
    lost = min(household.pantry, 6.0)
    if lost < 1:
        return None
    household.pantry -= lost
    return f"Des ratons laveurs ont ouvert la glacière : {lost:.0f} portions perdues."


def _inspector(engine: Engine, rng: random.Random) -> str | None:
    household = engine.economy.household
    if household.building_permit:
        return None
    household.building_permit = True
    engine.economy.transaction(engine.clock.total_minutes, "Permis de construire", -250)
    return "L'inspecteur municipal est passé : permis de construire obligatoire (250 $)."


def _sell_wood(engine: Engine, rng: random.Random) -> str | None:
    household = engine.economy.household
    if household.wood < 50:
        return None
    household.wood -= 15
    engine.economy.transaction(engine.clock.total_minutes, "Vente de bois de chauffage", 105)
    return "Le voisin achète 15 bûches pour son poêle : +105 $."


def _sick_baby(engine: Engine, rng: random.Random) -> str | None:
    babies = _babies_home(engine)
    parents = [a for a in _employed(engine) if a.persona.is_adult]
    if not babies or not parents or engine.clock.weekday >= 5:
        return None
    baby, parent = rng.choice(babies), rng.choice(parents)
    parent.unemployed_until = engine.clock.total_minutes + MINUTES_PER_DAY  # une journée sans salaire
    baby.needs.apply({"fun": -20})
    return f"{baby.name} fait de la fièvre : clinique, et {parent.name} reste à la maison une journée sans salaire."


def _birth_gift(engine: Engine, rng: random.Random) -> str | None:
    child = _newborn(engine)
    if child is None:
        return None
    engine.economy.household.gifted.append(child.id)
    amount = rng.choice((150, 200, 300))
    engine.economy.transaction(engine.clock.total_minutes, f"Cadeau de naissance pour {child.name}", amount)
    return f"La parenté envoie un cadeau de naissance pour {child.name} : {amount} $ et des pyjamas."


EVENTS: list[RandomEvent] = [
    RandomEvent("mise_a_pied", 0.015, False, _layoff),
    RandomEvent("facture_imprevue", 0.06, False, _surprise_bill),
    RandomEvent("hausse_epicerie", 0.03, False, _price_hike),
    RandomEvent("prime", 0.03, True, _bonus),
    RandomEvent("impot", 0.01, True, _tax_refund),
    RandomEvent("gardiennage", 0.25, True, _babysitting,
                condition=lambda e: any(13 <= a.persona.age < 18 and not a.dead for a in e.agents)),
    RandomEvent("grand_maman", 0.01, True, _grandma),
    RandomEvent("belle_journee", 0.05, True, _sunny_day),
    # Terrain
    RandomEvent("orage", 0.06, False, _storm, TERRAIN,
                lambda e: not e.has_roof() or _site(e) is not None),
    RandomEvent("arbre_tombe", 0.04, True, _fallen_tree, TERRAIN),
    RandomEvent("vol_chantier", 0.02, False, _site_theft, TERRAIN, lambda e: _site(e) is not None),
    RandomEvent("corvee", 0.03, True, _work_bee, TERRAIN, lambda e: _site(e) is not None),
    RandomEvent("ratons", 0.05, False, _raccoons, TERRAIN, lambda e: not _has_kitchen(e)),
    RandomEvent("inspecteur", 0.03, False, _inspector, TERRAIN,
                lambda e: _site(e) is not None and not e.economy.household.building_permit),
    RandomEvent("vente_bois", 0.04, True, _sell_wood, TERRAIN, lambda e: e.economy.household.wood >= 50),
    RandomEvent("bebe_malade", 0.04, False, _sick_baby, TERRAIN, lambda e: bool(_babies_home(e))),
    RandomEvent("cadeau_naissance", 0.4, True, _birth_gift, TERRAIN, lambda e: _newborn(e) is not None),
]


class RandomEvents:
    def __init__(self, config: EventsConfig) -> None:
        self.config = config

    def due(self, clock: SimClock, household: Household) -> bool:
        return (self.config.enabled and clock.minute_of_day >= parse_hhmm(self.config.check_time)
                and household.last_events_day != clock.day)

    @staticmethod
    def possible(engine: Engine) -> list[RandomEvent]:
        """Événements qui peuvent arriver aujourd'hui : bon scénario, condition remplie."""
        scenario = engine.house.layout.name
        return [e for e in EVENTS if scenario in e.scenarios and (e.condition is None or e.condition(engine))]

    def roll(self, engine: Engine, rng: random.Random) -> list[tuple[RandomEvent, str]]:
        """Tire les événements du jour (au plus MAX_EVENTS_PER_DAY) et applique leurs effets."""
        engine.economy.household.last_events_day = engine.clock.day
        happened: list[tuple[RandomEvent, str]] = []
        candidates = self.possible(engine)
        for event in rng.sample(candidates, len(candidates)):
            if rng.random() >= event.probability * self.config.frequency:
                continue
            text = event.apply(engine, rng)
            if text:
                happened.append((event, text))
            if len(happened) >= MAX_EVENTS_PER_DAY:
                break
        return happened
