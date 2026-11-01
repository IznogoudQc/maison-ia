"""L'IA architecte : le couple dessine sa maison, le moteur la place, on défriche, puis on bâtit.

Une soirée où les deux adultes sont au campement, le LLM (un seul appel) décide des pièces, de leur
taille, de leur nombre et de l'ordre de construction, avec une courte discussion du couple. Le moteur
place les pièces (world/building.py) ; les arbres sur l'emplacement de la prochaine pièce deviennent
prioritaires à couper. La construction elle-même (matériaux, travail) vient au lot C4 ;
world.terrain.instant_build bâtit une pièce dès que son emplacement est dégagé.
"""

from __future__ import annotations

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

    @property
    def active(self) -> bool:
        return self.engine.house.layout.wild

    def busy(self) -> bool:
        return self.pending is not None

    def clear(self) -> None:
        self.pending = None

    # ------------------------------------------------------------------ plan

    def couple(self) -> list[Agent]:
        return [a for a in self.engine.agents if a.persona.is_adult and not a.dead]

    def site(self) -> tuple[int, int]:
        tent = self.engine.house.objects.get("tente")
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

    def poll(self) -> None:
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

    def build(self, room: PlannedRoom) -> None:
        engine = self.engine
        furniture = build_room(engine.house, self.plan, room)
        self._assign_beds(furniture)
        engine.publish("piece_batie", room=room.name, size=f"{room.width}×{room.height}",
                       text=f"Nouvelle pièce bâtie : {room.name} ({room.width}×{room.height})")
        for agent in self.couple():
            engine.remember(agent, f"La {room.name.lower()} est bâtie ! On avance.", 7)

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
            state = {"bati": "bâtie", "pret": "emplacement dégagé",
                     "plan": f"{len(trees_in(self.engine.house, room))} arbres à couper"}[room.status]
            parts.append(f"{room.name} {room.width}×{room.height} ({state} ; {money:.0f} $, {wood} bûches)")
        return f"Projet de maison : {self.plan.vision} Pièces dans l'ordre : " + " ; ".join(parts) + "."

    def hud_lines(self) -> list[str]:
        if self.plan is None:
            return ["Pas encore de plan : le couple en jasera un soir au coin du feu."] if self.active else []
        lines = [f"« {self.plan.vision} »"] if self.plan.vision else []
        for room in self.plan.rooms:
            if room.status == "bati":
                state = "bâtie"
            elif room.status == "pret":
                state = "terrain prêt"
            else:
                state = f"{len(trees_in(self.engine.house, room))} arbres à couper"
            lines.append(f"{room.name} {room.width}×{room.height} : {state}")
        return lines

    def to_dict(self) -> dict | None:
        return self.plan.model_dump(mode="json") if self.plan else None

    def load_dict(self, data: dict | None) -> None:
        """Recharge le plan et remonte les pièces déjà bâties (murs et meubles sont recalculés)."""
        self.pending = None
        self.plan = HousePlan.model_validate(data) if data else None
        if self.plan is None:
            return
        for room in self.plan.rooms:
            if room.status == "bati":
                build_room(self.engine.house, self.plan, room)
