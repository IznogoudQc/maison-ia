"""Interface abstraite des fournisseurs LLM et factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sim.config import LLMConfig

RequestKind = Literal["decision", "dialogue", "summary", "plan", "reflection", "line", "debrief", "house_plan"]


class LLMRequest(BaseModel):
    kind: RequestKind
    system: str
    prompt: str
    max_tokens: int = 1500
    # Données structurées du contexte : ignorées par les vrais fournisseurs,
    # utilisées par le mock pour fabriquer une réponse plausible.
    meta: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


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
