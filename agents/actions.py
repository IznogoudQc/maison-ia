"""Catalogue des actions et score déterministe des options."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from agents.needs import Needs


@dataclass(frozen=True)
class ActionDef:
    name: str
    label: str                     # forme verbale affichée : « regarde la télé »
    object_kind: str | None        # type d'objet requis (None = sur place / cible agent)
    duration: int                  # minutes simulées une fois sur place
    effects: dict[str, float] = field(default_factory=dict)  # gain total sur la durée
    selectable: bool = True        # False = déclenchée seulement par l'horaire
    only_below: tuple[str, float] | None = None  # proposée seulement si ce besoin est sous le seuil
    allowed: tuple[str, ...] | None = None       # ids de persona autorisés (None = tous)
    excluded: tuple[str, ...] = ()               # ids de persona exclus
    daytime_only: bool = False                   # activité extérieure : seulement de jour


ACTIONS: dict[str, ActionDef] = {a.name: a for a in [
    ActionDef("collation", "prend une collation au frigo", "frigo", 8, {"hunger": 25},
              only_below=("hunger", 60)),
    ActionDef("douche", "prend sa douche", "douche", 15, {"hygiene": 70}, only_below=("hygiene", 50)),
    ActionDef("tele", "regarde la télé", "tele", 45, {"fun": 35, "energy": 3}),
    ActionDef("ordi", "joue à l'ordi", "ordi", 40, {"fun": 40}, excluded=("enfant",)),
    ActionDef("jouer", "joue aux Lego", "jouets", 35, {"fun": 45}, allowed=("enfant",)),
    ActionDef("lire", "lit un livre", "livres", 30, {"fun": 25, "energy": 2}),
    ActionDef("telephone", "scrolle sur son téléphone", None, 20, {"fun": 20, "social": 8},
              excluded=("enfant",)),
    ActionDef("sieste", "fait une sieste", "lit", 45, {"energy": 18}, only_below=("energy", 30)),
    ActionDef("jaser", "va jaser avec {target}", None, 15, {"social": 30, "fun": 5}),
    ActionDef("flaner", "flâne", None, 10, {"fun": 3}),
    # Cour arrière (les objets achetés n'existent qu'après l'achat)
    ActionDef("baignade", "se baigne dans la piscine", "piscine", 40, {"fun": 45, "social": 10, "hygiene": -5},
              daytime_only=True),
    ActionDef("jardin", "relaxe sur le patio", "patio", 30, {"fun": 20, "social": 10, "energy": 3},
              daytime_only=True),
    ActionDef("balancoire", "se balance", "balancoire", 25, {"fun": 40}, allowed=("enfant",),
              daytime_only=True),
    # Terrain : veillée autour du feu de camp (le soir, une bûche)
    ActionDef("veiller", "veille autour du feu", "feu", 40, {"fun": 25, "social": 12}),
    # Actions imposées par l'horaire
    ActionDef("dejeuner", "déjeune", "table", 20, {"hunger": 45, "social": 5}, selectable=False),
    ActionDef("souper", "soupe en famille", "table", 35, {"hunger": 65, "social": 15}, selectable=False),
    ActionDef("cuisiner", "prépare le souper", "cuisiniere", 40, {"fun": 5}, selectable=False),
    ActionDef("bbq", "fait un BBQ", "bbq", 40, {"fun": 15, "social": 5}, selectable=False),
    ActionDef("dormir", "dort", "lit", 480, {}, selectable=False),
    ActionDef("partir", "part {target}", "porte", 0, {}, selectable=False),
    # Actions économiques : proposées par le moteur selon l'état du ménage (pas par les besoins)
    ActionDef("epicerie", "va faire l'épicerie", "porte", 0, {}, selectable=False),
    ActionDef("heures_sup", "part faire des heures supplémentaires", "porte", 0, {}, selectable=False),
    ActionDef("acheter", "commande {target}", None, 10, {"fun": 10}, selectable=False),
    ActionDef("tondre", "tond la pelouse", None, 60, {"fun": -5, "energy": -4}, selectable=False),
    ActionDef("couper", "coupe un {target}", "arbre", 60, {"energy": -12, "fun": -4, "hygiene": -8},
              selectable=False, daytime_only=True),
]}

DAYTIME_HOURS = (7 * 60, 21 * 60)  # activités extérieures

# Actions qui font sortir de la maison une fois la porte atteinte
AWAY_ACTIONS = {"partir", "epicerie", "heures_sup"}


def away_phrase(label: str) -> str:
    """« travail » -> « au travail », « école » -> « à l'école »."""
    return f"à l'{label}" if label[:1].lower() in "aeéèêiouyh" else f"au {label}"


def is_allowed(action: ActionDef, persona_id: str, needs: Needs) -> bool:
    if action.allowed is not None and persona_id not in action.allowed:
        return False
    if persona_id in action.excluded:
        return False
    if action.only_below is not None:
        need, threshold = action.only_below
        if getattr(needs, need) >= threshold:
            return False
    return True

FAVORITE_BONUS = 1.4
URGENT_THRESHOLD = 20.0


class Option(BaseModel):
    """Action candidate pour un agent inactif."""

    action: str
    target: str | None = None      # id d'agent pour « jaser »
    label: str
    score: float
    urgent: bool = False           # choisie d'office, sans demander au LLM (garde-manger vide...)


# Cible par défaut quand elle n'est pas encore connue (plan du jour : « coupe un arbre »)
DEFAULT_TARGETS = {"couper": "arbre"}


def action_label(name: str, target_name: str | None = None) -> str:
    label = ACTIONS[name].label
    if "{target}" not in label:
        return label
    return label.format(target=target_name or DEFAULT_TARGETS.get(name, "?"))


def score_action(action: ActionDef, needs: Needs, favorites: list[str]) -> float:
    """Utilité : gain utile pondéré par l'urgence de chaque besoin."""
    values = needs.as_dict()
    score = 0.0
    for name, gain in action.effects.items():
        missing = 100.0 - values[name]
        urgency = (missing / 100.0) ** 2 * 2.0 + 0.05
        score += min(gain, missing) * urgency
    if action.name in favorites:
        score *= FAVORITE_BONUS
    return round(score, 2)
