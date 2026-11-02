"""Carrière : emploi, ancienneté, promotions, perte d'emploi, offres, retour aux études, scolarité des jeunes.

Chaque adulte a un emploi du catalogue (data/emplois.yaml) à un échelon, avec un employeur, une ancienneté
et une satisfaction au travail. Chaque matin (voir Engine._daily_calendar), selon la satisfaction : une
promotion, un congédiement, une offre d'ailleurs ; sans emploi : l'assurance-emploi et des offres. Le soir,
l'IA peut accepter une offre ou retourner aux études (frais au début, prêts et bourses pendant les cours,
meilleur emploi à la fin). Les jeunes ont un niveau scolaire selon l'âge et une moyenne que les devoirs
font monter ; à 18 ans, bonne moyenne : le cégep ; sinon un premier emploi.

Le salaire et l'horaire de travail de la fiche (persona) suivent la carrière (apply) : les autres modules
(paie, heures sup, crédit, événements) n'ont rien à savoir de plus.
"""

from __future__ import annotations

import random
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

from agents.actions import Option
from agents.persona import AwaySchedule

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

JOBS_FILE = Path("data/emplois.yaml")
BOURSE = 70.0               # prêts et bourses, par jour de cours
EI_RATE = 0.55              # assurance-emploi : part du dernier salaire, par jour de semaine
EI_DAYS = 30                # jours d'assurance-emploi au plus
PROMO_MIN_DAYS = 20         # jours entre deux promotions
PROMO_CHANCE = 0.08         # par jour de travail, si satisfait (60 et plus)
FIRE_CHANCE = 0.03          # par jour de travail, si la satisfaction tombe sous 25
OFFER_JOBLESS = 0.25        # chance d'une offre par jour de semaine sans emploi
OFFER_UNHAPPY = 0.05        # chance d'une offre d'ailleurs, si insatisfait (sous 50)
OFFER_DAYS = 5              # une offre reste valable ces jours-là
STUDY_EVERY = 7             # jours entre deux idées de retour aux études
EVENING = (17 * 60, 21 * 60 + 30)
WORK_DAYS = [0, 1, 2, 3, 4]
HISTORY = 8


class Job(BaseModel):
    id: str
    domaine: str
    formation: str | None = None
    echelons: list[tuple[str, float]]
    employeurs: list[str] = Field(default_factory=lambda: ["une entreprise du coin"])

    def title(self, level: int) -> str:
        return self.echelons[min(level, len(self.echelons) - 1)][0]

    def salary(self, level: int) -> float:
        return self.echelons[min(level, len(self.echelons) - 1)][1]


class Formation(BaseModel):
    id: str
    nom: str
    diplome: str
    jours: int
    frais: float
    emploi: str


class Career(BaseModel):
    """Situation de travail ou d'études d'une personne (sauvegardée avec elle)."""
    job: str | None = None
    level: int = 0
    employer: str = ""
    hired_day: int = 0
    promoted_day: int = 0
    satisfaction: float = 70.0
    formations: list[str] = Field(default_factory=list)
    studying: str | None = None
    study_left: int = 0              # jours de cours qu'il reste
    jobless_since: int | None = None
    ei_days: int = 0
    last_salary: float = 0.0
    offer: str | None = None         # « emploi|échelon » offert
    offer_until: int = -1
    study_idea_day: int = -100       # dernier jour où l'idée de retourner aux études a été proposée
    grade: float | None = None       # moyenne scolaire (jeunes)
    work_leave: str = "08:00"
    work_back: str = "16:30"
    history: list[str] = Field(default_factory=list)


def school_level(age: int) -> str:
    if age < 5:
        return "garderie"
    if age == 5:
        return "maternelle"
    if age < 12:
        year = age - 5
        return f"{year}{'re' if year == 1 else 'e'} année du primaire"
    if age < 17:
        return f"secondaire {age - 11}"
    return "cégep"


def load_jobs(path: Path = JOBS_FILE) -> tuple[dict[str, Job], dict[str, Formation]]:
    if not path.exists():
        return {}, {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs = {j.id: j for j in (Job.model_validate(raw) for raw in data.get("emplois", []))}
    formations = {f.id: f for f in (Formation.model_validate(raw) for raw in data.get("formations", []))}
    return jobs, formations


class Careers:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.jobs, self.formations = load_jobs()

    # ------------------------------------------------------------------ départ et fiche

    def setup(self) -> None:
        """Première partie : la carrière part de la fiche (emploi, formations) ou du salaire le plus proche."""
        for agent in self.engine.agents:
            if agent.career is None:
                agent.career = self._initial(agent)
        self.apply_all()

    def _initial(self, agent: Agent) -> Career | None:
        persona = agent.persona
        away = persona.schedule.away
        if away is not None and away.label == "école":
            return Career(grade=70.0 + zlib.crc32(agent.id.encode()) % 16)
        if persona.salary_per_day <= 0 or not self.jobs:
            return None
        job = self.jobs.get(persona.emploi or "") or min(
            self.jobs.values(), key=lambda j: abs(j.salary(0) - persona.salary_per_day))
        career = Career(job=job.id, formations=list(persona.formations) or ([job.formation] if job.formation else []))
        career.employer = persona.employeur or job.employeurs[zlib.crc32(agent.id.encode()) % len(job.employeurs)]
        if away is not None:
            career.work_leave, career.work_back = away.leave, away.back
        return career

    def apply_all(self) -> None:
        for agent in self.engine.agents:
            self.apply(agent)

    def apply(self, agent: Agent) -> None:
        """Le salaire et l'horaire de travail de la fiche suivent la carrière (rien à faire pour un jeune)."""
        career = agent.career
        if career is None or (career.grade is not None and agent.persona.age < 18):
            return
        persona = agent.persona
        if career.job is not None:
            persona.salary_per_day = self.jobs[career.job].salary(career.level)
            persona.schedule.away = AwaySchedule(leave=career.work_leave, back=career.work_back, days=WORK_DAYS,
                                                 label="travail")
        elif career.studying is not None:
            persona.salary_per_day = BOURSE
            persona.schedule.away = AwaySchedule(leave="08:00", back="15:30", days=WORK_DAYS, label="cours")
        else:
            persona.salary_per_day = 0.0
            persona.schedule.away = None

    # ------------------------------------------------------------------ descriptions

    def describe(self, agent: Agent, short: bool = False) -> str:
        """Une ligne : emploi, études ou école (short : sans l'ancienneté, pour le panneau)."""
        career = agent.career
        if career is None:
            return ""
        day = self.engine.clock.day
        if career.job is not None:
            job = self.jobs[career.job]
            text = f"{job.title(career.level)} · {job.salary(career.level):.0f} $/jour"
            return text if short else f"{text} · {day - career.hired_day} j d'ancienneté"
        if career.studying is not None:
            return f"Aux études : {self.formations[career.studying].nom} ({career.study_left} j de cours)"
        if career.grade is not None and agent.persona.age < 18:
            return f"{school_level(agent.persona.age).capitalize()} · moyenne {career.grade:.0f} %"
        ei = " (assurance-emploi)" if career.ei_days < EI_DAYS and career.last_salary else ""
        return f"Sans emploi{ei}"

    def _offer_text(self, career: Career) -> str | None:
        if not career.offer or self.engine.clock.day > career.offer_until:
            return None
        job_id, level = career.offer.split("|")
        job = self.jobs[job_id]
        return f"{job.title(int(level))} ({job.salary(int(level)):.0f} $/jour)"

    def lines(self, agent: Agent) -> list[str]:
        """Détails pour la fiche (touche P)."""
        career = agent.career
        if career is None:
            return []
        lines = [self.describe(agent)]
        if career.job is not None:
            lines.append(f"Chez {career.employer} · satisfaction au travail {career.satisfaction:.0f} %")
        offer = self._offer_text(career)
        if offer:
            lines.append(f"Offre reçue : {offer}")
        if career.formations:
            lines.append("Diplômes : " + ", ".join(self.formations[f].nom for f in career.formations
                                                   if f in self.formations))
        return lines + career.history[-4:]

    def context_line(self, agents: list[Agent]) -> str:
        """Pour les prompts : qui travaille où, qui étudie, qui cherche, l'école des jeunes."""
        parts = []
        for agent in agents:
            if agent.dead or agent.career is None:
                continue
            career = agent.career
            text = self.describe(agent)
            if career.job is not None:
                text += f", chez {career.employer}, satisfaction {career.satisfaction:.0f} %"
            offer = self._offer_text(career)
            if offer:
                text += f", a une offre : {offer}"
            parts.append(f"{agent.name} : {text}")
        return ("Travail et école : " + " ; ".join(parts) + ".") if parts else ""

    # ------------------------------------------------------------------ chaque matin

    def daily(self, day: int) -> None:
        engine = self.engine
        weekday = day % 7 < 5 and engine.calendar.holiday(day) is None
        for agent in engine.agents:
            career = agent.career
            if agent.dead or career is None:
                continue
            # Tirage propre à la personne et au jour : la carrière ne décale pas le hasard du reste du jeu
            luck = random.Random(f"carriere:{agent.id}:{day}")
            if career.offer and day > career.offer_until:
                career.offer = None
            if career.grade is not None and agent.persona.age < 18:
                if weekday and not engine.calendar.agent_off(agent, day):
                    career.grade = max(45.0, career.grade - 0.3)   # sans devoirs, la moyenne glisse
                continue
            if career.grade is not None and career.job is None and career.studying is None and not career.history:
                self._coming_of_age(agent, luck)
            elif career.studying is not None:
                if weekday and not engine.is_sick(agent):
                    career.study_left -= 1
                if career.study_left <= 0:
                    self._graduate(agent)
            elif career.job is None:
                self._jobless_day(agent, weekday, luck)
            else:
                self._work_day(agent, day, weekday, luck)

    def _work_day(self, agent: Agent, day: int, weekday: bool, luck: random.Random) -> None:
        career = agent.career
        now = self.engine.clock.total_minutes
        if (agent.unemployed_until is not None and now < agent.unemployed_until) or \
                (agent.parental_leave_until is not None and now < agent.parental_leave_until):
            return
        # Mesurée le matin : le plaisir et la vie sociale de la veille (le sommeil ne les remonte pas)
        needs = agent.needs
        target = 20 + 0.6 * (needs.fun + needs.social) / 2
        target -= (15 if self.engine.is_sick(agent) else 0) + (10 if self.engine.economy.household.money < 0 else 0)
        career.satisfaction = round(career.satisfaction + (target - career.satisfaction) * 0.15, 1)
        if not weekday:
            return
        job = self.jobs[career.job]
        if (career.satisfaction >= 60 and career.level + 1 < len(job.echelons)
                and day - max(career.promoted_day, career.hired_day) >= PROMO_MIN_DAYS
                and luck.random() < PROMO_CHANCE):
            self._promote(agent)
        elif career.satisfaction < 25 and luck.random() < FIRE_CHANCE:
            self.lose_job(agent, "congédiement")
        elif career.satisfaction < 50 and not career.offer and luck.random() < OFFER_UNHAPPY:
            better = [j for j in self._qualified(career)
                      if j.id != job.id and j.salary(0) >= job.salary(career.level)]
            if better:
                self._offer(agent, luck.choice(better), 0)

    def _jobless_day(self, agent: Agent, weekday: bool, luck: random.Random) -> None:
        career = agent.career
        engine = self.engine
        if not weekday:
            return
        if career.last_salary and career.ei_days < EI_DAYS and engine.economy.enabled:
            career.ei_days += 1
            amount = round(career.last_salary * EI_RATE, 2)
            engine.economy.transaction(engine.clock.total_minutes, f"Assurance-emploi de {agent.name}", amount)
            if career.ei_days == EI_DAYS:
                engine.remember(agent, "Fin de mon assurance-emploi. Il faut absolument trouver une job.", 7)
        if not career.offer and luck.random() < OFFER_JOBLESS:
            jobs = self._qualified(career)
            if jobs:
                self._offer(agent, max(jobs, key=lambda j: j.salary(0) + luck.random() * 60), 0)

    def _coming_of_age(self, agent: Agent, luck: random.Random) -> None:
        """18 ans : bonne moyenne, le cégep ; sinon, un premier emploi à chercher."""
        career = agent.career
        decs = [f for f in self.formations.values() if f.diplome == "DEC"]
        if career.grade >= 75 and decs:
            self.start_studies(agent, luck.choice(decs).id, free=True)
        else:
            career.jobless_since = self.engine.clock.day
            self._log(agent, "Fin du secondaire : à la recherche d'une première job")
            self.apply(agent)

    def _qualified(self, career: Career) -> list[Job]:
        return [j for j in self.jobs.values() if j.formation is None or j.formation in career.formations]

    # ------------------------------------------------------------------ événements de carrière

    def _tell_family(self, agent: Agent, text: str, own: int, others: int) -> None:
        for other in self.engine.agents:
            if not other.dead and other.persona.stage != "bebe":
                self.engine.remember(other, text, own if other is agent else others)

    def _offer(self, agent: Agent, job: Job, level: int) -> None:
        career = agent.career
        career.offer, career.offer_until = f"{job.id}|{level}", self.engine.clock.day + OFFER_DAYS
        text = f"{agent.name} reçoit une offre : {job.title(level)} ({job.salary(level):.0f} $/jour)"
        self.engine.publish("offre_emploi", agent=agent.id, name=agent.name, job=job.id, text=text)
        self.engine.remember(agent, f"On m'offre une job : {job.title(level)}, {job.salary(level):.0f} $ par jour.", 6)

    def hire(self, agent: Agent, job_id: str, level: int = 0) -> None:
        engine = self.engine
        career = agent.career
        job = self.jobs[job_id]
        day = engine.clock.day
        career.job, career.level, career.hired_day, career.promoted_day = job_id, level, day, day
        career.employer = random.Random(f"employeur:{agent.id}:{day}").choice(job.employeurs)
        career.satisfaction, career.jobless_since, career.ei_days, career.offer = 70.0, None, 0, None
        self.apply(agent)
        text = f"{agent.name} commence chez {career.employer} : {job.title(level)} ({job.salary(level):.0f} $/jour)"
        self._log(agent, f"Embauche : {job.title(level)} chez {career.employer}")
        engine.publish("embauche", agent=agent.id, name=agent.name, job=job_id, text=text)
        self._tell_family(agent, text + ".", 7, 4)

    def _promote(self, agent: Agent) -> None:
        engine = self.engine
        career = agent.career
        job = self.jobs[career.job]
        before = job.salary(career.level)
        career.level += 1
        career.promoted_day = engine.clock.day
        career.satisfaction = min(100.0, career.satisfaction + 15)
        self.apply(agent)
        raise_ = job.salary(career.level) - before
        text = f"Promotion pour {agent.name} : {job.title(career.level)} (+{raise_:.0f} $/jour)"
        self._log(agent, f"Promotion : {job.title(career.level)}")
        engine.publish("promotion", agent=agent.id, name=agent.name, job=career.job, text=text)
        self._tell_family(agent, text + " !", 8, 5)

    def lose_job(self, agent: Agent, reason: str) -> None:
        engine = self.engine
        career = agent.career
        career.last_salary = self.jobs[career.job].salary(career.level)
        career.job, career.jobless_since, career.ei_days = None, engine.clock.day, 0
        self.apply(agent)
        text = f"{agent.name} perd sa job ({reason}) chez {career.employer}"
        self._log(agent, f"Perte d'emploi ({reason}) chez {career.employer}")
        engine.publish("perte_emploi", agent=agent.id, name=agent.name, reason=reason, text=text)
        engine.remember(agent, f"J'ai perdu ma job ({reason}). L'assurance-emploi va aider un temps.", 9)
        for other in engine.agents:
            if other is not agent and not other.dead and other.persona.stage != "bebe":
                engine.remember(other, text + ".", 6)

    def start_studies(self, agent: Agent, formation_id: str, free: bool = False) -> None:
        engine = self.engine
        career = agent.career
        formation = self.formations[formation_id]
        if not free and engine.economy.enabled:
            engine.economy.transaction(engine.clock.total_minutes, f"Frais de scolarité : {formation.nom}",
                                       -formation.frais)
        if career.job is not None:
            career.last_salary = self.jobs[career.job].salary(career.level)
            career.job = None
        career.studying, career.study_left, career.offer = formation_id, formation.jours, None
        self.apply(agent)
        text = f"{agent.name} retourne aux études : {formation.nom} ({formation.jours} jours de cours)"
        self._log(agent, f"Retour aux études : {formation.nom}")
        engine.publish("etudes", agent=agent.id, name=agent.name, formation=formation_id, text=text)
        engine.remember(agent, f"Je commence un {formation.nom}. Ça va être serré, mais ça vaut la peine.", 8)

    def _graduate(self, agent: Agent) -> None:
        engine = self.engine
        career = agent.career
        formation = self.formations[career.studying]
        career.formations.append(formation.id)
        career.studying = None
        self.apply(agent)
        text = f"{agent.name} a son diplôme : {formation.nom} !"
        self._log(agent, f"Diplôme : {formation.nom}")
        engine.publish("diplome", agent=agent.id, name=agent.name, formation=formation.id, text=text)
        self._tell_family(agent, text, 9, 6)
        job = self.jobs.get(formation.emploi)
        if job is not None:
            self._offer(agent, job, 0)
            career.offer_until += OFFER_DAYS  # l'offre d'un premier emploi reste plus longtemps

    def _log(self, agent: Agent, text: str) -> None:
        history = agent.career.history
        history.append(f"Jour {self.engine.clock.day + 1} : {text}")
        del history[:-HISTORY]

    # ------------------------------------------------------------------ choix de l'IA

    def homework(self, agent: Agent, gain: float = 1.5) -> None:
        """Devoirs faits (ou une lecture) : la moyenne monte."""
        career = agent.career
        if career is not None and career.grade is not None and agent.persona.age < 18:
            career.grade = min(99.0, career.grade + gain)

    def options_for(self, agent: Agent) -> list[Option]:
        """Le soir, à la maison : accepter une offre, ou retourner aux études."""
        engine = self.engine
        career = agent.career
        minute = engine.clock.minute_of_day
        if (career is None or not engine.economy.enabled or not agent.persona.is_adult
                or not EVENING[0] <= minute < EVENING[1] or career.studying is not None):
            return []
        day = engine.clock.day
        options = []
        current = self.jobs[career.job].salary(career.level) if career.job else 0.0
        offer = self._offer_text(career)
        if offer:
            pay = self.jobs[career.offer.split("|")[0]].salary(int(career.offer.split("|")[1]))
            now = f"au lieu de {current:.0f} $" if career.job else "sans emploi en ce moment"
            score = 6 + max(0.0, pay - current) / 10 + (15 if career.job is None else 0)
            options.append(Option(action="carriere", target=f"offre|{career.offer}",
                                  label=f"accepte l'offre : {offer}, {now}", score=round(score, 2)))
        if day - career.study_idea_day >= STUDY_EVERY and (career.job is None or career.satisfaction < 55):
            budget = engine.economy.household.money - engine.economy.reserve(engine.alive_count())
            choices = [f for f in self.formations.values() if f.id not in career.formations and f.frais <= budget
                       and self.jobs[f.emploi].salary(0) > current + 20]
            if choices:
                career.study_idea_day = day
                formation = max(choices, key=lambda f: self.jobs[f.emploi].salary(0) - f.jours)
                later = self.jobs[formation.emploi].salary(0)
                label = (f"retourne aux études : {formation.nom} ({formation.jours} jours de cours, "
                         f"{formation.frais:.0f} $, ensuite environ {later:.0f} $/jour)")
                score = 4 + (6 if career.job is None else 0) + (4 if career.satisfaction < 40 else 0)
                options.append(Option(action="carriere", target=f"etudes|{formation.id}", label=label, score=score))
        return options

    def target_name(self, target: str | None) -> str | None:
        parts = (target or "").split("|")
        if parts[0] == "offre" and len(parts) == 3 and parts[1] in self.jobs:
            return f"l'offre : {self.jobs[parts[1]].title(int(parts[2]))}"
        if parts[0] == "etudes" and len(parts) == 2 and parts[1] in self.formations:
            return f"un {self.formations[parts[1]].nom}"
        return None

    def decide(self, agent: Agent, target: str | None) -> None:
        """L'action « carriere » est faite : on signe l'offre ou on s'inscrit aux études."""
        parts = (target or "").split("|")
        career = agent.career
        if career is None:
            return
        if parts[0] == "offre" and len(parts) == 3 and career.offer == f"{parts[1]}|{parts[2]}":
            self.hire(agent, parts[1], int(parts[2]))
        elif parts[0] == "etudes" and len(parts) == 2 and parts[1] in self.formations and career.studying is None:
            self.start_studies(agent, parts[1])
