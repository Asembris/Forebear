"""Run the frozen Phase 3 evaluation on a private copy of the shipped graph."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forebear.agent import load_env  # noqa: E402
from forebear.config import use_raw_cache  # noqa: E402
from forebear.graph import open_graph  # noqa: E402
from forebear.investigation import runner, store  # noqa: E402
from forebear.investigation.llm import DEFAULT_MODELS, ChatClient, LLMUnavailable  # noqa: E402


EVAL = ROOT / "eval" / "agent"
GRAPH = ROOT / "data" / "forebear.rl"
MODEL = DEFAULT_MODELS[0]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


@dataclass
class InferenceLimit:
    max_requests: int = 180
    max_requested_output: int = 216_000
    max_total: int = 1_800_000
    interval: float = 4.0
    attempts: list[dict] = field(default_factory=list)
    requested_output: int = 0
    accounted: int = 0
    next_start: float = 0
    stop: str | None = None

    def reserve(self, messages: list[dict], tools: list[dict], output: int, deadline: float | None) -> dict:
        # UTF-8 bytes conservatively bound ordinary tokenizer input plus an allowance for the provider template.
        payload = json.dumps([messages, tools], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reservation = len(payload) + 2048 + output
        if self.stop:
            raise LLMUnavailable(self.stop)
        if (len(self.attempts) >= self.max_requests or self.requested_output + output > self.max_requested_output
                or self.accounted + reservation > self.max_total):
            self.stop = "session inference budget exhausted"
            raise LLMUnavailable(self.stop)
        wait = max(0.0, self.next_start - time.monotonic())
        if deadline is not None and time.time() + wait + 10 >= deadline:
            raise TimeoutError("run deadline leaves no time for a paced request")
        time.sleep(wait)
        self.next_start = time.monotonic() + self.interval
        attempt = {"requested_output": output, "reserved_tokens": reservation,
                   "pace_seconds": round(wait, 3)}
        self.attempts.append(attempt)
        self.requested_output += output
        self.accounted += reservation
        return attempt


class EvaluationClient(ChatClient):
    """Instrument actual SDK attempts, including the shipped client's length retry."""

    limit: InferenceLimit

    def _once(self, model, messages, tools, max_tokens, deadline):
        attempt = self.limit.reserve(messages, tools, max_tokens, deadline)
        started = time.monotonic()
        try:
            response, choice, calls = super()._once(model, messages, tools, max_tokens, deadline)
        except Exception as error:
            status = getattr(error, "status_code", None)
            kind = type(error).__name__
            attempt.update(error=kind, http_status=status)
            if status in (401, 402, 403, 404, 429) or kind in ("APIConnectionError", "APITimeoutError"):
                self.limit.stop = f"NVIDIA {kind}" + (f" (HTTP {status})" if status else "")
            # Do not retain provider response bodies, credentials, or request headers.
            raise LLMUnavailable(self.limit.stop or f"NVIDIA {kind} (HTTP {status})") from None
        finally:
            attempt["seconds"] = round(time.monotonic() - started, 3)
        usage = getattr(response, "usage", None)
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        attempt.update(prompt_tokens=prompt, completion_tokens=completion, finish_reason=choice.finish_reason)
        if prompt is not None and completion is not None:
            self.limit.accounted += prompt + completion - attempt["reserved_tokens"]
        if self.limit.accounted > self.limit.max_total:
            self.limit.stop = "provider-reported usage exceeded the session admission estimate"
        return response, choice, calls


def execute(graph, case: dict, frozen: dict, mode: str, limit: InferenceLimit, path: Path) -> dict:
    k = case["k"]
    result = {"k": k, "status": "unattempted"}
    if limit.stop:
        return result | {"error": limit.stop}
    client = None
    if mode == "llm":
        try:
            client = EvaluationClient.from_env([MODEL], timeout=45.0)
        except LLMUnavailable:
            limit.stop = "NVIDIA credentials or base URL absent"
            return result | {"error": limit.stop}
        client.limit = limit
    inv = {"id": store.new_id("I"), "request": frozen["request"].format(k=k), "target_k": k,
           "depth": frozen["depth"], "mode": mode, "agent_version": runner.AGENT_VERSION,
           "models": [MODEL] if client else []}
    trace = []

    def on_event(kind, data):
        if kind in ("turn", "tool"):
            trace.append({"kind": kind, **data})

    offset = len(limit.attempts)
    started = time.monotonic()
    try:
        store.create(graph, inv)
        report = runner.run(lambda fn: fn(graph), inv, client=client, on_event=on_event)
        result.update(status=report["status"], report=report)
    except LLMUnavailable as error:
        result.update(status="failed", error=str(error))
    finally:
        result.update(seconds=round(time.monotonic() - started, 3), attempts=limit.attempts[offset:])
        write_json(path, result | {"trace": trace})
        if client:
            client._client.close()
    return result


def evaluate(out: Path, mode: str) -> None:
    frozen = json.loads((EVAL / "cases.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=False)
    copy = out / "graph.rl"
    shutil.copyfile(GRAPH, copy)
    if sha256(copy) != frozen["graph_sha256"]:
        raise SystemExit("Snapshot differs from the frozen graph.")
    use_raw_cache(offline=True)
    limit = InferenceLimit()
    if mode == "llm":
        load_env()
        endpoint = urlsplit(os.environ.get("NVIDIA_BASE_URL", ""))
        if (endpoint.scheme, endpoint.netloc, endpoint.path.rstrip("/"), endpoint.query, endpoint.fragment) != (
            "https", "integrate.api.nvidia.com", "/v1", "", ""
        ):
            raise SystemExit("Live evaluation requires NVIDIA's official integrate.api.nvidia.com/v1 endpoint.")
    write_json(out / "run.json", {
        "mode": mode, "model": MODEL if mode == "llm" else None,
        "graph_sha256": frozen["graph_sha256"],
        "cases_sha256": hashlib.sha256((EVAL / "cases.json").read_text(encoding="utf-8").encode()).hexdigest(),
        "protocol_sha256": hashlib.sha256((EVAL / "PROTOCOL.md").read_text(encoding="utf-8").encode()).hexdigest(),
        "budget": vars(limit).copy() if mode == "llm" else None,
    })
    graph = open_graph(copy)
    try:
        for case in frozen["cases"]:
            path = out / f"{case['k']}.json"
            result = execute(graph, case, frozen, mode, limit, path)
            if result["status"] == "unattempted":
                write_json(path, result)
            print(case["k"], result["status"], result.get("seconds", ""), result.get("error", ""), flush=True)
    finally:
        graph.close()
        if sha256(GRAPH) != frozen["graph_sha256"]:
            raise RuntimeError("Shipped graph changed during evaluation")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["deterministic", "llm"], required=True)
    parser.add_argument("--out", type=Path, required=True, help="new output directory, preferably under data/live")
    args = parser.parse_args()
    evaluate(args.out, args.mode)


if __name__ == "__main__":
    main()
