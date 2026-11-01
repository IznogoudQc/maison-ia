"""Retry puis repli du service LLM, limite de débit."""

from llm.prompts import ActionDecision
from llm.provider import LLMError, LLMProvider, LLMRequest, LLMResponse
from llm.service import LLMService, RateLimiter

FALLBACK = ActionDecision(action="flaner", reason="repli")
VALID = '{"action": "tele", "target": null, "reason": "relaxer"}'


class ScriptedProvider(LLMProvider):
    """Renvoie les réponses prévues dans l'ordre ; une Exception est levée telle quelle."""

    name = "test"

    def __init__(self, script):
        self.script = list(script)
        self.prompts: list[str] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.prompts.append(request.prompt)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, input_tokens=10, output_tokens=5)


def request() -> LLMRequest:
    return LLMRequest(kind="decision", system="sys", prompt="choisis")


def run(script, validate=None):
    provider = ScriptedProvider(script)
    service = LLMService(provider, max_calls_per_minute=100, max_workers=1)
    try:
        result = service.run_structured(request(), ActionDecision, FALLBACK, validate)
    finally:
        service.shutdown()
    return result, provider, service


def test_reponse_valide_du_premier_coup():
    result, provider, service = run([VALID])
    assert result.ok and result.attempts == 1
    assert result.value.action == "tele"
    assert service.stats.calls == 1 and service.stats.input_tokens == 10


def test_json_invalide_puis_valide_un_retry():
    result, provider, service = run(["pas du JSON", VALID])
    assert result.ok and result.attempts == 2
    assert "ATTENTION" in provider.prompts[1]  # le retry signale l'erreur au modèle
    assert service.stats.failures == 1 and service.stats.fallbacks == 0


def test_deux_echecs_donnent_le_repli():
    result, _, service = run(["n'importe quoi", '{"oups": 1}'])
    assert not result.ok
    assert result.value == FALLBACK
    assert service.stats.fallbacks == 1
    assert result.error


def test_erreur_fournisseur_donne_le_repli():
    result, _, service = run([LLMError("réseau"), LLMError("réseau")])
    assert not result.ok and result.value == FALLBACK
    assert service.stats.calls == 0


def test_validation_metier_refusee_donne_le_repli():
    def reject(_decision):
        raise ValueError("hors options")
    result, _, _ = run([VALID, VALID], validate=reject)
    assert not result.ok and result.value == FALLBACK


def test_try_submit_asynchrone():
    service = LLMService(ScriptedProvider([VALID]), max_calls_per_minute=10, max_workers=1)
    future = service.try_submit(request(), ActionDecision, FALLBACK)
    assert future is not None
    assert future.result(timeout=5).value.action == "tele"
    service.shutdown()


def test_limite_de_debit_fenetre_glissante():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    assert limiter.try_acquire() and limiter.try_acquire()
    assert not limiter.try_acquire()
    now[0] = 59.9
    assert not limiter.try_acquire()
    now[0] = 60.0
    assert limiter.try_acquire()
    assert limiter.used() == 1


def test_try_submit_refuse_quand_limite_atteinte():
    service = LLMService(ScriptedProvider([VALID]), max_calls_per_minute=1, max_workers=1)
    assert service.try_submit(request(), ActionDecision, FALLBACK) is not None
    assert service.try_submit(request(), ActionDecision, FALLBACK) is None
    service.shutdown()
