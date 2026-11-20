"""Offline checks of the evaluation's network budget, separate from live measurements."""

from types import SimpleNamespace

import pytest

from forebear.investigation.llm import ChatClient, LLMUnavailable
from scripts.evaluate_agent import EvaluationClient, InferenceLimit


@pytest.mark.parametrize("limit", [
    {"max_requests": 0},
    {"max_requested_output": 1199},
    {"max_total": 1200},
])
def test_inference_cap_refuses_before_sending(limit):
    budget = InferenceLimit(interval=0, **limit)
    with pytest.raises(LLMUnavailable, match="session inference budget"):
        budget.reserve([], [], 1200, None)
    assert budget.attempts == []


def test_length_retry_is_charged_as_a_separate_attempt(monkeypatch):
    choices = iter([
        SimpleNamespace(message=SimpleNamespace(content=""), finish_reason="length"),
        SimpleNamespace(message=SimpleNamespace(content="done"), finish_reason="stop"),
    ])
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=200, completion_tokens=10))
    monkeypatch.setattr(ChatClient, "_once", lambda *args: (response, next(choices), []))
    client = EvaluationClient(models=["test-only"])
    client.limit = InferenceLimit(interval=0, max_requests=2)
    assert client.chat([], []).content == "done"
    assert [attempt["requested_output"] for attempt in client.limit.attempts] == [1200, 3600]
    assert client.limit.accounted == 420
    with pytest.raises(LLMUnavailable, match="session inference budget"):
        client.chat([], [])


def test_rate_limit_stops_the_sweep_and_redacts_provider_body(monkeypatch):
    class RateLimitError(Exception):
        status_code = 429

    def rate_limit(*args):
        raise RateLimitError("provider response body")

    monkeypatch.setattr(ChatClient, "_once", rate_limit)
    budget = InferenceLimit(interval=0)
    client = EvaluationClient(models=["test-only"])
    client.limit = budget
    with pytest.raises(LLMUnavailable, match="HTTP 429") as error:
        client.chat([], [])
    assert "provider response body" not in str(error.value)
    assert len(budget.attempts) == 1
    assert budget.attempts[0]["http_status"] == 429
    assert client.rate_limit_waits == 0
    next_client = EvaluationClient(models=["test-only"])
    next_client.limit = budget
    with pytest.raises(LLMUnavailable, match="HTTP 429"):
        next_client.chat([], [])
    assert len(budget.attempts) == 1
