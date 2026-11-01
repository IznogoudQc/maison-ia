"""Écran Maison (touche I) : objets, véhicules, garde-manger, prêts et dépenses de la semaine.

Tab ou flèches gauche/droite : onglet ; molette, Page préc./suiv. : défiler ; I ou Échap : fermer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from sim.economy import PORTIONS_PER_PERSON_DAY
from sim.food import FOODS
from sim.inventory import RESALE
from ui import theme
from ui.dialogue_box import wrap_text

if TYPE_CHECKING:
    from sim.engine import Engine

TABS = ["Objets", "Véhicules", "Garde-manger", "Prêts", "Dépenses"]
HEADER = (235, 200, 120)   # ligne de titre d'une section
GOOD, BAD = (140, 210, 120), (235, 120, 110)
Row = tuple[str, tuple[int, int, int] | None]   # texte, couleur (None = normal)


def _money(value: float) -> str:
    return f"{value:,.0f} $".replace(",", " ")


def object_rows(engine: Engine) -> list[Row]:
    items = engine.economy.household.items
    if not items:
        return [("Rien d'acheté pour l'instant.", theme.TEXT_DIM)]
    rows: list[Row] = [(f"{len(items)} objet(s), payés {_money(sum(o.price for o in items))}, "
                        f"revente {_money(sum(o.price for o in items) * RESALE)}", HEADER)]
    for owned in items:
        item = engine.inventory.catalogue.get(owned.item_id)
        where = "dehors" if owned.room == "exterieur" else owned.room
        rows.append((f"{owned.label.capitalize()} ({where}) : {_money(owned.price)}", None))
        effects = [item.utilite] if item and item.utilite else []
        if owned.weekly:
            effects.append(f"{owned.weekly:+.0f} $/semaine")
        if owned.hydro:
            effects.append(f"Hydro −{owned.hydro:.0f} $/semaine")
        if owned.food:
            food = FOODS.get(owned.harvest or ("oeufs" if owned.kind == "poulailler" else "legumes"))
            effects.append(f"{owned.food:g} portion(s) de {food.label if food else 'nourriture'} par jour")
        if owned.discount:
            effects.append(f"épicerie −{owned.discount * 100:.0f} %")
        if effects:
            rows.append(("    " + " · ".join(effects), theme.TEXT_DIM))
    if engine.inventory.has_dog():
        walked = engine.inventory.dog_walked_today()
        rows.append(("Le chien a eu sa marche aujourd'hui." if walked else "Le chien attend sa marche !",
                     GOOD if walked else BAD))
    return rows


def vehicle_rows(engine: Engine) -> list[Row]:
    garage = engine.garage
    if not garage.owned:
        return [("Pas de véhicule : tout le monde prend l'autobus.", theme.TEXT_DIM)]
    busy = garage.in_use()
    rows: list[Row] = []
    for vehicle in garage.owned:
        model = garage.model(vehicle)
        state = "parti" if vehicle.object_id in busy else "à la maison"
        rows.append((f"{vehicle.label.capitalize()} : {_money(vehicle.price)}, {vehicle.weekly:.0f} $/semaine "
                     f"({state})", None))
        details = [model.utilite] if model.utilite else []
        details.append(f"{model.places} place(s)")
        if model.trajet:
            details.append(f"{model.trajet} min de moins au retour du travail")
        rows.append(("    " + " · ".join(details), theme.TEXT_DIM))
    return rows


def pantry_rows(engine: Engine) -> list[Row]:
    eco = engine.economy
    household = eco.household
    day = engine.clock.day
    alive = engine.alive_count()
    daily = alive * PORTIONS_PER_PERSON_DAY
    days = household.pantry / daily if daily else 0
    rows: list[Row] = [(f"{household.pantry:.0f} portions, environ {days:.0f} jour(s) pour {alive} personne(s)",
                        HEADER if days >= 2 else BAD)]
    style = {"economique": "économique", "equilibre": "équilibré", "gaterie": "gâteries"}[eco.grocery_style()]
    freezer = ", congélateur : on garde trois fois plus longtemps" if eco.has_freezer() else ""
    rows.append((f"Prochain panier : {style}{freezer}", theme.TEXT_DIM))
    grouped: dict[str, list[float]] = {}
    for stock in household.foods:
        portions, first = grouped.get(stock.food, [0.0, stock.expires_day])
        grouped[stock.food] = [portions + stock.portions, min(first, stock.expires_day)]
    for food_id, (portions, expires) in sorted(grouped.items(), key=lambda kv: kv[1][1]):
        food = FOODS.get(food_id)
        left = int(expires) - day
        when = ("périme aujourd'hui" if left <= 0 else "périme demain" if left == 1
                else f"périme dans {left} jours" if left < 30 else "se garde longtemps")
        fans = [a.name for a in engine.agents if not a.dead and food_id in a.persona.aime]
        liked = f" · préféré de {', '.join(fans)}" if fans else ""
        rows.append((f"{food.label if food else food_id} : {portions:.1f} portion(s), {when}{liked}",
                     BAD if left <= 1 else None))
    return rows


def loan_rows(engine: Engine) -> list[Row]:
    household = engine.economy.household
    rows: list[Row] = [(f"Dossier de crédit : {household.credit_score}", HEADER)]
    if not household.loans:
        rows.append(("Aucun prêt en cours.", theme.TEXT_DIM))
        return rows
    for loan in household.loans:
        rows.append((f"{loan.label.capitalize()} : solde {_money(loan.balance)} sur {_money(loan.principal)}", None))
        late = f" · {loan.missed} paiement(s) manqué(s)" if loan.missed else ""
        rows.append((f"    {loan.payment:.0f} $/semaine · {loan.weeks_left} semaines · taux {loan.rate * 100:.1f} %"
                     f"{late}", BAD if loan.missed else theme.TEXT_DIM))
    total = sum(l.balance for l in household.loans)
    rows.append((f"Dette totale : {_money(total)}", BAD))
    return rows


def expense_rows(engine: Engine) -> list[Row]:
    eco = engine.economy
    alive = engine.alive_count()
    bills = eco.weekly_bill_items()
    loans = sum(l.payment for l in eco.household.loans)
    food = alive * PORTIONS_PER_PERSON_DAY * 7 * eco.portion_price() * (1 - eco.grocery_discount())
    total = sum(bills.values()) + loans + food
    rows: list[Row] = [(f"Solde : {_money(eco.household.money)} · dépenses : {_money(total)} par semaine",
                        HEADER if eco.household.money >= 0 else BAD)]
    for label, amount in sorted(bills.items(), key=lambda kv: -kv[1]):
        rows.append((f"{label} : {amount:+.0f} $", GOOD if amount < 0 else None))
    if loans:
        rows.append((f"Paiements de prêts : {loans:+.0f} $", None))
    rows.append((f"Épicerie (environ) : {food:+.0f} $", None))
    rows.append((f"Coussin conseillé en banque : {_money(eco.reserve(alive))}", theme.TEXT_DIM))
    return rows


BUILDERS = [object_rows, vehicle_rows, pantry_rows, loan_rows, expense_rows]


class HouseholdScreen:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.open = False
        self.tab = 0
        self.scroll = 0   # lignes descendues depuis le haut

    def toggle(self) -> None:
        self.open = not self.open
        self.scroll = 0

    def rows(self) -> list[Row]:
        return BUILDERS[self.tab](self.engine)

    def handle_key(self, event: pygame.event.Event) -> bool:
        """Touche pour l'écran ouvert ; True si elle est consommée (le jeu ne la voit pas)."""
        if not self.open:
            return False
        key = event.key
        if key in (pygame.K_ESCAPE, pygame.K_i):
            self.toggle()
        elif key in (pygame.K_TAB, pygame.K_RIGHT):
            self.tab, self.scroll = (self.tab + 1) % len(TABS), 0
        elif key == pygame.K_LEFT:
            self.tab, self.scroll = (self.tab - 1) % len(TABS), 0
        elif key == pygame.K_PAGEDOWN:
            self.scroll += 15
        elif key == pygame.K_PAGEUP:
            self.scroll = max(0, self.scroll - 15)
        return True

    def wheel(self, dy: int) -> None:
        self.scroll = max(0, self.scroll - dy * 3)

    def draw(self, surface: pygame.Surface, area: pygame.Rect) -> None:
        if not self.open:
            return
        panel = area.inflate(-32, -32)
        veil = pygame.Surface(panel.size, pygame.SRCALPHA)
        veil.fill((22, 22, 28, 240))
        surface.blit(veil, panel.topleft)
        pygame.draw.rect(surface, theme.PANEL_BORDER, panel, 2, border_radius=6)
        x, y = panel.x + 16, panel.y + 12
        surface.blit(theme.font(18, bold=True).render("La maison", True, theme.TEXT), (x, y))
        tx = x + 150
        for index, label in enumerate(TABS):
            active = index == self.tab
            image = theme.font(14, bold=active).render(label, True, theme.ACCENT if active else theme.TEXT_DIM)
            surface.blit(image, (tx, y + 3))
            if active:
                pygame.draw.line(surface, theme.ACCENT, (tx, y + 22), (tx + image.get_width(), y + 22), 2)
            tx += image.get_width() + 18
        y += 40
        font = theme.font(13)
        width = panel.width - 40
        lines: list[tuple[str, tuple[int, int, int]]] = []
        for text, color in self.rows():
            indent = "    " if text.startswith("    ") else ""
            for i, line in enumerate(wrap_text(text.strip(), font, width - (24 if indent else 0))):
                lines.append(((indent or ("  " if i else "")) + line, color or theme.TEXT))
        visible = (panel.bottom - 40 - y) // 18
        self.scroll = min(self.scroll, max(0, len(lines) - visible))
        for text, color in lines[self.scroll:self.scroll + visible]:
            surface.blit(font.render(text, True, color), (x, y))
            y += 18
        help_text = "Tab : onglet   molette : défiler   I : fermer"
        surface.blit(theme.font(12).render(help_text, True, theme.TEXT_DIM), (x, panel.bottom - 26))
