"""Interface abstraite des fournisseurs LLM et factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sim.config import LLMConfig

RequestKind = Literal["decision", "dialogue", "summary", "plan", "reflection", "line", "debrief", "house_plan", "baby_talk", "birth",
                      "event_story", "portrait", "interview"]


class LLMRequest(BaseModel):
    kind: RequestKind
    system: str
    prompt: str
    # Début du message qui ne change presque jamais (fiche, famille, règles du monde) : Claude le met en
    # cache et le facture environ 10 fois moins cher aux appels suivants. Le reste (prompt) varie.
    prefix: str = ""
    max_tokens: int = 1500
    # Données structurées du contexte : ignorées par les vrais fournisseurs,
    # utilisées par le mock pour fabriquer une réponse plausible.
    meta: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    text: str
    input_tokens: int = 0          # tokens d'entrée hors cache
    output_tokens: int = 0
    cache_read_tokens: int = 0     # lus dans le cache (environ 0,1 fois le prix)
    cache_write_tokens: int = 0    # écrits dans le cache (environ 1,25 fois le prix)


class LLMError(Exception):
    """Échec d'appel (réseau, quota, refus, configuration)."""


class LLMProvider(ABC):
    name: str = "abstract"
    model: str = ""

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Appel bloquant ; exécuté hors du fil pygame par LLMService."""

    def label(self) -> str:
        return f"{self.name} ({self.model})" if self.model else self.name


def create_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "mock":
        from llm.mock_provider import MockProvider

        return MockProvider(config.mock_latency_s, config.mock_invalid_rate)
    if config.provider == "claude":
        from llm.claude_provider import ClaudeProvider

        return ClaudeProvider(config.claude_model, config.claude_effort, config.timeout_s)
    if config.provider == "ollama":
        from llm.ollama_provider import OllamaProvider

        return OllamaProvider(config.ollama_url, config.ollama_model, config.timeout_s)
    raise LLMError(f"Fournisseur LLM inconnu : {config.provider}")
