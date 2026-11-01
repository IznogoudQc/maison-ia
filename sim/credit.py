"""Crédit : financer un véhicule, un objet cher ou les matériaux d'une pièce, et rembourser chaque vendredi.

Le moteur propose « financer » quand un achat est trop cher comptant mais que la mise de fonds passe et
que le prêteur accepte (paiements sous 35 % du revenu, dossier correct). L'IA décide si la famille
s'endette. Paiement manqué : frais de retard et dossier en baisse ; trois retards sur un véhicule, la
banque le reprend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents.actions import Option
from sim.economy import Loan

if TYPE_CHECKING:
    from agents.agent import Agent
    from sim.engine import Engine

RATES = {"vehicule": 0.06, "chantier": 0.08, "objet": 0.19}      # taux annuels de base
DOWN = {"vehicule": 0.15, "chantier": 0.10, "objet": 0.20}       # mise de fonds minimale
WEEKS = {"vehicule": 104, "chantier": 52, "objet": 26}
MAX_DEBT_RATIO = 0.35        # paiements de prêts / revenu hebdomadaire
MIN_SCORE = 560              # sous ce dossier, la banque refuse
MIN_FINANCED = 1500.0        # on ne finance pas les petits achats
LATE_FEE = 25.0
REPOSSESS_AFTER = 3


def weekly_payment(principal: float, annual_rate: float, weeks: int) -> float:
    """Paiement constant (amortissement) d'un prêt remboursé chaque semaine."""
    r = annual_rate / 52
    if r == 0:
        return round(principal / weeks, 2)
    return round(principal * r / (1 - (1 + r) ** -weeks), 2)


class Credit:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @property
    def household(self):
        return self.engine.economy.household

    @property
    def loans(self) -> list[Loan]:
        return self.household.loans

    # ------------------------------------------------------------------ prêteur

    def rate_for(self, purpose: str) -> float:
        """Taux de base, plus cher avec un dossier faible."""
        return round(RATES[purpose] + max(0, 720 - self.household.credit_score) * 0.0002, 4)

    def weekly_income(self) -> float:
        now = self.engine.clock.total_minutes
        return sum(a.persona.salary_per_day * 5 for a in self.engine.agents
                   if not a.dead and a.persona.salary_per_day > 0
                   and (a.unemployed_until is None or now >= a.unemployed_until))

    def check(self, purpose: str, price: float) -> tuple[bool, str, float, float]:
        """(accepté, raison du refus, mise de fonds, paiement hebdomadaire)."""
        down = round(price * DOWN[purpose], -1)
        payment = weekly_payment(price - down, self.rate_for(purpose), WEEKS[purpose])
        if self.household.credit_score < MIN_SCORE:
            return False, "dossier de crédit trop faible", down, payment
        current = sum(loan.payment for loan in self.loans)
        if current + payment > MAX_DEBT_RATIO * self.weekly_income():
            return False, "paiements trop lourds pour le revenu", down, payment
        budget = self.household.money - self.engine.economy.reserve(self.engine.alive_count()) / 2
        if down > budget:
            return False, "pas assez pour la mise de fonds", down, payment
        return True, "", down, payment

    # ------------------------------------------------------------------ options

    def options_for(self, agent: Agent) -> list[Option]:
        engine = self.engine
        if not engine.economy.enabled or not agent.persona.is_adult:
            return []
        cash = self.household.money - engine.economy.reserve(engine.alive_count())
        options: list[Option] = []
        for purpose, ref, label, price in self._financeable(cash):
            ok, _reason, down, payment = self.check(purpose, price)
            if not ok:
                continue
            weeks = WEEKS[purpose]
            total = down + payment * weeks
            text = (f"{label} à crédit : {down:.0f} $ comptant, puis {payment:.0f} $/semaine pendant {weeks} semaines "
                    f"(taux {self.rate_for(purpose) * 100:.1f} %, coût total {total:,.0f} $)").replace(",", " ")
            score = 3.0 if purpose == "objet" else 6.0  # s'endetter pour un spa reste une mauvaise idée
            options.append(Option(action="emprunter", target=f"{purpose}|{ref}", label=text, score=score))
        for loan in self.loans:
            if cash > loan.balance * 1.2:
                options.append(Option(action="rembourser", target=str(loan.uid), score=7.0,
                                      label=f"rembourse le prêt de {loan.label} ({loan.balance:.0f} $ d'un coup)"))
        return options[:3]

    def _financeable(self, cash: float, limit: int | None = 2) -> list[tuple[str, str, str, float]]:
        """Achats utiles trop chers comptant : (but, référence, libellé, prix) ; les moins chers d'abord."""
        engine = self.engine
        out = []
        garage = engine.garage
        household = self.household
        if len(garage.owned) < 3 and engine.clock.day - household.last_vehicle_day >= 7:
            owned = {v.model for v in garage.owned}
            cars = [garage.model(v) for v in garage.owned if garage.model(v).epicerie]
            people = sum(1 for a in engine.agents if not a.dead)
            for model in garage.models.values():
                if model.id in owned or model.prix < MIN_FINANCED or model.prix <= cash:
                    continue
                if model.terrain and not engine.house.layout.wild:
                    continue
                # On ne s'endette que pour l'utile : une première auto, plus de places, la camionnette du chantier
                first_car = model.epicerie and not cars and model.places <= 4
                more_seats = model.places >= 5 and cars and people > max(c.places for c in cars)
                site_truck = model.materiaux > 0 and engine.architect.site_room() is not None
                if first_car or more_seats or site_truck:
                    out.append(("vehicule", model.id, f"achète {model.label}", model.prix))
        site = engine.architect.site_room() if engine.architect.active else None
        if site is not None and not site.materials_paid and not site.contractor:
            price = engine.architect.materials_price(site)
            if not engine.architect.can_afford_materials(site):
                out.append(("chantier", site.id, f"paie les matériaux ({site.name.lower()})", price))
        owned_items = {o.item_id for o in household.items}
        for item in engine.inventory.catalogue.values():
            if item.id in owned_items or item.prix < MIN_FINANCED or item.prix <= cash:
                continue
            if not item.effet:
                continue  # à crédit, seulement ce qui fait économiser (panneaux solaires), pas un piano
            if engine.inventory._rooms_for(item):
                out.append(("objet", item.id, f"achète {item.label}", item.prix))
        order = {"chantier": 0, "vehicule": 1, "objet": 2}  # la maison, puis l'auto, puis le reste
        out.sort(key=lambda o: (order[o[0]], o[3]))
        return out[:limit] if limit else out

    # ------------------------------------------------------------------ prêt, remboursement

    def borrow(self, agent: Agent, target: str | None) -> Loan | None:
        engine = self.engine
        purpose, ref = ((target or "") + "|").split("|")[:2]
        if purpose not in RATES:
            return None
        found = {(p, r): (label, price) for p, r, label, price in self._financeable(float("-inf"), limit=None)}
        label_price = found.get((purpose, ref))
        if label_price is None:
            return None
        label, price = label_price
        ok, reason, down, payment = self.check(purpose, price)
        if not ok:
            engine.publish("pret", ok=False, text=f"Prêt refusé : {reason}")
            engine.remember(agent, f"La banque a refusé le prêt pour {label.split(' ', 1)[-1]} : {reason}.", 6)
            return None
        principal = round(price - down, 2)
        now = engine.clock.total_minutes
        engine.economy.transaction(now, f"Prêt ({purpose})", principal)
        if not self._purchase(agent, purpose, ref):
            engine.economy.transaction(now, f"Prêt annulé ({purpose})", -principal)  # achat raté : rien n'est dû
            return None
        loan = Loan(uid=self.household.next_loan_uid, purpose=purpose, label=label.split(" ", 1)[-1], target=ref,
                    principal=principal, balance=principal, rate=self.rate_for(purpose),
                    weeks_left=WEEKS[purpose], payment=payment)
        self.household.next_loan_uid += 1
        self.loans.append(loan)
        engine.publish("pret", ok=True, text=f"Prêt accordé : {loan.label}, {payment:.0f} $/semaine")
        for other in engine.agents:
            if other.persona.is_adult and not other.dead:
                engine.remember(other, f"On s'est endettés pour {loan.label} : {payment:.0f} $ par semaine pendant "
                                       f"{loan.weeks_left} semaines.", 7)
        return loan

    def _purchase(self, agent: Agent, purpose: str, ref: str) -> bool:
        engine = self.engine
        if purpose == "vehicule":
            return engine.garage.buy(agent, ref) is not None
        if purpose == "chantier":
            room = engine.architect.plan.room(ref) if engine.architect.plan else None
            if room is None or room.materials_paid:
                return False
            engine.architect.pay_materials(room)
            return True
        item = engine.inventory.catalogue.get(ref)
        rooms = engine.inventory._rooms_for(item) if item else []
        before = len(self.household.items)
        if rooms:
            self.household.last_item_day = -1  # le financement passe avant la limite d'un achat par jour
            engine.inventory.buy(agent, f"{ref}|{rooms[0]}|")
        return len(self.household.items) > before

    def repay(self, agent: Agent, target: str | None) -> None:
        engine = self.engine
        loan = next((l for l in self.loans if str(l.uid) == target), None)
        if loan is None or self.household.money < loan.balance:
            return
        engine.economy.transaction(engine.clock.total_minutes, f"Remboursement : {loan.label}", -loan.balance)
        self.loans.remove(loan)
        self.household.credit_score = min(900, self.household.credit_score + 10)
        engine.publish("pret", ok=True, text=f"Prêt de {loan.label} remboursé d'avance !")
        engine.remember(agent, f"On a fini de payer {loan.label}. Quel soulagement !", 6)

    def charge(self) -> None:
        """Vendredi : chaque prêt prélève son paiement ; sinon frais de retard, puis saisie du véhicule."""
        engine = self.engine
        now = engine.clock.total_minutes
        for loan in list(self.loans):
            if self.household.money >= loan.payment:
                interest = round(loan.balance * loan.rate / 52, 2)
                engine.economy.transaction(now, f"Paiement : {loan.label}", -loan.payment)
                loan.balance = round(max(0.0, loan.balance - (loan.payment - interest)), 2)
                loan.weeks_left -= 1
                loan.missed = 0
                self.household.credit_score = min(900, self.household.credit_score + 3)
                if loan.balance <= 0.5 or loan.weeks_left <= 0:
                    self.loans.remove(loan)
                    self.household.credit_score = min(900, self.household.credit_score + 15)
                    engine.publish("pret", ok=True, text=f"Dernier paiement : {loan.label} est à nous !")
                continue
            loan.missed += 1
            engine.economy.transaction(now, f"Frais de retard : {loan.label}", -LATE_FEE)
            self.household.credit_score = max(300, self.household.credit_score - 40)
            engine.publish("pret_retard", text=f"Paiement manqué : {loan.label} ({loan.missed}/{REPOSSESS_AFTER})")
            for agent in engine.agents:
                if agent.persona.is_adult and not agent.dead:
                    engine.remember(agent, f"On n'a pas pu payer {loan.label} cette semaine. La banque appelle.", 7)
                    agent.needs.apply({"fun": -15})
            if loan.purpose == "vehicule" and loan.missed >= REPOSSESS_AFTER:
                self._repossess(loan)

    def _repossess(self, loan: Loan) -> None:
        engine = self.engine
        vehicle = next((v for v in engine.garage.owned if v.model == loan.target), None)
        if vehicle is not None:
            for agent in engine.agents:
                if agent.vehicle == vehicle.object_id:  # parti avec : il rentre en autobus
                    agent.vehicle, agent.drove = None, False
            engine.house.remove_object(vehicle.object_id)
            engine.garage.owned.remove(vehicle)
        self.loans.remove(loan)
        self.household.credit_score = max(300, self.household.credit_score - 80)
        engine.publish("pret_retard", text=f"La banque a repris {loan.label}.")
        for agent in engine.agents:
            if agent.persona.is_adult and not agent.dead:
                engine.remember(agent, f"La banque a repris {loan.label}. Quelle honte.", 9)

    # ------------------------------------------------------------------ prompts, interface

    def context_line(self) -> str:
        if not self.loans:
            return f"Dossier de crédit : {self.household.credit_score}." if self.engine.economy.enabled else ""
        parts = [f"{l.label} ({l.payment:.0f} $/semaine, {l.weeks_left} semaines, solde {l.balance:.0f} $"
                 + (f", {l.missed} paiement(s) manqué(s)" if l.missed else "") + ")" for l in self.loans]
        return "Prêts : " + " ; ".join(parts) + f". Dossier de crédit : {self.household.credit_score}."

    def hud_lines(self) -> list[str]:
        if not self.loans:
            return []
        weekly = sum(l.payment for l in self.loans)
        return [f"Prêts : {len(self.loans)} · {weekly:.0f} $/sem · dossier {self.household.credit_score}"]
