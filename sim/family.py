"""Vie de famille (scénario terrain) : vieillir, désirer un enfant, grossesse, naissance, grandir.

Un an passe en LifeConfig.days_per_year jours simulés. Quand le couple est heureux, proche et a un
toit, un soir il en parle (un appel LLM : discussion + décision). S'il dit oui, la grossesse vient
quelques jours plus tard (ou l'adoption, si aucune fiche n'a can_be_pregnant), puis la naissance :
l'IA imagine le bébé (prénom, traits, intérêts). Le bébé dort dans un berceau près du lit des
parents et dépend d'eux ; un parent prend un congé parental la première année. Garderie de 1 à
4 ans, école dès 5 ans, un vrai lit à 3 ans (et l'architecte agrandit la maison).
"""

from __future__ import annotations

import re
import unicodedata
from concurrent.futures import Future
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agents.agent import ActiveAction, Agent
from agents.needs import Needs
from agents.persona import AwaySchedule, FixedTask, Persona, Schedule
from llm.family_prompts import (
    FALLBACK_NAMES,
    BabyTalk,
    ChildProfile,
    build_birth_request,
    build_talk_request,
    validate_child,
    validate_talk,
)
from llm.service import StructuredResult
from sim.clock import MINUTES_PER_DAY
from world.house import InteractiveObject

if TYPE_CHECKING:
    from sim.engine import Engine

TALK_HOURS = (19 * 60 + 30, 21 * 60 + 30)
MIN_MONEY = 1500.0                 # on ne parle pas de bébé avec moins que ça en banque
BIRTH_STAY = 12 * 60               # à l'hôpital pour l'accouchement
BABY_HUNGER_PER_HOUR = 3.0         # un bébé a faim plus souvent (en plus de la décroissance normale)
PREGNANCY_ENERGY_PER_HOUR = 1.0
HEAVY_WORK_BEFORE_DUE = 2 * MINUTES_PER_DAY   # plus de chantier ni de coupe dans les deux derniers jours
LEAVE_PAY_TIME = 16 * 60


class Pregnancy(BaseModel):
    carrier: str | None            # None : adoption
    start: int
    due: int


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_") or "bebe"


def schedule_for(age: int) -> Schedule:
    """Horaire d'un enfant né dans la partie, selon son âge."""
    if age < 3:
        away = AwaySchedule(leave="07:45", back="16:15", label="garderie") if age >= 1 else None
        return Schedule(wake="07:00", sleep="19:00", away=away)
    tasks = [FixedTask(time="18:00", action="souper")]
    if age < 5:
        return Schedule(wake="07:00", sleep="19:30", tasks=tasks,
                        away=AwaySchedule(leave="07:45", back="16:15", label="garderie"))
    if age < 13:
        return Schedule(wake="07:00", sleep="20:00", tasks=tasks,
                        away=AwaySchedule(leave="08:00", back="15:30", label="école"))
    if age < 18:
        return Schedule(wake="06:45", sleep="22:30", tasks=tasks,
                        away=AwaySchedule(leave="07:50", back="15:45", label="école"))
    return Schedule(wake="07:00", sleep="23:00", tasks=tasks,
                    away=AwaySchedule(leave="08:00", back="16:00", label="cégep"))


class FamilyLife:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.pregnancy: Pregnancy | None = None
        self.conceive_at: int | None = None
        self.last_talk_day = -100
        self.happiness: dict[str, float] = {}
        self.births: list[str] = []          # ids des enfants nés dans la partie
        self.last_leave_pay_day = -1
        self.pending_talk: Future[StructuredResult[BabyTalk]] | None = None
        self.pending_birth: Future[StructuredResult[ChildProfile]] | None = None

    @property
    def config(self):
        return self.engine.config.life

    @property
    def active(self) -> bool:
        return self.config.enabled and self.engine.house.layout.wild

    def busy(self) -> bool:
        return self.pending_talk is not None or self.pending_birth is not None

    def clear(self) -> None:
        self.pending_talk = self.pending_birth = None

    def year_minutes(self) -> float:
        return self.config.days_per_year * MINUTES_PER_DAY

    def couple(self) -> list[Agent]:
        return [a for a in self.engine.agents if a.persona.is_adult and not a.dead and a.id not in self.births]

    def children(self) -> list[Agent]:
        return [a for a in self.engine.agents if a.id in self.births and not a.dead]

    # ------------------------------------------------------------------ boucle

    def initialize(self) -> None:
        for agent in self.engine.agents:
            if agent.age_years is None:
                agent.age_years = float(agent.persona.age)

    def update(self) -> None:
        if not self.active:
            return
        self._age()
        clock = self.engine.clock
        if clock.minute_of_day % 60 == 0:
            self._update_happiness()
        self._maybe_talk()
        self._conception()
        self._pregnancy_tick()
        self._leave_pay()

    def poll(self) -> None:
        if self.pending_talk is not None and self.pending_talk.done():
            future, self.pending_talk = self.pending_talk, None
            result = _result(future)
            self._apply_talk(result.value or BabyTalk(decision="pas_maintenant", reason="On en reparlera."))
        if self.pending_birth is not None and self.pending_birth.done():
            future, self.pending_birth = self.pending_birth, None
            self._create_child(_result(future).value or self._fallback_profile())

    # ------------------------------------------------------------------ âge

    def _age(self) -> None:
        step = self.engine.clock.tick_minutes / self.year_minutes()
        for agent in self.engine.agents:
            if agent.dead:
                continue
            if agent.age_years is None:
                agent.age_years = float(agent.persona.age)
            agent.age_years += step
            if int(agent.age_years) > agent.persona.age:
                self._birthday(agent, int(agent.age_years))

    def _birthday(self, agent: Agent, age: int) -> None:
        engine = self.engine
        before = agent.persona.stage
        agent.persona.age = age
        if age >= 18 and agent.id not in self.births:
            return  # les adultes vieillissent en silence
        engine.publish("anniversaire", agent=agent.id, name=agent.name, age=age,
                       text=f"{agent.name} a {age} an{'s' if age > 1 else ''} aujourd'hui !")
        for other in engine.agents:
            if not other.dead and other.persona.stage != "bebe":
                engine.remember(other, f"Fête de {agent.name} : {age} an{'s' if age > 1 else ''} !", 5)
        if agent.id in self.births:
            agent.persona.schedule = schedule_for(age)
            agent.fired.clear()
        if before == "bebe" and agent.persona.stage != "bebe":
            self._first_bed(agent)

    # ------------------------------------------------------------------ bonheur et désir d'enfant

    def _update_happiness(self) -> None:
        for agent in self.couple():
            value = sum(agent.needs.as_dict().values()) / 5 * (agent.health / 100)
            current = self.happiness.get(agent.id, value)
            self.happiness[agent.id] = round(current * 0.95 + value * 0.05, 2)

    def ready_for_baby(self) -> tuple[bool, str]:
        """Conditions pour que le couple en parle ; sinon la raison (pour les tests et l'interface)."""
        engine = self.engine
        couple = self.couple()
        cfg = self.config
        if len(couple) < 2:
            return False, "il faut un couple"
        if self.pregnancy or self.conceive_at or self.pending_birth:
            return False, "un bébé s'en vient déjà"
        kids = self.children()
        if len(kids) >= cfg.max_children:
            return False, "la famille est complète"
        if any((k.age_years or 0) < 1 for k in kids):
            return False, "le petit dernier a moins d'un an"
        if not engine.has_roof():
            return False, "on vit encore sous la tente"
        if engine.economy.household.money < MIN_MONEY:
            return False, "pas assez d'argent de côté"
        a, b = couple[:2]
        if min(a.relation(b.id).affection, b.relation(a.id).affection) < cfg.min_affection:
            return False, "pas assez proches ces temps-ci"
        if min(self.happiness.get(a.id, 0), self.happiness.get(b.id, 0)) < cfg.min_happiness:
            return False, "pas assez heureux ces temps-ci"
        return True, ""

    def _maybe_talk(self) -> None:
        engine = self.engine
        clock = engine.clock
        if self.pending_talk is not None or clock.day - self.last_talk_day < self.config.talk_every_days:
            return
        if not TALK_HOURS[0] <= clock.minute_of_day < TALK_HOURS[1]:
            return
        couple = self.couple()
        if not all(a.is_available for a in couple) or not self.ready_for_baby()[0]:
            return
        self.last_talk_day = clock.day
        if engine.llm is None:
            self._apply_talk(BabyTalk(decision="oui", reason="On est heureux, on se sent prêts."))
            return
        names = {a.id: a.name for a in couple}
        request = build_talk_request(couple, engine.family_context(couple), clock.total_minutes,
                                     engine.config.llm.max_tokens, len(self.children()))
        fallback = BabyTalk(decision="pas_maintenant", reason="On en reparlera.")
        self.pending_talk = engine.llm.try_submit(request, BabyTalk, fallback, lambda t: validate_talk(t, names))

    def _apply_talk(self, talk: BabyTalk) -> None:
        engine = self.engine
        couple = self.couple()
        if talk.discussion:
            engine.publish("dialogue", room="Terrain", participants=[a.name for a in couple],
                           lines=[line.model_dump() for line in talk.discussion], time=engine.clock.hhmm,
                           attempts=1, mode="scene")
        engine.publish("projet_bebe", yes=talk.yes, reason=talk.reason,
                       text=("On essaie d'avoir un bébé !" if talk.yes else "Pas de bébé pour l'instant")
                       + (f" ({talk.reason})" if talk.reason else ""))
        for agent in couple:
            if talk.yes:
                engine.remember(agent, f"On a décidé d'essayer d'avoir un bébé. {talk.reason}", 8)
            else:
                engine.remember(agent, f"On a parlé d'avoir un bébé : pas maintenant. {talk.reason}", 6)
        if talk.yes:
            low, high = self.config.conception_days
            self.conceive_at = engine.clock.total_minutes + round(engine.rng.uniform(low, high) * MINUTES_PER_DAY)
            engine.architect.request_extension("Un bébé s'en vient : il lui faudra une chambre.")

    # ------------------------------------------------------------------ grossesse et naissance

    def carrier(self) -> Agent | None:
        return next((a for a in self.couple() if a.persona.can_be_pregnant), None)

    def _conception(self) -> None:
        engine = self.engine
        now = engine.clock.total_minutes
        if self.conceive_at is None or now < self.conceive_at:
            return
        self.conceive_at = None
        carrier = self.carrier()
        self.pregnancy = Pregnancy(carrier=carrier.id if carrier else None, start=now,
                                   due=now + round(self.config.pregnancy_days * MINUTES_PER_DAY))
        text = f"{carrier.name} est enceinte !" if carrier else "Le dossier d'adoption est accepté !"
        engine.publish("grossesse", carrier=carrier.name if carrier else None, text=text)
        for agent in self.couple():
            engine.remember(agent, f"Grande nouvelle : {text} On va être parents.", 9)
        engine.mind.mark_stale(text)

    def _pregnancy_tick(self) -> None:
        engine = self.engine
        pregnancy = self.pregnancy
        if pregnancy is None or self.pending_birth is not None:
            return
        carrier = engine.agent_by_id(pregnancy.carrier) if pregnancy.carrier else None
        now = engine.clock.total_minutes
        if carrier is not None and not carrier.is_sleeping and not carrier.is_away:
            carrier.needs.apply({"energy": -PREGNANCY_ENERGY_PER_HOUR * engine.clock.tick_minutes / 60})
        if now < pregnancy.due:
            return
        if carrier is not None:
            engine._cancel_decision(carrier)
            carrier.action, carrier.path = None, []
            carrier.away_until, carrier.away_label = now + BIRTH_STAY, "hôpital (accouchement)"
            carrier.away_kind, carrier.away_pay = "hopital", 0.0
        parents = self.couple()
        taken = {a.name for a in engine.agents}
        if engine.llm is None:
            self._create_child(self._fallback_profile())
            return
        request = build_birth_request(parents, taken, engine.config.llm.max_tokens, adoption=carrier is None)
        future = engine.llm.try_submit(request, ChildProfile, self._fallback_profile(),
                                       lambda p: validate_child(p, taken))
        if future is None:
            self._create_child(self._fallback_profile())
        else:
            self.pending_birth = future

    def _fallback_profile(self) -> ChildProfile:
        taken = {a.name.lower() for a in self.engine.agents}
        name = next((n for n in FALLBACK_NAMES if n.lower() not in taken), f"Bébé {len(self.births) + 1}")
        return ChildProfile(name=name, traits=["curieux", "rieur", "têtu"], interests=["les animaux", "dessiner"])

    def _inherit(self, parents: list[Agent], field: str) -> list[str]:
        """Sans réponse de l'IA : une qualité (ou un défaut) de chaque parent."""
        out = []
        for parent in parents:
            choices = [t for t in getattr(parent.persona, field) if t not in out]
            if choices:
                out.append(self.engine.rng.choice(choices))
        return out

    def _create_child(self, profile: ChildProfile) -> Agent:
        engine = self.engine
        now = engine.clock.total_minutes
        pregnancy, self.pregnancy = self.pregnancy, None
        parents = self.couple()
        child_id = f"enfant_{_slug(profile.name)}"
        while engine.agent_by_id(child_id):
            child_id += "_2"
        persona = Persona(
            id=child_id, name=profile.name, age=0, role="enfant", color=tuple(profile.color),
            look={"hair": profile.hair, "long_hair": False}, traits=profile.traits,
            qualites=profile.qualites or self._inherit(parents, "qualites"),
            defauts=profile.defauts or self._inherit(parents, "defauts"),
            interests=profile.interests, speech_style=profile.speech_style,
            relations={p.id: f"Son parent, {p.name}." for p in parents},
            bed="tente", schedule=schedule_for(0),
        )
        for parent in parents:
            parent.persona.relations[child_id] = f"Notre enfant, {profile.name}."
        baby = Agent(persona=persona, pos=parents[0].pos if parents else (0, 0), age_years=0.0,
                     needs=Needs(hunger=80, energy=80, hygiene=80, social=80, fun=80))
        crib = self._place_crib(baby, parents)
        if crib is not None:
            baby.bed = crib.id
            baby.pos = crib.rect[:2]
        carrier = engine.agent_by_id(pregnancy.carrier) if pregnancy and pregnancy.carrier else None
        if carrier is not None and carrier.is_away:
            baby.away_until, baby.away_label, baby.away_kind = carrier.away_until, "hôpital", "hopital"
        engine.agents.append(baby)
        self.births.append(child_id)
        leave_parent = carrier or (parents[0] if parents else None)
        if leave_parent is not None:
            leave_parent.parental_leave_until = now + round(self.config.parental_leave_years * self.year_minutes())
        how = "adopté" if pregnancy and pregnancy.carrier is None else "né"
        engine.publish("naissance", agent=child_id, name=profile.name,
                       text=f"Bienvenue {profile.name} ! ({', '.join(profile.traits)})")
        for parent in parents:
            engine.remember(parent, f"{profile.name} est {how} aujourd'hui. Le plus beau jour de ma vie.", 10)
            if parent is leave_parent:
                engine.remember(parent, "Je prends mon congé parental (RQAP) pour m'occuper du bébé.", 6)
        engine.mind.mark_stale(f"{profile.name} vient d'arriver dans la famille.")
        return baby

    def _place_crib(self, baby: Agent, parents: list[Agent]) -> InteractiveObject | None:
        """Berceau sur une case libre près du lit des parents (ou de la tente)."""
        house = self.engine.house
        bed = house.objects.get(parents[0].bed_id) if parents else None
        if bed is None:
            return None
        bx, by, bw, bh = bed.rect
        reserved = {p for o in house.objects.values() for p in o.use_positions}
        bed_room = house.room_at(bed.use_positions[0]) if bed.use_positions else None
        # D'abord dans la chambre des parents, puis au plus près du lit
        candidates = sorted(((x, y) for x in range(bx - 3, bx + bw + 3) for y in range(by - 2, by + bh + 3)),
                            key=lambda p: (house.room_at(p) != bed_room, abs(p[0] - bx) + abs(p[1] - by)))
        for x, y in candidates:
            if not house.is_walkable((x, y)) or (x, y) in reserved or (x, y) in house.doors:
                continue
            if any((x + dx, y + dy) in house.doors for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0))):
                continue  # juste devant une porte : on boucherait le passage
            if not _keeps_passage(house, (x, y)):
                continue
            spots = [p for p in ((x, y + 1), (x - 1, y), (x + 1, y), (x, y - 1))
                     if house.is_walkable(p) and p not in reserved and p not in house.doors]
            if not spots:
                continue
            crib = InteractiveObject(f"berceau_{baby.id}", "berceau", f"Berceau de {baby.name}",
                                     house.room_at((x, y)) or "Terrain", (x, y, 1, 1), spots[:1])
            house.add_object(crib)
            return crib
        return None

    def _first_bed(self, child: Agent) -> None:
        """À 3 ans : un vrai lit libre s'il y en a un, sinon un matelas à la place du berceau."""
        engine = self.engine
        house = engine.house
        used: dict[str, int] = {}
        for agent in engine.agents:
            if not agent.dead:
                used[agent.bed_id] = used.get(agent.bed_id, 0) + 1
        free = [o for o in house.objects_of_kind("lit")
                if o.id.startswith("maison_") and used.get(o.id, 0) < o.capacity]
        crib = house.objects.get(child.bed or "")
        if free:
            child.bed = free[0].id
        elif crib is not None:
            mattress = InteractiveObject(f"matelas_{child.id}", "lit", f"Matelas de {child.name}", crib.room,
                                         crib.rect, list(crib.use_positions))
            house.remove_object(crib.id)
            house.add_object(mattress)
            child.bed = mattress.id
            engine.architect.request_extension(f"{child.name} a 3 ans et dort sur un matelas : il lui faut sa chambre.")
        if crib is not None and crib.id in house.objects:
            house.remove_object(crib.id)
        engine.remember(child, "J'ai un vrai lit de grand !", 6)

    # ------------------------------------------------------------------ bébé au quotidien

    def update_baby(self, baby: Agent) -> None:
        """Le bébé ne marche pas : il dort, va à la garderie (porté) et attend les soins au berceau."""
        engine = self.engine
        clock = engine.clock
        minutes = clock.tick_minutes
        scheduled = engine.scheduler.check(baby, clock)
        if scheduled is not None and scheduled.action == "dormir":
            baby.action = ActiveAction(name="dormir", until_minute=scheduled.until, forced=True, started=True)
        elif scheduled is not None and scheduled.action == "partir":
            action = engine.make_action(baby, "partir", scheduled.target, forced=True, until=scheduled.until)
            if action is not None:
                engine._leave(baby, action)
                return
        if baby.action is not None and baby.action.until_minute is not None \
                and clock.total_minutes >= baby.action.until_minute:
            baby.action = None
        baby.needs.decay(minutes, "sleeping" if baby.is_sleeping else "awake")
        if not baby.is_sleeping:
            baby.needs.apply({"hunger": -BABY_HUNGER_PER_HOUR * minutes / 60})
        crib = engine.house.objects.get(baby.bed or "")
        if crib is not None:
            baby.pos, baby.path = crib.rect[:2], []

    def babies_needing_care(self) -> list[tuple[Agent, str, float]]:
        """Bébés à la maison et le besoin le plus bas : (bébé, besoin, valeur)."""
        out = []
        for baby in self.children():
            if baby.persona.stage != "bebe" or baby.is_away:
                continue
            need, value = baby.needs.lowest()
            if baby.is_sleeping and value >= 25:
                continue  # on ne réveille pas un bébé qui dort pour rien
            out.append((baby, need, value))
        return out

    def heavy_work_ok(self, agent: Agent) -> bool:
        """Fin de grossesse : ni chantier ni coupe d'arbres."""
        p = self.pregnancy
        return not (p and p.carrier == agent.id and self.engine.clock.total_minutes > p.due - HEAVY_WORK_BEFORE_DUE)

    def _leave_pay(self) -> None:
        engine = self.engine
        clock = engine.clock
        if clock.minute_of_day < LEAVE_PAY_TIME or clock.weekday >= 5 or self.last_leave_pay_day == clock.day:
            return
        self.last_leave_pay_day = clock.day
        for agent in self.couple():
            if agent.parental_leave_until is None:
                continue
            if clock.total_minutes >= agent.parental_leave_until:
                agent.parental_leave_until = None
                engine.remember(agent, "Fin du congé parental : retour au travail lundi.", 6)
                continue
            pay = round(agent.persona.salary_per_day * self.config.leave_pay_rate, 2)
            if pay:
                engine.economy.transaction(clock.total_minutes, f"Prestations RQAP de {agent.name}", pay)

    # ------------------------------------------------------------------ prompts, interface, sauvegarde

    def context_lines(self) -> list[str]:
        if not self.active:
            return []
        lines = []
        engine = self.engine
        if self.pregnancy:
            carrier = engine.agent_by_id(self.pregnancy.carrier) if self.pregnancy.carrier else None
            day = (engine.clock.total_minutes - self.pregnancy.start) // MINUTES_PER_DAY + 1
            total = round(self.config.pregnancy_days)
            who = f"{carrier.name} est enceinte" if carrier else "L'adoption est en cours"
            lines.append(f"{who} (jour {day} sur {total}).")
        elif self.conceive_at:
            lines.append("Le couple essaie d'avoir un bébé.")
        kids = self.children()
        if kids:
            lines.append("Enfants : " + ", ".join(f"{k.name} ({k.persona.age} an{'s' if k.persona.age > 1 else ''}, "
                                                  f"{k.persona.stage})" for k in kids) + ".")
        return lines

    def hud_lines(self) -> list[str]:
        if not self.active:
            return []
        lines = []
        if self.pregnancy:
            day = (self.engine.clock.total_minutes - self.pregnancy.start) // MINUTES_PER_DAY + 1
            carrier = self.engine.agent_by_id(self.pregnancy.carrier) if self.pregnancy.carrier else None
            lines.append(f"{carrier.name + ' enceinte' if carrier else 'Adoption'} : jour {day} sur "
                         f"{round(self.config.pregnancy_days)}")
        elif self.conceive_at:
            lines.append("Projet : un bébé")
        return lines

    def to_dict(self) -> dict:
        births = [self.engine.agent_by_id(i) for i in self.births]
        return {"pregnancy": self.pregnancy.model_dump() if self.pregnancy else None,
                "conceive_at": self.conceive_at, "last_talk_day": self.last_talk_day,
                "happiness": self.happiness, "last_leave_pay_day": self.last_leave_pay_day,
                "births": [a.persona.model_dump(mode="json") for a in births if a is not None],
                "cribs": [o.__dict__ | {"rect": list(o.rect), "use_positions": [list(p) for p in o.use_positions]}
                          for o in self.engine.house.objects.values() if o.kind == "berceau"
                          or o.id.startswith("matelas_")]}

    def load_dict(self, data: dict | None) -> None:
        """À appeler avant de restaurer les agents : recrée les enfants nés dans la partie."""
        self.clear()
        data = data or {}
        self.pregnancy = Pregnancy.model_validate(data["pregnancy"]) if data.get("pregnancy") else None
        self.conceive_at = data.get("conceive_at")
        self.last_talk_day = data.get("last_talk_day", -100)
        self.happiness = dict(data.get("happiness", {}))
        self.last_leave_pay_day = data.get("last_leave_pay_day", -1)
        self.births = []
        engine = self.engine
        for raw in data.get("births", []):
            persona = Persona.model_validate(raw)
            if engine.agent_by_id(persona.id) is None:
                engine.agents.append(Agent(persona=persona, pos=(0, 0)))
            self.births.append(persona.id)
            for parent in self.couple():
                parent.persona.relations.setdefault(persona.id, f"Notre enfant, {persona.name}.")
        for raw in data.get("cribs", []):
            obj = InteractiveObject(raw["id"], raw["kind"], raw["label"], raw["room"], tuple(raw["rect"]),
                                    [tuple(p) for p in raw["use_positions"]], raw.get("quality", 1.0))
            engine.house.add_object(obj)

    def after_load(self) -> None:
        """Les fiches viennent du YAML (âge de départ) : on remet l'âge sauvegardé."""
        for agent in self.engine.agents:
            if agent.age_years is not None:
                agent.persona.age = int(agent.age_years)
            if agent.id in self.births:
                agent.persona.schedule = schedule_for(agent.persona.age)


def _keeps_passage(house, tile: tuple[int, int]) -> bool:
    """Poser un meuble sur tile laisse ses voisines libres reliées entre elles (pas de couloir bouché)."""
    from world.pathfinding import find_path
    x, y = tile
    around = [p for p in ((x, y + 1), (x - 1, y), (x + 1, y), (x, y - 1)) if house.is_walkable(p)]
    passable = lambda p: p != tile and house.is_walkable(p)  # noqa: E731
    return all(find_path(around[0], other, passable, max_nodes=400) is not None for other in around[1:])


def _result(future: Future) -> StructuredResult:
    try:
        return future.result()
    except Exception as exc:  # erreur inattendue dans le thread
        return StructuredResult(value=None, ok=False, attempts=0, error=str(exc))
