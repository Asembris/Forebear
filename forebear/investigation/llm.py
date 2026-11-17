"""NVIDIA-hosted chat client (OpenAI-compatible) for the investigation agent.

Bounded on purpose: one attempt per model per turn (no SDK retries), a per-request timeout, a max_tokens cap,
and a per-run circuit breaker: a model that times out, errors or returns an unusable reply twice is not called
again in that run, and the next configured model takes over. Model choice is configurable with
FOREBEAR_AGENT_MODELS (comma-separated); the defaults were picked by the probe in docs/INVESTIGATION_AGENT.md.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

# Probed 2026-11-17: both completed multi-turn structured tool calls in ~1 s per turn. minimax-m3.1-flash,
# glm-5.3-flash, gpt-oss-20b and gemma-4-31b timed out at 45 s and are not used.
DEFAULT_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b", "mistralai/mistral-large-4-1t-a52b"]


class LLMUnavailable(Exception):
    pass


@dataclass
class Turn:
    content: str
    tool_calls: list[dict]          # [{"id", "name", "arguments" (raw JSON string)}]
    model: str
    seconds: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ChatClient:
    models: list[str]
    timeout: float = 60.0
    max_tokens: int = 1200
    failures: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    _client: object = None

    @classmethod
    def from_env(cls, models: list[str] | None = None, timeout: float = 90.0) -> "ChatClient":
        key, base = os.environ.get("NVIDIA_API_KEY"), os.environ.get("NVIDIA_BASE_URL")
        if not (key and base):
            raise LLMUnavailable("NVIDIA_API_KEY / NVIDIA_BASE_URL are not configured")
        env_models = [m.strip() for m in os.environ.get("FOREBEAR_AGENT_MODELS", "").split(",") if m.strip()]
        from openai import OpenAI
        c = cls(models=models or env_models or list(DEFAULT_MODELS), timeout=timeout)
        c._client = OpenAI(api_key=key, base_url=base, timeout=timeout, max_retries=0)
        return c

    def usable(self) -> list[str]:
        return [m for m in self.models if self.failures.get(m, 0) < 2]

    def _once(self, model: str, messages: list[dict], tools: list[dict], max_tokens: int, deadline: float | None):
        timeout = self.timeout if deadline is None else min(self.timeout, deadline - time.time())
        if timeout < 10:
            raise TimeoutError("run time budget exhausted before the request")
        r = self._client.with_options(timeout=timeout).chat.completions.create(
            model=model, messages=messages, tools=tools, tool_choice="auto", temperature=0,
            max_tokens=max_tokens, extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        ch = r.choices[0]
        calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments or "{}"}
                 for c in (ch.message.tool_calls or [])]
        return r, ch, calls

    def chat(self, messages: list[dict], tools: list[dict], deadline: float | None = None) -> Turn:
        """One model turn. `deadline` (epoch seconds) caps every request so a run cannot overrun its time budget."""
        for model in self.usable():
            t0 = time.time()
            try:
                r, ch, calls = self._once(model, messages, tools, self.max_tokens, deadline)
                if not calls and not (ch.message.content or "").strip() and ch.finish_reason == "length":
                    # a long tool call (submit_report) cut off by max_tokens: one retry with more room
                    r, ch, calls = self._once(model, messages, tools, self.max_tokens * 3, deadline)
                if not calls and not (ch.message.content or "").strip():
                    raise ValueError(f"empty reply (finish_reason={ch.finish_reason})")
                u = getattr(r, "usage", None)
                return Turn(ch.message.content or "", calls, model, round(time.time() - t0, 2),
                            getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)
            except TimeoutError as e:       # out of run time: no point trying another model
                self.errors.append(f"{model}: {e}")
                break
            except Exception as e:          # timeout, 4xx/5xx, malformed reply: count it, try the next model
                self.failures[model] = self.failures.get(model, 0) + 1
                self.errors.append(f"{model}: {type(e).__name__}: {str(e)[:160]}")
                if type(e).__name__ in ("AuthenticationError", "PermissionDeniedError", "NotFoundError"):
                    self.failures[model] = 2          # broken endpoint for this run: never retried
        raise LLMUnavailable("; ".join(self.errors[-3:]) or "no usable model")
