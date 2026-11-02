"""Projets de vie : chacun (dès 3 ans) se donne une aspiration, découpée en mois, en semaines et en jours.

L'IA choisit l'aspiration selon la fiche (goûts, caractère, situation), l'action du jeu qui la fait avancer,
l'objectif du premier mois et quatre étapes hebdomadaires. Chaque fois que la personne fait cette action,
le mois avance (deux fois par jour au plus) ; chaque semaine, on passe à l'étape suivante (en avance ou
en retard, on s'en souvient) ; mois réussi : l'IA planifie le suivant. Après trois mois réussis, le projet
est accompli, et un nouveau vient quelques jours plus tard. Le geste du jour attire la personne (bonus
de score) et le projet entre dans ses prompts ; la fiche (P) montre où elle en est.
"""

from __future__ import annotations

import random
from concurrent.futures import Future
from typing import TYPE_CHECKING

from agents.actions import ACTIONS, Option
from agents.aspiration import WEEKS_PER_MONTH, Aspiration
from llm.project_prompts import ProjectIdea, build_project_request, validate_project

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

PLAN_HOUR = 8
MONTH_GAIN = 9.0              # % de l'objectif du mois par geste
PROJECT_GAIN = 3.4            # % du projet entier par geste (environ trois mois)
DAILY_CREDITS = 2
MONTH_DAYS = 7 * WEEKS_PER_MONTH
REST_DAYS = 5                 # pause avant un nouveau projet
BOOST = 1.5
NOT_A_PROJECT = {"jaser", "flaner", "telephone", "sieste", "collation", "douche"}
# Repli sans IA : un projet par action préférée (texte, objectif du mois)
FALLBACK = {
    "piano": ("Apprendre à jouer du piano", "Jouer une première chanson au complet"),
    "lire": ("Lire plus de livres", "Finir un roman"),
    "exercice": ("Me remettre en forme", "Pédaler 30 minutes sans arrêter"),
    "jardiner": ("Faire pousser mes légumes", "Récolter mes premières tomates"),
    "devoirs": ("Avoir de meilleures notes", "Réussir mon prochain examen"),
    "jouer": ("Bâtir le plus gros château de Lego", "Finir la tour du château"),
    "ordi": ("Créer mon propre jeu vidéo", "Finir le premier niveau"),
}


class Projects:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.pending: dict[str, Future] = {}
        self.checked_day = engine.clock.day   # le premier jour, on s'installe : les projets viennent le lendemain

    def people(self) -> list[Agent]:
        return [a for a in self.engine.agents if not a.dead and a.persona.stage != "bebe"]

    def actions_for(self, agent: Agent) -> dict[str, str]:
        """Actions qui peuvent porter un projet : permises pour la personne, objet présent dans la maison."""
        keys, house = agent.persona.keys, self.engine.house
        found = {}
        for d in ACTIONS.values():
            if not d.selectable or d.name in NOT_A_PROJECT or "{target}" in d.label:
                continue
            if (d.allowed is not None and not keys & set(d.allowed)) or keys & set(d.excluded):
                continue
            if d.object_kind and not house.objects_of_kind(d.object_kind):
                continue
            found[d.name] = d.label
        return found

    # ------------------------------------------------------------------ chaque minute

    def update(self) -> None:
        engine = self.engine
        clock = engine.clock
        if clock.minute_of_day < PLAN_HOUR * 60 or self.checked_day == clock.day:
            return
        self.checked_day = clock.day
        for agent in self.people():
            aspiration = agent.aspiration
            if aspiration is None or (aspiration.done and clock.day - (aspiration.done_day or 0) >= REST_DAYS):
                self._request(agent, None)
            elif not aspiration.done:
                self._new_week(agent, aspiration, clock.day)

    def _new_week(self, agent: Agent, aspiration: Aspiration, day: int) -> None:
        engine = self.engine
        week = min(WEEKS_PER_MONTH - 1, (day - aspiration.phase_day) // 7)
        if week > aspiration.week_index:
            expected = week * 100 / WEEKS_PER_MONTH
            done = aspiration.week_step
            aspiration.week_index = week
            if aspiration.month_progress >= expected:
                engine.remember(agent, f"Étape de la semaine réussie pour mon projet : {done}.", 5)
            else:
                engine.remember(agent, f"J'ai pris du retard dans mon projet ({aspiration.text}). Faut que je m'y mette.", 5)
            engine.publish("projet_etape", agent=agent.id, name=agent.name,
                           text=f"{agent.name}, semaine {week + 1} : {aspiration.week_step}")
        if day - aspiration.phase_day >= MONTH_DAYS and aspiration.month_progress < 100:
            engine.remember(agent, f"Le mois est passé sans que j'atteigne « {aspiration.month_goal} ». "
                                   "Je recommence, autrement.", 6)
            aspiration.history.append(f"Mois {aspiration.phase} manqué : {aspiration.month_goal}")
            self._request(agent, aspiration)

    def _request(self, agent: Agent, current: Aspiration | None) -> None:
        engine = self.engine
        if agent.id in self.pending:
            return
        actions = self.actions_for(agent)
        if not actions:
            return
        fallback = self._fallback(agent, actions, current)
        if engine.llm is None:
            self._apply(agent, fallback)
            return
        keep = current.action if current is not None else None
        request = build_project_request(agent, engine.agents, actions, engine.clock.total_minutes,
                                        engine.dialogue_context([agent]), current.text if current else None,
                                        current.history if current else [], engine.config.llm.max_tokens)
        future = engine.llm.try_submit(request, ProjectIdea, fallback,
                                       lambda idea: validate_project(idea, set(actions), keep))
        if future is None:
            self._apply(agent, fallback)
        else:
            self.pending[agent.id] = future

    def _fallback(self, agent: Agent, actions: dict[str, str], current: Aspiration | None) -> ProjectIdea:
        if current is not None:
            goal = f"Aller plus loin : {current.text.lower()}"
            return ProjectIdea(aspiration=current.text, action=current.action, month_goal=goal,
                               weeks=[f"Semaine {i + 1} : pratiquer souvent" for i in range(4)])
        luck = random.Random(f"projet:{agent.id}:{self.engine.clock.day}")
        favorites = [a for a in agent.persona.favorite_actions if a in actions]
        action = next((a for a in favorites if a in FALLBACK), None) or next((a for a in FALLBACK if a in actions), None)
        action = action or (favorites[0] if favorites else luck.choice(sorted(actions)))
        text, goal = FALLBACK.get(action, (f"Devenir bon : {actions[action]}", "Y consacrer du temps chaque semaine"))
        weeks = ["Commencer doucement", "Pratiquer un peu chaque jour", "Essayer quelque chose de plus dur",
                 "Montrer mes progrès à la famille"]
        return ProjectIdea(aspiration=text, why="ça me tente depuis longtemps", action=action, month_goal=goal, weeks=weeks)

    def _apply(self, agent: Agent, idea: ProjectIdea) -> None:
        engine = self.engine
        day = engine.clock.day
        current = agent.aspiration
        if current is not None and not current.done and current.text == idea.aspiration:
            current.phase += 1 if current.month_progress >= 100 else 0
            current.phase_day, current.week_index, current.month_progress = day, 0, 0.0
            current.month_goal, current.weeks = idea.month_goal, idea.weeks
            engine.remember(agent, f"Nouveau mois pour mon projet ({current.text}) : {idea.month_goal}.", 5)
            return
        agent.aspiration = Aspiration(text=idea.aspiration, why=idea.why, action=idea.action, started_day=day,
                                      phase_day=day, month_goal=idea.month_goal, weeks=idea.weeks)
        engine.remember(agent, f"Je me lance un projet : {idea.aspiration}"
                               + (f" ({idea.why})" if idea.why else "") + f". Ce mois-ci : {idea.month_goal}.", 7)
        engine.publish("projet", agent=agent.id, name=agent.name,
                       text=f"{agent.name} se lance un projet : {idea.aspiration}")

    def poll(self) -> None:
        for agent_id, future in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[agent_id]
            try:
                idea = future.result().value
            except Exception:  # erreur inattendue dans le thread
                idea = None
            agent = self.engine.agent_by_id(agent_id)
            if idea is not None and agent is not None and not agent.dead:
                self._apply(agent, idea)

    # ------------------------------------------------------------------ progrès

    def boost(self, agent: Agent, options: list[Option]) -> None:
        """Le geste du jour attire, tant qu'il n'est pas fait."""
        aspiration = agent.aspiration
        if aspiration is None or aspiration.done or aspiration.did_today(self.engine.clock.day):
            return
        for option in options:
            if option.action == aspiration.action:
                option.score = round(option.score * BOOST + 2, 2)

    def on_done(self, agent: Agent, action_name: str) -> None:
        aspiration = agent.aspiration
        if aspiration is None or aspiration.done or action_name != aspiration.action:
            return
        engine = self.engine
        day = engine.clock.day
        if aspiration.credited.get(day, 0) >= DAILY_CREDITS:
            return
        aspiration.credited = {d: n for d, n in aspiration.credited.items() if day - d < 7}
        aspiration.credited[day] = aspiration.credited.get(day, 0) + 1
        aspiration.month_progress = min(100.0, aspiration.month_progress + MONTH_GAIN)
        aspiration.progress = min(100.0, aspiration.progress + PROJECT_GAIN)
        if aspiration.progress >= 100:
            aspiration.done, aspiration.done_day = True, day
            aspiration.history.append(f"Projet accompli : {aspiration.text}")
            engine.remember(agent, f"J'ai réussi mon projet : {aspiration.text} ! Je suis fier de moi.", 9)
            engine.publish("projet_reussi", agent=agent.id, name=agent.name,
                           text=f"{agent.name} a accompli son projet : {aspiration.text}")
        elif aspiration.month_progress >= 100:
            aspiration.history.append(f"Mois {aspiration.phase} réussi : {aspiration.month_goal}")
            engine.remember(agent, f"Objectif du mois atteint : {aspiration.month_goal} !", 8)
            engine.publish("projet_mois", agent=agent.id, name=agent.name,
                           text=f"{agent.name} atteint son objectif du mois : {aspiration.month_goal}")
            self._request(agent, aspiration)

    # ------------------------------------------------------------------ prompts et fiche

    def lines(self, agent: Agent) -> list[str]:
        aspiration = agent.aspiration
        if aspiration is None:
            return ["(l'IA cherche un projet à sa mesure…)" if agent.id in self.pending else "Pas encore de projet."]
        if aspiration.done:
            return [f"Accompli : {aspiration.text} — 100 %"] + aspiration.history[-3:]
        day = self.engine.clock.day
        label = ACTIONS[aspiration.action].label if aspiration.action in ACTIONS else aspiration.action
        today = "fait" if aspiration.did_today(day) else "à faire"
        return [f"{aspiration.text} — {aspiration.progress:.0f} %",
                f"Mois {aspiration.phase} : {aspiration.month_goal} ({aspiration.month_progress:.0f} %)",
                f"Semaine {aspiration.week_index + 1} : {aspiration.week_step}",
                f"Aujourd'hui : {label} ({today})"] + aspiration.history[-2:]
