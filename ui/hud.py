"""Panneau latéral : heure, vitesse, agent sélectionné, contrôles."""

from __future__ import annotations

import pygame

from agents.actions import action_label
from agents.agent import Agent
from agents.needs import NEED_LABELS
from llm.service import LLMService
from sim.clock import DAY_NAMES, SimClock
from sim.economy import Economy
from ui import theme
from ui.dialogue_box import wrap_text

HEALTH_WARNING = 60.0  # vue famille : santé affichée sous ce seuil
MAX_PLAN_LINES = 6
PLAN_DONE = (120, 200, 130)
PLAN_MISSED = (200, 110, 100)
PLAN_THOUGHT = (180, 170, 230)

CONTROLS = [
    "Espace : pause / reprise    1-4 : vitesse",
    "Clic : sélectionner un agent (clic vide : famille)",
    "Flèches / clic droit glissé : vue   molette : zoom",
    "F : suivre   P : fiche   H : dialogues   J : journal   I : maison",
    "Échap : sauvegarder et quitter",
]



def format_cost(dollars: float) -> str:
    """« 0,013 $ US » : trois décimales sous 10 $ (une partie coûte souvent quelques cents)."""
    return f"{dollars:.3f} $ US".replace(".", ",") if dollars < 10 else f"{dollars:.2f} $ US".replace(".", ",")


class Hud:
    def __init__(self, rect: pygame.Rect) -> None:
        self.rect = rect
        self.agents: list[Agent] = []  # pour afficher les prénoms des cibles du plan

    def draw(self, surface: pygame.Surface, clock: SimClock, speed: float, paused: bool,
             agents: list[Agent], selected: Agent | None, llm: LLMService | None = None,
             llm_label: str = "", economy: Economy | None = None, alive: int = 0,
             promises: list[str] | None = None, extra: list[str] | None = None,
             project: list[str] | None = None, possessions: list[str] | None = None) -> None:
        self.agents = agents
        pygame.draw.rect(surface, theme.PANEL, self.rect)
        pygame.draw.line(surface, theme.PANEL_BORDER, self.rect.topleft, self.rect.bottomleft, 2)
        x, y = self.rect.x + 14, self.rect.y + 12
        surface.blit(theme.font(20, bold=True).render(clock.label(), True, theme.TEXT), (x, y))
        y += 32
        state = "PAUSE" if paused else f"Vitesse x{speed:g}"
        surface.blit(theme.font(15).render(state, True, theme.ACCENT if paused else theme.TEXT_DIM), (x, y))
        date_text = clock.date_label()
        if date_text:
            surface.blit(theme.font(13).render(_clip(date_text, 40), True, theme.TEXT_DIM), (x + 110, y + 2))
        y += 24
        if llm is not None:
            y = self._draw_llm(surface, x, y, llm, llm_label)
        y += 8
        if economy is not None and economy.enabled:
            y = self._draw_household(surface, x, y, economy, alive)
        for line in extra or []:  # terrain : réserve de bois, arbres restants
            surface.blit(theme.font(12).render(line, True, theme.TEXT_DIM), (x, y - 4))
            y += 16

        controls_top = self.rect.bottom - 18 * len(CONTROLS) - 10
        if selected is None:
            y = self._draw_family(surface, x, y, agents)
            if promises:
                y = self._draw_promises(surface, x, y + 6, promises)
            if project:
                y = self._draw_promises(surface, x, y + 6, project, "Maison", theme.TEXT_DIM)
            if possessions:
                y = self._draw_promises(surface, x, y + 6, possessions, "Objets", theme.TEXT_DIM)
            if economy is not None and economy.enabled:
                self._draw_ledger(surface, x, y + 8, economy, controls_top - 8)
        else:
            y = self._draw_agent(surface, x, y, selected)
            if not selected.dead:
                y = self._draw_mind(surface, x, y, selected, clock)
                y = self._draw_relations(surface, x, y, selected, agents)
            self._draw_memory(surface, x, y, selected, controls_top - 8)

        y = controls_top
        for line in CONTROLS:
            surface.blit(theme.font(13).render(line, True, theme.TEXT_DIM), (x, y))
            y += 18

    def _draw_llm(self, surface: pygame.Surface, x: int, y: int, llm: LLMService, label: str) -> int:
        stats = llm.stats
        lines = [
            f"LLM : {label}",
            f"Appels : {stats.calls}  ({llm.limiter.used()}/{llm.limiter.max_per_minute} cette minute)",
            f"Tokens : {stats.input_tokens:,} entrée / {stats.output_tokens:,} sortie".replace(",", " "),
            f"Coût de la partie : {format_cost(llm.cost())}" if any(llm.prices) else "Coût : gratuit (pas de Claude)",
            *([f"Cache : {stats.cache_read_tokens:,} tokens relus (-{format_cost(llm.stats.cache_savings(llm.prices[0]))})"
               .replace(",", " ")] if stats.cache_read_tokens and any(llm.prices) else []),
            f"Échecs : {stats.failures}  —  replis : {stats.fallbacks}",
        ]
        for line in lines:
            surface.blit(theme.font(12).render(_clip(line, 56), True, theme.TEXT_DIM), (x, y))
            y += 16
        return y

    def _draw_household(self, surface: pygame.Surface, x: int, y: int, economy: Economy, alive: int) -> int:
        h = economy.household
        money_color = (235, 90, 80) if h.money < 0 else (120, 210, 130)
        surface.blit(theme.font(17, bold=True).render(_money(h.money), True, money_color), (x, y))
        days = economy.pantry_days(alive)
        pantry_color = (235, 90, 80) if days < 1 else (230, 180, 70) if days < 2 else theme.TEXT_DIM
        pantry = f"Garde-manger : {h.pantry:.0f} portions (~{days:.1f} j)".replace(".", ",")
        surface.blit(theme.font(13).render(pantry, True, pantry_color), (x + 130, y + 3))
        y += 24
        day = DAY_NAMES[economy.config.bills_weekday]
        bills = f"Factures chaque {day} : {_money(economy.weekly_bills())}"
        surface.blit(theme.font(12).render(bills, True, theme.TEXT_DIM), (x, y))
        return y + 22

    def _draw_ledger(self, surface: pygame.Surface, x: int, y: int, economy: Economy, bottom: int) -> None:
        surface.blit(theme.font(14, bold=True).render("Derniers mouvements", True, theme.TEXT), (x, y))
        y += 20
        for entry in reversed(economy.household.ledger):
            if y + 16 > bottom:
                break
            color = (120, 210, 130) if entry.amount >= 0 else (235, 130, 110)
            sign = "+" if entry.amount >= 0 else "−"
            surface.blit(theme.font(12).render(_clip(entry.label, 38), True, theme.TEXT_DIM), (x, y))
            amount = theme.font(12, bold=True).render(f"{sign}{_money(abs(entry.amount))}", True, color)
            surface.blit(amount, (self.rect.right - 16 - amount.get_width(), y))
            y += 16

    def _draw_family(self, surface: pygame.Surface, x: int, y: int, agents: list[Agent]) -> int:
        surface.blit(theme.font(15, bold=True).render("Famille", True, theme.TEXT), (x, y))
        y += 24
        for agent in agents:
            color = (90, 90, 100) if agent.dead else agent.persona.color
            pygame.draw.circle(surface, color, (x + 7, y + 9), 7)
            text = f"{agent.name} ({agent.persona.age}) — {agent.status_label}"
            if not agent.dead and agent.health < HEALTH_WARNING:
                text += f" (santé {agent.health:.0f})"
            surface.blit(theme.font(13).render(_clip(text, 44), True, theme.TEXT_DIM), (x + 20, y))
            y += 22
        return y

    def _draw_agent(self, surface: pygame.Surface, x: int, y: int, agent: Agent) -> int:
        persona = agent.persona
        pygame.draw.circle(surface, persona.color, (x + 9, y + 12), 9)
        title = f"{persona.name}, {persona.age} ans ({persona.role})"
        surface.blit(theme.font(17, bold=True).render(title, True, theme.TEXT), (x + 24, y))
        y += 28
        careers = getattr(self, "careers", None)  # sim.career.Careers, branché par main.py
        work = careers.describe(agent, short=True) if careers is not None else ""
        for line in (f"Action : {agent.status_label}",
                     f"Humeur : {agent.mood}",
                     f"Pièce : {agent.last_room or '-'}" if not agent.is_away else "Pièce : dehors",
                     *([f"Travail : {work}" if agent.persona.is_adult else f"École : {work}"] if work else [])):
            surface.blit(theme.font(13).render(_clip(line, 48), True, theme.TEXT), (x, y))
            y += 19
        if agent.action is not None and agent.action.reason:
            surface.blit(theme.font(12).render(_clip(f"« {agent.action.reason} »", 54), True,
                                               theme.TEXT_DIM), (x, y))
            y += 18
        y += 6
        if agent.dead:
            when = SimClock(); when.total_minutes = agent.died_minute or 0
            surface.blit(theme.font(13).render(f"Décès : {when.label()}", True, (200, 120, 120)), (x, y))
            return y + 26
        bar_w = self.rect.width - 120
        rows = [("Santé", agent.health)] + [(NEED_LABELS[n], v) for n, v in agent.needs.as_dict().items()]
        for label, value in rows:
            surface.blit(theme.font(13, bold=label == "Santé").render(label, True, theme.TEXT_DIM), (x, y))
            bar = pygame.Rect(x + 80, y + 4, bar_w, 11)
            pygame.draw.rect(surface, (70, 70, 84), bar, border_radius=4)
            fill = bar.copy()
            fill.width = int(bar_w * value / 100)
            pygame.draw.rect(surface, _need_color(value), fill, border_radius=4)
            y += 20
        return y + 6

    def _draw_mind(self, surface: pygame.Surface, x: int, y: int, agent: Agent, clock: SimClock) -> int:
        """Intention et plan du jour, objectif, dernier constat de réflexion."""
        font = theme.font(12)
        width = self.rect.width - 28
        plan = agent.plan if agent.plan is not None and agent.plan.day == clock.day else None
        if plan is None and agent.goal is None and not agent.memory.beliefs:
            return y
        surface.blit(theme.font(14, bold=True).render("Plan du jour", True, theme.TEXT), (x, y))
        y += 20
        if plan is None:
            surface.blit(font.render("Pas encore de plan.", True, theme.TEXT_DIM), (x, y))
            y += 16
        else:
            if plan.intention:
                for line in wrap_text(f"« {plan.intention} »", font, width)[:2]:
                    surface.blit(font.render(line, True, theme.ACCENT), (x, y))
                    y += 15
            due = plan.due(clock.minute_of_day)
            for item in plan.items[:MAX_PLAN_LINES]:
                names = {a.id: a.name for a in self.agents}
                target = names.get(item.target, item.target) if item.target else None
                color = {"done": PLAN_DONE, "missed": PLAN_MISSED}.get(item.status, theme.TEXT_DIM)
                if item is due:
                    color = theme.TEXT
                pygame.draw.circle(surface, color, (x + 4, y + 8), 3)
                text = _clip(f"{item.hhmm} {action_label(item.action, target)}", 46)
                surface.blit(font.render(text, True, color), (x + 12, y))
                y += 16
        if agent.goal is not None and clock.total_minutes < agent.goal.until:
            for line in wrap_text(f"Objectif : {agent.goal.text}", font, width)[:2]:
                surface.blit(font.render(line, True, theme.TEXT_DIM), (x, y))
                y += 15
        if agent.memory.beliefs:
            for line in wrap_text(f"Pense : {agent.memory.beliefs[-1].text}", font, width)[:2]:
                surface.blit(font.render(line, True, PLAN_THOUGHT), (x, y))
                y += 15
        return y + 8

    def _draw_relations(self, surface: pygame.Surface, x: int, y: int, agent: Agent,
                        agents: list[Agent]) -> int:
        """Ressenti envers chacun : proximité et tension (rouge quand ça accroche)."""
        others = [a for a in agents if a is not agent and not a.dead]
        if not others:
            return y
        surface.blit(theme.font(14, bold=True).render("Relations", True, theme.TEXT), (x, y))
        y += 20
        font = theme.font(12)
        for other in others:
            relation = agent.relation(other.id)
            if relation.tension >= 45:
                color = PLAN_MISSED
            elif relation.tension >= 25:
                color = (230, 180, 70)
            else:
                color = theme.TEXT_DIM
            pygame.draw.circle(surface, other.persona.color, (x + 4, y + 8), 4)
            text = f"{other.name} : {relation.closeness}, {relation.mood}"
            text += f"  ({relation.affection:.0f} / {relation.tension:.0f})"
            surface.blit(font.render(_clip(text, 50), True, color), (x + 12, y))
            y += 16
        return y + 8

    def _draw_promises(self, surface: pygame.Surface, x: int, y: int, promises: list[str],
                       title: str = "Promesses", color: tuple[int, int, int] = theme.ACCENT) -> int:
        surface.blit(theme.font(14, bold=True).render(title, True, theme.TEXT), (x, y))
        y += 20
        font = theme.font(12)
        for text in promises[:9]:
            for line in wrap_text(text, font, self.rect.width - 28)[:2]:
                surface.blit(font.render(line, True, color), (x, y))
                y += 15
        return y + 4

    def _draw_memory(self, surface: pygame.Surface, x: int, y: int, agent: Agent, bottom: int) -> None:
        """Résumé puis souvenirs du plus récent au plus ancien, tant qu'il reste de la place."""
        font = theme.font(12)
        line_h = font.get_linesize()
        width = self.rect.width - 28
        surface.blit(theme.font(14, bold=True).render("Mémoire", True, theme.TEXT), (x, y))
        y += 22
        blocks: list[tuple[str, tuple[int, int, int]]] = []
        if agent.memory.latest_summary:
            blocks.append((f"Résumé : {agent.memory.latest_summary}", theme.ACCENT))
        blocks += [(event.formatted(), theme.TEXT_DIM) for event in reversed(agent.memory.events)]
        if not blocks:
            blocks.append(("Aucun souvenir pour l'instant.", theme.TEXT_DIM))
        for text, color in blocks:
            lines = wrap_text(text, font, width)[:3]
            if y + line_h * len(lines) > bottom:
                break
            for line in lines:
                surface.blit(font.render(line, True, color), (x, y))
                y += line_h
            y += 3


def _need_color(value: float) -> tuple[int, int, int]:
    if value < 25:
        return (220, 70, 60)
    if value < 50:
        return (230, 170, 60)
    return (90, 190, 110)


def draw_game_over(surface: pygame.Surface, rect: pygame.Rect, clock: SimClock) -> None:
    """Voile sombre sur la carte quand plus personne n'est en vie."""
    veil = pygame.Surface(rect.size, pygame.SRCALPHA)
    veil.fill((8, 8, 12, 200))
    surface.blit(veil, rect.topleft)
    lines = [
        (theme.font(30, bold=True), "La famille n'a pas survécu", theme.TEXT),
        (theme.font(18), f"Jours tenus : {clock.day + 1}  —  fin le {clock.label()}", theme.TEXT_DIM),
        (theme.font(15), "Échap pour quitter ; relancer avec --nouveau pour une nouvelle partie", theme.TEXT_DIM),
    ]
    y = rect.centery - 60
    for font, text, color in lines:
        image = font.render(text, True, color)
        surface.blit(image, image.get_rect(midtop=(rect.centerx, y)))
        y += image.get_height() + 14


def _money(amount: float) -> str:
    """1234.5 -> « 1 235 $ » ; -80 -> « -80 $ »."""
    return f"{amount:,.0f} $".replace(",", " ")


def _clip(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"
