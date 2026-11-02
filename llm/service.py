"""Exécution asynchrone des appels LLM : threads, limite de débit, parsing, retry et repli."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

from llm.provider import LLMError, LLMProvider, LLMRequest

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ParseError(ValueError):
    """Réponse LLM inexploitable (JSON invalide ou schéma non respecté)."""


def parse_json_response(text: str, schema: type[T]) -> T:
    """Extrait le premier objet JSON de la réponse et le valide avec le schéma pydantic.

    Tolère les blocs ```json et le texte parasite autour de l'objet.
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ParseError(f"aucun objet JSON trouvé dans : {text[:80]!r}")
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON invalide : {exc}") from exc
    try:
        return schema.model_validate(data)
    except ValueError as exc:  # pydantic.ValidationError hérite de ValueError
        raise ParseError(f"schéma non respecté : {exc}") from exc


@dataclass
class StructuredResult(Generic[T]):
    value: T | None
    ok: bool                 # False = valeur de repli
    attempts: int
    error: str = ""


class RateLimiter:
    """Fenêtre glissante d'appels par minute réelle (thread-safe)."""

    def __init__(self, max_per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_per_minute = max_per_minute
        self.clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= 60.0:
            self._calls.popleft()

    def try_acquire(self) -> bool:
        with self._lock:
            now = self.clock()
            self._purge(now)
            if len(self._calls) >= self.max_per_minute:
                return False
            self._calls.append(now)
            return True

    def used(self) -> int:
        with self._lock:
            self._purge(self.clock())
            return len(self._calls)


class LLMStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.failures = 0     # appels ou parsings ratés (avant retry)
        self.fallbacks = 0    # requêtes terminées sur la valeur de repli

    def record_call(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens

    def cost(self, price_in: float, price_out: float) -> float:
        """Coût en $ selon les tarifs par million de tokens."""
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1

    def record_fallback(self) -> None:
        with self._lock:
            self.fallbacks += 1


class LLMService:
    MAX_ATTEMPTS = 2  # un essai + un retry, puis repli

    def __init__(self, provider: LLMProvider, max_calls_per_minute: int = 12, max_workers: int = 3,
                 prices: tuple[float, float] = (0.0, 0.0)) -> None:
        self.provider = provider
        self.prices = prices  # $ US par million de tokens (entrée, sortie) ; 0 : gratuit (simulé, Ollama)
        self.limiter = RateLimiter(max_calls_per_minute)
        self.stats = LLMStats()
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm")

    def cost(self) -> float:
        """Coût de la partie en $ US (depuis le début, compteurs gardés dans la sauvegarde)."""
        return self.stats.cost(*self.prices)

    def try_submit(self, request: LLMRequest, schema: type[T], fallback: T | None = None,
                   validate: Callable[[T], T] | None = None) -> Future[StructuredResult[T]] | None:
        """Soumet la requête en arrière-plan ; None si la limite par minute est atteinte."""
        if not self.limiter.try_acquire():
            return None
        return self.executor.submit(self.run_structured, request, schema, fallback, validate)

    def run_structured(self, request: LLMRequest, schema: type[T], fallback: T | None = None,
                       validate: Callable[[T], T] | None = None) -> StructuredResult[T]:
        """Appel bloquant avec un retry ; renvoie le repli si les deux essais échouent."""
        errors: list[str] = []
        current = request
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = self.provider.complete(current)
                self.stats.record_call(response.input_tokens, response.output_tokens)
                value = parse_json_response(response.text, schema)
                if validate is not None:
                    value = validate(value)
                return StructuredResult(value=value, ok=True, attempts=attempt)
            except (LLMError, ValueError) as exc:
                self.stats.record_failure()
                errors.append(str(exc))
                current = request.model_copy(update={"prompt": request.prompt + (
                    f"\n\nATTENTION : ta réponse précédente était invalide ({str(exc)[:150]}). "
                    "Réponds uniquement avec l'objet JSON demandé, sans aucun texte autour.")})
        self.stats.record_fallback()
        return StructuredResult(value=fallback, ok=False, attempts=self.MAX_ATTEMPTS,
                                error=" | ".join(errors))

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
