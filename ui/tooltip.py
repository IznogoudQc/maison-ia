"""Infobulle au survol de la souris : nom, utilité, état et qui s'en sert (objets, arbres, chantier, personnages)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ui import theme
from ui.dialogue_box import wrap_text

if TYPE_CHECKING:
    from sim.engine import Engine
    from ui.renderer import Renderer

# Utilité des types d'objets qui ne viennent pas du catalogue (maison des Gagnon, pièces bâties, campement)
KIND_INFO = {
    "lit": "dormir (et faire la sieste)", "tele": "s'asseoir et regarder la télé", "frigo": "prendre une collation",
    "cuisiniere": "cuisiner le souper", "table": "manger en famille", "douche": "se laver", "livres": "lire",
    "jouets": "jouer aux Lego (enfants)", "ordi": "jouer à l'ordi", "patio": "relaxer dehors",
    "balancoire": "se balancer (enfants)", "piscine": "se baigner", "bbq": "les soupers BBQ de fin de semaine",
    "porte": "prendre l'autobus (travail, école, épicerie)", "feu": "veiller autour du feu le soir",
    "berceau": "le bébé y dort et attend les soins", "vehicule": "partir plus vite au travail ou à l'épicerie",
    "deco": "décoration",
}
OBJECT_INFO = {"feu": "cuisiner sur le feu (une bûche)", "glaciere": "garder la nourriture au frais",
               "baril": "se laver à l'eau de pluie (moins efficace qu'une douche)", "tente": "dormir (on dort moins bien)",
               "becosse": "la bécosse du campement", "corde_bois": "réserve de bûches"}
MAX_WIDTH = 300


def describe(engine: Engine, renderer: Renderer, mouse: tuple[int, int]) -> list[str]:
    """Lignes à afficher pour ce qui est sous la souris (vide : rien d'intéressant)."""
    agent = renderer.agent_at(engine.everyone, mouse)
    if agent is not None:
        lines = [f"{agent.name}, {agent.persona.age} ans ({agent.persona.role})", agent.status_label.capitalize(),
                 f"Humeur : {agent.mood}"]
        if agent.action is not None and agent.action.reason:
            lines.append(f"« {agent.action.reason} »")
        return lines
    tile = renderer.screen_to_tile(mouse)
    house = engine.house
    obj = next((o for o in house.objects.values() if tile in o.tiles), None) or house.object_at_spot(tile)
    if obj is not None:
        return _object_lines(engine, obj)
    plan = engine.architect.plan
    if plan is not None:
        for room in plan.rooms:
            if room.status != "bati" and tile in room.outer_tiles():
                state = {"plan": "à défricher", "pret": "terrain prêt",
                         "chantier": f"chantier {room.fraction * 100:.0f} %"}[room.status]
                return [f"{room.name} (prévue) {room.width}×{room.height}", state.capitalize(),
                        f"Matériaux {room.materials_cost:.0f} $ · {room.wood_needed} bûches · {room.work_needed:.0f} h"]
    room = house.room_at(tile)
    if room and room not in house.outdoor_rooms:
        return [room]
    return []


def _object_lines(engine: Engine, obj) -> list[str]:
    lines = [obj.label]
    if obj.kind == "arbre":
        logs = {"Érable": 6, "Sapin": 5, "Bouleau": 4}.get(obj.label, 5) + engine.garage.wood_bonus()
        return [obj.label, f"À couper : {logs} bûches", "Coupable par la lisière" if obj.use_positions else "Pas encore accessible"]
    owned = next((o for o in engine.economy.household.items if o.object_id == obj.id), None)
    vehicle = engine.garage.get(obj.id) if obj.kind == "vehicule" else None
    if owned is not None:
        item = engine.inventory.catalogue.get(owned.item_id)
        lines.append(item.utilite if item else KIND_INFO.get(obj.kind, ""))
        cost = f"Acheté {owned.price:.0f} $" + (f" · {owned.weekly:+.0f} $/semaine" if owned.weekly else "")
        lines.append(cost)
    elif vehicle is not None:
        model = engine.garage.model(vehicle)
        lines.append(model.utilite)
        lines.append(f"Acheté {vehicle.price:.0f} $ · {model.places} place(s)")
        if obj.id in engine.garage.in_use():
            driver = next((a.name for a in engine.agents if a.vehicle == obj.id), "quelqu'un")
            lines.append(f"Parti avec {driver}")
    else:
        lines.append(OBJECT_INFO.get(obj.id, KIND_INFO.get(obj.kind, "")))
    if obj.id == "corde_bois":
        lines.append(f"{engine.economy.household.wood} bûches")
    if obj.quality != 1.0:
        lines.append(f"Qualité : {obj.quality * 100:.0f} %")
    users = [a.name for a in engine.agents
             if a.action is not None and a.action.use_pos in obj.use_positions and a.action.started]
    if users:
        lines.append("Utilisé par " + ", ".join(users))
    return [line for line in lines if line]


def draw(surface: pygame.Surface, lines: list[str], mouse: tuple[int, int], area: pygame.Rect) -> None:
    if not lines:
        return
    font, bold = theme.font(13), theme.font(13, bold=True)
    rendered: list[pygame.Surface] = []
    for index, text in enumerate(lines):
        for line in wrap_text(text, font, MAX_WIDTH):
            rendered.append((bold if index == 0 else font).render(line, True, theme.TEXT if index == 0 else theme.TEXT_DIM))
    width = max(r.get_width() for r in rendered) + 16
    height = sum(r.get_height() for r in rendered) + 10
    box = pygame.Rect(mouse[0] + 16, mouse[1] + 16, width, height)
    box.clamp_ip(area)
    panel = pygame.Surface(box.size, pygame.SRCALPHA)
    panel.fill((24, 24, 30, 235))
    surface.blit(panel, box.topleft)
    pygame.draw.rect(surface, theme.PANEL_BORDER, box, 1, border_radius=4)
    y = box.y + 5
    for image in rendered:
        surface.blit(image, (box.x + 8, y))
        y += image.get_height()
