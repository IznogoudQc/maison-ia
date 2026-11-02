"""Fournisseur Claude (SDK anthropic)."""

from __future__ import annotations

import os

import anthropic

from llm.provider import LLMError, LLMProvider, LLMRequest, LLMResponse


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, model: str, effort: str = "low", timeout_s: float = 30.0) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY absente : copier .env.example vers .env et la remplir")
        self.model = model
        self.effort = effort
        # Une seule relance SDK : notre service gère déjà retry + repli
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=1)

    def complete(self, request: LLMRequest) -> LLMResponse:
        content: str | list[dict] = request.prompt
        if request.prefix:
            # Point de cache à la fin de la partie stable : consignes (system) + fiche + famille + monde
            content = [{"type": "text", "text": request.prefix, "cache_control": {"type": "ephemeral"}},
                       {"type": "text", "text": request.prompt}]
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                system=request.system,
                output_config={"effort": self.effort},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("Clé API Claude invalide") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Limite de débit Claude atteinte") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Erreur API Claude {exc.status_code} : {exc.message}") from exc
        except anthropic.APIConnectionError as exc:  # inclut APITimeoutError
            raise LLMError(f"Connexion à l'API Claude impossible : {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("Requête refusée par le modèle")
        # La réflexion adaptative peut produire des blocs « thinking » : on ne garde que le texte
        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        return LLMResponse(text=text, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                           cache_read_tokens=usage.cache_read_input_tokens or 0,
                           cache_write_tokens=usage.cache_creation_input_tokens or 0)
