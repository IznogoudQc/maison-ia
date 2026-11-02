"""Mémoire d'un agent : souvenirs pondérés, mémoire longue, réflexions et résumés.

Le rappel s'inspire de « Generative Agents » : chaque souvenir reçoit un score
fraîcheur + importance + pertinence, et les meilleurs sont envoyés au LLM.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, Field

MINUTES_PER_DAY = 24 * 60
ALWAYS_RECENT = 2  # souvenirs les plus récents toujours rappelés, quel que soit leur score

STOPWORDS = {
    "avec", "pour", "dans", "mais", "plus", "tout", "toute", "tous", "cette", "elle", "elles", "nous",
    "vous", "sont", "faire", "fait", "etre", "etait", "tres", "bien", "comme", "juste", "encore",
    "apres", "avant", "depuis", "quand", "alors", "aussi", "meme", "rien", "quelque", "chose", "leur",
    "leurs", "notre", "votre", "entre", "sans", "sous", "vers", "chez", "parce", "jase", "jaser",
}


# Familles de mots : « budget » et « paie » parlent du même thème ; un souvenir partage alors le thème
# (#argent) avec la situation même sans mot identique. Racines sans accents, comparées au début du mot.
WORD_FAMILIES = {
    "argent": ("argent", "budget", "paie", "payer", "salaire", "pret", "dette", "factur", "banque", "piastre",
               "dollar", "cout", "depens", "econom", "hypothe", "credit", "cheque", "rouge"),
    "nourriture": ("epicer", "bouffe", "manger", "souper", "diner", "dejeun", "frigo", "garde", "portion",
                   "repas", "cuisin", "lait", "pain", "legume", "viande", "collation"),
    "maison": ("maison", "chantier", "chambre", "constru", "buche", "piece", "plancher", "toit", "tente",
               "atelier", "entrepren", "bois"),
    "travail": ("travail", "job", "emploi", "patron", "promotion", "bureau", "collegue", "ouvrage",
                "chomage", "congedi", "embauch", "offre"),
    "ecole": ("ecole", "devoir", "cours", "etude", "diplome", "moyenne", "examen", "cegep", "professeur"),
    "amour": ("amour", "aime", "bisou", "couple", "chicane", "dispute", "pardon", "tendre", "blonde", "chum",
              "calin", "promesse", "promis"),
    "enfants": ("bebe", "enfant", "fils", "fille", "naissance", "enceinte", "garderie", "berceau"),
    "sante": ("malade", "grippe", "hopital", "fatigu", "epuis", "sante", "medecin", "deuil"),
    "loisirs": ("hockey", "film", "tele", "jouer", "console", "piano", "livre", "lire", "baignade", "kayak",
                "chien", "feu", "veill", "fete"),
}


def keywords(text: str) -> set[str]:
    """Mots porteurs de sens (4 lettres et plus, sans accents ni mots outils) et leurs thèmes (#argent...)."""
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    words = {w for w in re.findall(r"[a-z]+", plain) if len(w) >= 3 and w not in STOPWORDS}
    themes = {f"#{family}" for family, roots in WORD_FAMILIES.items()
              if any(w.startswith(root) for w in words for root in roots)}
    return {w for w in words if len(w) >= 4} | themes


class MemoryEvent(BaseModel):
    minute: int   # minute absolue de simulation
    time: str     # « HH:MM » pour l'affichage et les prompts
    text: str
    importance: int = 3       # 1 (banal) à 10 (inoubliable)
    kind: str = "event"       # event, reflection

    def formatted(self) -> str:
        return f"[{self.time}] {self.text}"

    def formatted_at(self, now: int) -> str:
        """Horodatage relatif pour les prompts : « [14:20] », « [hier 14:20] », « [il y a 5 j] »."""
        days = now // MINUTES_PER_DAY - self.minute // MINUTES_PER_DAY
        if days <= 0:
            stamp = self.time
        elif days == 1:
            stamp = f"hier {self.time}"
        else:
            stamp = f"il y a {days} j"
        prefix = "Réflexion : " if self.kind == "reflection" else ""
        return f"[{stamp}] {prefix}{self.text}"


class Belief(BaseModel):
    """Constat tiré d'une réflexion du soir ; reste en tête quelques jours."""
    text: str
    importance: int = 5
    minute: int = 0


class Memory(BaseModel):
    events: list[MemoryEvent] = Field(default_factory=list)       # mémoire courte, chronologique
    long_term: list[MemoryEvent] = Field(default_factory=list)    # souvenirs marquants sortis de la courte
    beliefs: list[Belief] = Field(default_factory=list)
    summaries: list[str] = Field(default_factory=list)
    since_summary: int = 0   # événements ajoutés depuis le dernier résumé
    importance_since_reflection: int = 0   # importance accumulée depuis la dernière réflexion
    last_reflection_minute: int = -1

    def add(self, minute: int, time: str, text: str, max_events: int = 30, importance: int = 3,
            kind: str = "event", keep_from: int = 6, long_term_size: int = 40) -> MemoryEvent:
        event = MemoryEvent(minute=minute, time=time, text=text, importance=importance, kind=kind)
        self.events.append(event)
        if len(self.events) > max_events:
            dropped = self.events[: len(self.events) - max_events]
            del self.events[: len(self.events) - max_events]
            self.long_term += [e for e in dropped if e.importance >= keep_from]
            if len(self.long_term) > long_term_size:
                # On oublie d'abord le moins important, puis le plus ancien
                self.long_term.sort(key=lambda e: (e.importance, e.minute))
                del self.long_term[: len(self.long_term) - long_term_size]
                self.long_term.sort(key=lambda e: e.minute)
        self.since_summary += 1
        if kind != "reflection":
            self.importance_since_reflection += importance
        return event

    def all_events(self) -> list[MemoryEvent]:
        """Mémoire longue et courte, dans l'ordre chronologique."""
        return sorted(self.long_term + self.events, key=lambda e: e.minute)

    def recent(self, count: int = 5) -> list[str]:
        return [event.formatted() for event in self.events[-count:]] if count > 0 else []

    def since(self, minute: int) -> list[MemoryEvent]:
        return [e for e in self.events if e.minute >= minute]

    def retrieve(self, now: int, query: set[str], count: int = 5,
                 half_life_hours: float = 24.0) -> list[MemoryEvent]:
        """Les souvenirs les plus utiles maintenant, dans l'ordre chronologique.

        Score = fraîcheur (demi-vie configurable) + importance / 10 + pertinence (mots en commun
        avec la situation). Les ALWAYS_RECENT derniers souvenirs sont toujours inclus.
        """
        if count <= 0 or not self.events:
            return []
        keep = min(ALWAYS_RECENT, count, len(self.events))
        recent = self.events[-keep:]
        pool = self.long_term + self.events[:-keep]

        def score(event: MemoryEvent) -> float:
            recency = 0.5 ** (max(0, now - event.minute) / 60 / half_life_hours)
            relevance = 0.0
            if query:
                relevance = min(1.0, len(keywords(event.text) & query) / min(3, len(query)))
            return recency + event.importance / 10 + relevance

        best = sorted(pool, key=score, reverse=True)[: count - keep]
        return sorted(best, key=lambda e: e.minute) + recent

    def pending_for_summary(self) -> list[str]:
        """Événements pas encore couverts par un résumé (bornés par la mémoire courte)."""
        return self.recent(min(self.since_summary, len(self.events)))

    @property
    def latest_summary(self) -> str | None:
        return self.summaries[-1] if self.summaries else None

    def add_summary(self, text: str, covered: int, max_summaries: int = 5) -> None:
        self.summaries.append(text)
        if len(self.summaries) > max_summaries:
            del self.summaries[: len(self.summaries) - max_summaries]
        self.since_summary = max(0, self.since_summary - covered)

    def add_belief(self, text: str, importance: int, minute: int, max_beliefs: int = 6) -> None:
        same = next((b for b in self.beliefs if b.text == text), None)
        if same is not None:  # constat déjà fait : il se renforce au lieu de se répéter
            self.beliefs.remove(same)
            importance = max(importance, same.importance)
        self.beliefs.append(Belief(text=text, importance=importance, minute=minute))
        if len(self.beliefs) > max_beliefs:
            # Les constats les moins importants, puis les plus vieux, s'effacent
            self.beliefs.sort(key=lambda b: (b.importance, b.minute))
            del self.beliefs[: len(self.beliefs) - max_beliefs]
            self.beliefs.sort(key=lambda b: b.minute)
