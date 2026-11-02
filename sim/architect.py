"""L'IA architecte : le couple dessine sa maison, le moteur la place, on défriche, puis on bâtit.

Une soirée où les deux adultes sont au campement, le LLM (un seul appel) décide des pièces, de leur
taille, de leur nombre et de l'ordre de construction, avec une courte discussion du couple. Le moteur
place les pièces (world/building.py) ; les arbres sur l'emplacement de la prochaine pièce deviennent
prioritaires à couper. La construction elle-même (matériaux, travail) vient au lot C4 ;
world.terrain.instant_build bâtit une pièce dès que son emplacement est dégagé.
"""

from __future__ import annotations

import math
from concurrent.futures import Future
from typing import TYPE_CHECKING

from llm.architect_prompts import HouseDesign, RoomRequest, build_design_request, validate_design
from llm.service import StructuredResult
from world.building import HousePlan, PlannedRoom, build_room, place_rooms, room_cost, trees_in

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine
    from world.house import InteractiveObject

PLAN_HOURS = (19 * 60, 21 * 60 + 30)   # le couple dessine sa maison en soirée, au coin du feu
CONTRACTOR_RATE = 40.0                 # $ par heure de main-d'œuvre d'un entrepreneur
CONTRACTOR_HOURS = (8 * 60, 16 * 60)   # l'entrepreneur travaille en semaine, de 8 h à 16 h
CONTRACTOR_SPEED = 1.5                 # une équipe de métier avance plus vite qu'une personne
LUMBER_PRICE = 6.0                     # $ par bûche que l'entrepreneur doit acheter
MATERIALS_RESERVE_WEEKS = 1            # garder une semaine de dépenses en banque après les matériaux
SKILLED_WORDS = ("charpent", "menuis", "bricol")
SKILL = 1.5                            # un charpentier ou un bricoleur avance 50 % plus vite
SITE_GAP = 7                           # la première pièce se pose ~7 cases au nord du campement

FALLBACK_ROOMS = [  # plan sans LLM (ou si le LLM échoue) : petit et raisonnable
    RoomRequest(id="cuisine", type="cuisine", name="Cuisine", width=5, height=4),
    RoomRequest(id="chambre", type="chambre", name="Chambre", width=4, height=4, anchor="cuisine", side="est"),
    RoomRequest(id="sdb", type="salle_de_bain", name="Salle de bain", width=3, height=3, anchor="cuisine",
                side="ouest"),
    RoomRequest(id="salon", type="salon", name="Salon", width=6, height=5, anchor="cuisine", side="nord"),
]


class Architect:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.plan: HousePlan | None = None
        self.pending: Future[StructuredResult[HouseDesign]] | None = None
        self.pending_extension: tuple[Future[StructuredResult[HouseDesign]], str] | None = None

    @property
    def active(self) -> bool:
        return self.engine.house.layout.wild

    def busy(self) -> bool:
        return self.pending is not None or self.pending_extension is not None

    def clear(self) -> None:
        self.pending = self.pending_extension = None

    # ------------------------------------------------------------------ plan

    def couple(self) -> list[Agent]:
        return [a for a in self.engine.agents if a.persona.is_adult and not a.dead]

    def site(self) -> tuple[int, int]:
        # La tente de départ, même revendue depuis : la maison reste au même endroit
        house = self.engine.house
        tent = house.objects.get("tente") or next((o for o in house.layout.objects if o.id == "tente"), None)
        if tent is None:
            return self.engine.house.width // 2, self.engine.house.height // 2
        x, y, w, _h = tent.rect
        return x + w + 2, y - SITE_GAP + 3

    def update(self) -> None:
        """Chaque tick : dessiner la maison (une fois), suivre le défrichage, bâtir si instant_build."""
        if not self.active:
            return
        engine = self.engine
        if self.plan is None:
            if self.pending is None and self._evening_together():
                self._request_design()
            return
        clearing = self.clearing_room()
        if clearing is not None and not trees_in(engine.house, clearing):
            clearing.status = "pret"
            engine.publish("emplacement_pret", room=clearing.name)
            for agent in self.couple():
                engine.remember(agent, f"L'emplacement de la {clearing.name.lower()} est dégagé.", 4)
        room = self.plan.next_room()
        if room is not None and room.status == "pret" and engine.config.world.terrain.instant_build:
            self.build(room)
        elif room is not None and room.contractor and room.status == "chantier":
            self._contractor_tick(room)

    def _evening_together(self) -> bool:
        couple = self.couple()
        minute = self.engine.clock.minute_of_day
        return (len(couple) >= 1 and PLAN_HOURS[0] <= minute < PLAN_HOURS[1]
                and all(a.is_available for a in couple))

    def _request_design(self) -> None:
        engine = self.engine
        couple = self.couple()
        names = {a.id: a.name for a in couple}
        if engine.llm is None:
            self._apply(HouseDesign(vision="Une petite maison pour commencer.", rooms=FALLBACK_ROOMS), ok=False)
            return
        request = build_design_request(couple, engine.family_context(couple), engine.config.llm.max_tokens)
        fallback = HouseDesign(vision="Une petite maison pour commencer.", rooms=FALLBACK_ROOMS)
        future = engine.llm.try_submit(request, HouseDesign, fallback, lambda d: validate_design(d, names))
        if future is not None:
            self.pending = future

    def request_extension(self, reason: str) -> None:
        """Agrandir la maison (un bébé s'en vient, un enfant sans chambre) : l'IA ajoute 1 à 3 pièces."""
        if not self.active or self.plan is None or self.pending_extension is not None:
            return
        engine = self.engine
        couple = self.couple()
        existing = [r.id for r in self.plan.rooms]
        fallback = HouseDesign(rooms=[RoomRequest(id=f"chambre_{len(existing) + 1}", type="chambre",
                                                  name="Chambre des enfants", width=3, height=3,
                                                  anchor=existing[-1], side="nord")])
        if engine.llm is None:
            self._apply_extension(fallback, reason)
            return
        names = {a.id: a.name for a in couple}
        request = build_design_request(couple, engine.family_context(couple), engine.config.llm.max_tokens,
                                       existing=existing, reason=reason)
        future = engine.llm.try_submit(request, HouseDesign, fallback,
                                       lambda d: validate_design(d, names, set(existing)))
        if future is not None:
            self.pending_extension = (future, reason)

    def _apply_extension(self, design: HouseDesign, reason: str) -> None:
        engine = self.engine
        before = len(self.plan.rooms)
        place_rooms(engine.house, [r.model_dump() for r in design.rooms], self.site(), plan=self.plan)
        added = self.plan.rooms[before:]
        if design.discussion:
            engine.publish("dialogue", room="Terrain", participants=[a.name for a in self.couple()],
                           lines=[line.model_dump() for line in design.discussion], time=engine.clock.hhmm,
                           attempts=1, mode="scene")
        if not added:
            return
        names = ", ".join(f"{r.name.lower()} ({r.width}×{r.height})" for r in added)
        engine.publish("agrandissement", rooms=[r.name for r in added], text=f"On agrandit : {names}")
        for agent in self.couple():
            engine.remember(agent, f"{reason} On a ajouté au plan : {names}.", 7)

    def poll(self) -> None:
        if self.pending_extension is not None and self.pending_extension[0].done():
            (future, reason), self.pending_extension = self.pending_extension, None
            try:
                result = future.result()
            except Exception as exc:  # erreur inattendue dans le thread : rien à ajouter
                result = StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
            if result.value is not None:
                self._apply_extension(result.value, reason)
        if self.pending is None or not self.pending.done():
            return
        future, self.pending = self.pending, None
        try:
            result = future.result()
        except Exception as exc:  # erreur inattendue dans le thread : plan de repli
            result = StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
        design = result.value or HouseDesign(vision="Une petite maison pour commencer.", rooms=FALLBACK_ROOMS)
        self._apply(design, ok=result.ok)

    def _apply(self, design: HouseDesign, ok: bool) -> None:
        engine = self.engine
        specs = [r.model_dump() for r in design.rooms]
        plan = place_rooms(engine.house, specs, self.site(), design.vision)
        if not plan.rooms:  # rien n'a pu être placé : on retombe sur le petit plan
            plan = place_rooms(engine.house, [r.model_dump() for r in FALLBACK_ROOMS], self.site(), design.vision)
        self.plan = plan
        couple = self.couple()
        if design.discussion:
            engine.publish("dialogue", room="Terrain", participants=[a.name for a in couple],
                           lines=[line.model_dump() for line in design.discussion], time=engine.clock.hhmm,
                           attempts=1, mode="scene")
        rooms = ", ".join(f"{r.name.lower()} ({r.width}×{r.height})" for r in plan.rooms)
        engine.publish("plan_maison", vision=plan.vision, rooms=[r.model_dump() for r in plan.rooms],
                       rejected=plan.rejected, ok=ok, text=f"Plan de la maison : {plan.vision or rooms}")
        for agent in couple:
            engine.remember(agent, f"On a dessiné notre maison : {plan.vision} Pièces, dans l'ordre : {rooms}.", 8)
            if plan.rejected:
                engine.remember(agent, "Pas de place pour : " + " ; ".join(plan.rejected), 4)
        engine.mind.mark_stale("On vient de dessiner les plans de notre maison.")

    # ------------------------------------------------------------------ défrichage et construction

    def clearing_room(self) -> PlannedRoom | None:
        """Première pièce, dans l'ordre du plan, dont l'emplacement reste à défricher."""
        if self.plan is None:
            return None
        return next((r for r in self.plan.rooms if r.status == "plan"), None)

    def clearing_trees(self) -> list[InteractiveObject]:
        """Arbres sur l'emplacement de cette pièce (à couper en priorité, même avant le chantier)."""
        room = self.clearing_room()
        return trees_in(self.engine.house, room) if room is not None else []

    # ------------------------------------------------------------------ chantier

    def site_room(self) -> PlannedRoom | None:
        """Pièce en cours ou prochaine à bâtir, une fois son emplacement dégagé."""
        room = self.plan.next_room() if self.plan else None
        return room if room is not None and room.status in ("pret", "chantier") else None

    @staticmethod
    def skill(agent: Agent) -> float:
        p = agent.persona
        text = " ".join(p.traits + p.interests + p.routines).lower()
        return SKILL if any(word in text for word in SKILLED_WORDS) else 1.0

    def wood_per_hour(self, room: PlannedRoom) -> int:
        return max(1, math.ceil(room.wood_needed / room.work_needed))

    def wood_missing(self) -> int:
        """Bûches qui manquent encore pour finir la pièce du chantier (soi-même)."""
        room = self.site_room()
        if room is None or room.contractor:
            return 0
        return max(0, room.wood_needed - room.wood_used - self.engine.economy.household.wood)

    def can_afford_materials(self, room: PlannedRoom) -> bool:
        eco = self.engine.economy
        keep = eco.reserve(self.engine.alive_count()) * MATERIALS_RESERVE_WEEKS / 2
        return eco.household.money >= room.materials_cost + keep

    def start_session(self, agent: Agent, room_id: str | None) -> bool:
        """Début d'une séance : au premier coup de marteau, on achète les matériaux. False s'il faut annuler."""
        room = self.plan.room(room_id or "") if self.plan else None
        if room is None or room.status not in ("pret", "chantier") or room.contractor:
            return False
        if self.engine.economy.household.wood < 1:
            return False
        if not room.materials_paid:
            if not self.can_afford_materials(room):
                return False
            self.pay_materials(room)
        return True

    def materials_price(self, room: PlannedRoom) -> float:
        return round(room.materials_cost * (1 - self.engine.garage.materials_discount()), -1)  # camionnette

    def pay_materials(self, room: PlannedRoom) -> None:
        """Achat des matériaux (comptant ou grâce à un prêt rénovation) : le chantier commence."""
        if room.materials_paid:
            return
        eco = self.engine.economy
        eco.transaction(self.engine.clock.total_minutes, f"Matériaux : {room.name.lower()}",
                        -self.materials_price(room))
        room.materials_paid = True
        room.status = "chantier"
        self.engine.publish("chantier_debut", room=room.name,
                            text=f"Chantier lancé : {room.name} ({room.materials_cost:.0f} $ de matériaux)")
        for other in self.couple():
            self.engine.remember(other, f"On a acheté les matériaux de la {room.name.lower()} "
                                        f"({room.materials_cost:.0f} $). Le chantier commence !", 7)

    def work(self, agent: Agent, room_id: str | None, hours: float) -> None:
        """Fin d'une séance : du bois posé et des heures de travail en plus ; pièce finie, on la bâtit."""
        room = self.plan.room(room_id or "") if self.plan else None
        if room is None or room.status != "chantier":
            return
        household = self.engine.economy.household
        wanted = min(self.wood_per_hour(room) * hours, room.wood_needed - room.wood_used)
        logs = min(household.wood, math.ceil(wanted))
        household.wood -= logs
        room.wood_used += logs
        share = 1.0 if wanted <= 0 else min(1.0, logs / wanted)  # sans assez de bois, on avance moins
        room.progress += hours * self.skill(agent) * share
        if room.progress >= room.work_needed and room.wood_used >= room.wood_needed:
            self.build(room)
        else:
            self.engine.remember(agent, f"J'ai travaillé sur la {room.name.lower()} "
                                        f"({room.fraction * 100:.0f} % fait).", 2)

    def quote(self, room: PlannedRoom) -> tuple[float, int]:
        """Prix demandé par un entrepreneur pour finir la pièce, et nombre de jours ouvrables."""
        remaining = max(0.0, room.work_needed - room.progress)
        labor = remaining * CONTRACTOR_RATE
        materials = 0.0 if room.materials_paid else room.materials_cost
        lumber = max(0, room.wood_needed - room.wood_used - self.engine.economy.household.wood) * LUMBER_PRICE
        days = max(1, math.ceil(remaining / CONTRACTOR_SPEED / 8))
        return round(labor + materials + lumber, -1), days

    def can_hire(self, room: PlannedRoom) -> bool:
        eco = self.engine.economy
        price, _days = self.quote(room)
        return eco.household.money >= price + eco.reserve(self.engine.alive_count()) / 2

    def hire(self, agent: Agent, room_id: str | None) -> None:
        engine = self.engine
        room = self.plan.room(room_id or "") if self.plan else None
        if room is None or room.status not in ("pret", "chantier") or room.contractor:
            return
        price, days = self.quote(room)
        if engine.economy.household.money < price:
            engine.remember(agent, "Finalement, on n'a pas les moyens d'un entrepreneur.", 4)
            return
        engine.economy.transaction(engine.clock.total_minutes, f"Entrepreneur : {room.name.lower()}", -price)
        household = engine.economy.household
        logs = min(household.wood, room.wood_needed - room.wood_used)  # il prend notre bois, achète le reste
        household.wood -= logs
        room.wood_used = room.wood_needed
        room.materials_paid, room.contractor, room.status = True, True, "chantier"
        engine.publish("entrepreneur", room=room.name,
                       text=f"Entrepreneur engagé : {room.name} ({price:.0f} $, ~{days} jours)")
        for other in self.couple():
            engine.remember(other, f"On a engagé un entrepreneur pour la {room.name.lower()} : {price:.0f} $, "
                                   f"environ {days} jours.", 7)

    def _contractor_tick(self, room: PlannedRoom) -> None:
        clock = self.engine.clock
        if clock.weekday >= 5 or not CONTRACTOR_HOURS[0] <= clock.minute_of_day < CONTRACTOR_HOURS[1]:
            return
        room.progress += clock.tick_minutes / 60 * CONTRACTOR_SPEED
        if room.progress >= room.work_needed:
            self.build(room)

    def build(self, room: PlannedRoom) -> None:
        engine = self.engine
        room.progress = max(room.progress, room.work_needed)
        furniture = build_room(engine.house, self.plan, room)
        self._unstuck_everyone()
        self._assign_beds(furniture)
        engine.publish("piece_batie", room=room.name, size=f"{room.width}×{room.height}",
                       text=f"Nouvelle pièce bâtie : {room.name} ({room.width}×{room.height})")
        for agent in self.couple():
            engine.remember(agent, f"La {room.name.lower()} est bâtie ! On avance.", 7)

    def _unstuck_everyone(self) -> None:
        """Des murs viennent de monter : personne ne reste dans un mur ni sur un chemin qui les traverse."""
        engine = self.engine
        house = engine.house
        for agent in engine.agents:
            if agent.dead or agent.is_away or agent.persona.stage == "bebe":
                continue
            if not house.is_walkable(agent.pos):
                free = [(agent.pos[0] + dx, agent.pos[1] + dy) for r in range(1, 6)
                        for dx in range(-r, r + 1) for dy in range(-r, r + 1)]
                spot = next((p for p in free if house.is_walkable(p)), None)
                if spot is not None:
                    agent.pos = spot
            if agent.path and any(not house.is_walkable(p) for p in agent.path):
                goal = agent.action.use_pos if agent.action is not None else None
                if goal is None or not agent.set_destination(goal, house.is_walkable):
                    agent.path, agent.action = [], None

    def _assign_beds(self, furniture: list[InteractiveObject]) -> None:
        """Un nouveau lit : ceux qui dorment encore sous la tente s'y installent."""
        for bed in (o for o in furniture if o.kind == "lit"):
            sleepers = [a for a in self.engine.agents if not a.dead and a.bed_id == "tente"]
            for agent in sleepers[:bed.capacity]:
                agent.bed = bed.id
                self.engine.remember(agent, "Fini la tente : ce soir, je dors dans un vrai lit !", 7)

    # ------------------------------------------------------------------ prompts, interface, sauvegarde

    def context_line(self) -> str:
        if self.plan is None:
            return ""
        parts = []
        for room in self.plan.rooms:
            money, wood = room_cost(room.type, room.width, room.height)
            parts.append(f"{room.name} {room.width}×{room.height} ({self._state(room)} ; matériaux {money:.0f} $, "
                         f"{wood} bûches, {room.work_needed:.0f} h de travail)")
        line = f"Projet de maison : {self.plan.vision} Pièces dans l'ordre : " + " ; ".join(parts) + "."
        missing = self.wood_missing()
        if missing:
            line += f" Il manque {missing} bûches pour finir le chantier en cours."
        return line

    def _state(self, room: PlannedRoom) -> str:
        if room.status == "bati":
            return "bâtie"
        if room.status == "chantier":
            who = "entrepreneur" if room.contractor else "chantier"
            return f"{who} {room.fraction * 100:.0f} %"
        if room.status == "pret":
            return "terrain prêt"
        return f"{len(trees_in(self.engine.house, room))} arbres à couper"

    def hud_lines(self) -> list[str]:
        if self.plan is None:
            return ["Pas encore de plan : le couple en jasera un soir au coin du feu."] if self.active else []
        lines = [f"« {self.plan.vision} »"] if self.plan.vision else []
        for room in self.plan.rooms:
            lines.append(f"{room.name} {room.width}×{room.height} : {self._state(room)}")
        missing = self.wood_missing()
        if missing:
            lines.append(f"Manque {missing} bûches pour finir")
        return lines

    def to_dict(self) -> dict | None:
        return self.plan.model_dump(mode="json") if self.plan else None

    def load_dict(self, data: dict | None) -> None:
        """Recharge le plan et remonte les pièces déjà bâties (murs et meubles sont recalculés)."""
        self.pending = None
        self.plan = HousePlan.model_validate(data) if data else None
        if self.plan is None:
            return
        # Les objets achetés reviendront à leur place : les meubles de la pièce les évitent
        items = self.engine.economy.household.items
        for room in self.plan.rooms:
            if room.status == "bati":
                occupied = {(x + dx, y + dy) for o in items if o.room == room.name
                            for x, y, w, h in [o.rect] for dx in range(w) for dy in range(h)}
                build_room(self.engine.house, self.plan, room, occupied)
