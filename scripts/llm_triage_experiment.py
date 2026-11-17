"""Bounded experiment: does the optional NVIDIA-hosted LLM triage help on difficult citation evidence?

    python scripts/llm_triage_experiment.py [--max 30]

Runs forebear.agent.triage_citation (the same quote-checked call the app's "Ask AI to label" uses) on the
labelled evaluation items (eval/extraction_eval_labels.json) whose deterministic outcome the audit found
hardest: the old_only/new_only strata and any item labelled 'unclear' or 'not_predicate'. It compares
the LLM label with the audit label and writes eval/llm_triage_experiment.json.

Nothing is written to the graph and the LLM output decides nothing; the key is read from .env by
agent.load_env() and never printed. At most --max calls are made (default 30), one model fallback each.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forebear import agent  # noqa: E402

EVAL = ROOT / "eval"


def main(max_calls: int) -> dict:
    agent.load_env()
    if not (os.environ.get("NVIDIA_API_KEY") and os.environ.get("NVIDIA_BASE_URL")):
        out = {"ran": False, "reason": "NVIDIA_API_KEY/NVIDIA_BASE_URL not configured"}
        print(json.dumps(out))
        return out
    sample = {(i["src"], i["dst"]): i for i in
              json.loads((EVAL / "extraction_eval_sample.json").read_text(encoding="utf-8"))["items"]}
    labels = json.loads((EVAL / "extraction_eval_labels.json").read_text(encoding="utf-8"))["labels"]
    hard = [x for x in labels if sample[(x["src"], x["dst"])]["stratum"] in ("old_only", "new_only")
            or x["label"] in ("unclear", "not_predicate")]
    hard = sorted(hard, key=lambda x: (x["src"], x["dst"]))[:max_calls]
    rows, t0 = [], time.time()
    for x in hard:
        ctx = sample[(x["src"], x["dst"])]["context"]
        r = agent.triage_citation(x["src"], x["dst"], ctx[-700:])
        llm = r.get("label") if r.get("ok") else None
        rows.append({"src": x["src"], "dst": x["dst"], "audit_label": x["label"], "llm_label": llm,
                     "llm_model": r.get("model"), "llm_error": None if r.get("ok") else r.get("error")})
    answered = [r for r in rows if r["llm_label"]]
    def agrees(r):
        return (r["llm_label"] == "predicate") == (r["audit_label"] == "predicate")
    decided = [r for r in answered if r["audit_label"] != "unclear"]
    out = {"ran": True, "calls": len(rows), "answered": len(answered), "seconds": round(time.time() - t0, 1),
           "agreement_on_decided": f"{sum(agrees(r) for r in decided)}/{len(decided)}",
           "llm_said_predicate_where_audit_said_not": [f"{r['src']}->{r['dst']}" for r in decided
                                                       if r["llm_label"] == "predicate"
                                                       and r["audit_label"] != "predicate"],
           "llm_said_not_where_audit_said_predicate": [f"{r['src']}->{r['dst']}" for r in decided
                                                       if r["llm_label"] != "predicate"
                                                       and r["audit_label"] == "predicate"],
           "rows": rows}
    (EVAL / "llm_triage_experiment.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=30)
    main(ap.parse_args().max)
