"""Fournisseur Ollama (HTTP local, endpoint /api/chat)."""

from __future__ import annotations

import httpx

from llm.provider import LLMError, LLMProvider, LLMRequest, LLMResponse


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_s: float = 60.0) -> None:
        self.model = model
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s)

    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",  # force une sortie JSON côté Ollama
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": f"{request.prefix}\n\n{request.prompt}" if request.prefix
                 else request.prompt},
            ],
            "options": {"num_predict": request.max_tokens},
        }
        try:
            response = self.client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"Ollama HTTP {exc.response.status_code} : {exc.response.text[:200]}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"Ollama injoignable ({self.client.base_url}) : {exc}") from exc

        text = data.get("message", {}).get("content", "")
        return LLMResponse(text=text, input_tokens=data.get("prompt_eval_count", 0),
                           output_tokens=data.get("eval_count", 0))
