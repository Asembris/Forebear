"""Two pieces of 'analyst' logic:

1. template_memo(): the due-diligence note. It is deterministic on purpose: in testing,
   an LLM-written memo kept valid identifiers but miscounted recalls (e.g. "three
   design-related" where the graph holds two). A citation guard cannot catch wrong numbers,
   so in a regulatory workflow the note is generated from graph facts only.

2. triage_citation(): an optional LLM pass (NVIDIA-hosted, OpenAI-compatible) that reads
   the snippet around an *ambiguous* K-number mention and labels it predicate / reference /
   other. The label is written to the graph with method="llm:<model>" and the snippet stays
   visible, so a person can confirm or reject it. Nothing is relabelled without evidence text.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MODELS = ["nvidia/nemotron-3.5-lightning-30b-a3b", "mistralai/mistral-large-4-1t-a52b"]


def template_memo(a: dict) -> dict:
    d = a["device"]
    paras = [{"text": f"{a['k']} ({d.get('name')}, {d.get('applicant')}, cleared {d.get('decision_date')}) "
                      f"was assessed to {a['depth']} predicate generations: verdict {a['verdict']}. "
                      f"{a['verdict_reason']}", "cites": [a["k"]]}]
    for s in [s for s in a["signals"] if s["severity"] in ("high", "medium")][:3]:
        recs = [e for e in s["evidence"] if e.get("type") == "recall"]
        rec = next((e for e in recs if e.get("design_related")), recs[0] if recs else None)
        ids = [i for i in (s.get("chain") or [])[-1:]] + ([rec["id"]] if rec else [])
        txt = s["title"].rstrip(".") + (f". For example, {rec.get('classification') or 'unclassified'} recall {rec['id']} "
                            f"({rec.get('root_cause')}, initiated {rec.get('initiated')})." if rec else ".")
        follow_up = (" Resolve the citation role before relying on this route." if s.get("conditional")
                     else " Document how this is addressed in the predicate rationale.")
        paras.append({"text": txt + follow_up, "cites": ids})
    cov = a["coverage"]
    if cov["ancestors_lineage_unknown"] or not cov["candidate_lineage_known"]:
        paras.append({"text": f"Coverage: {cov['ancestors_lineage_unknown']} of {cov['ancestors']} ancestors "
                              f"have unread summaries, so the lineage may be incomplete.", "cites": [a["k"]]})
    return {"headline": f"Predicate check for {a['k']}: {a['verdict'].replace('_', ' ').lower()}",
            "paragraphs": paras, "source": "deterministic (graph facts only)"}


TRIAGE_SYSTEM = (
    "You label one K-number mention in an FDA 510(k) summary. Answer with JSON only: "
    "{\"label\": \"predicate\"|\"reference\"|\"other\", \"quote\": str}. "
    "'predicate' = the submitter claims substantial equivalence to it (primary or secondary predicate). "
    "'reference' = a reference device cited for a specific characteristic. "
    "'other' = anything else (accessory, compatible device, prior version mentioned in history, the "
    "submission's own number, OCR noise). 'quote' must be an exact substring of the snippet that justifies "
    "the label. If unsure, answer 'other'."
)


def triage_citation(src: str, dst: str, snippet: str, timeout: float = 20.0) -> dict:
    key, base = os.environ.get("NVIDIA_API_KEY"), os.environ.get("NVIDIA_BASE_URL")
    if not (key and base):
        return {"ok": False, "error": "no NVIDIA_API_KEY/NVIDIA_BASE_URL configured"}
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=base, timeout=timeout, max_retries=0)
    user = json.dumps({"submission": src, "mentioned_k_number": dst, "snippet": snippet})
    errors = []
    for model in MODELS:
        t0 = time.time()
        try:
            r = client.chat.completions.create(
                model=model, temperature=0, max_tokens=200,
                messages=[{"role": "system", "content": TRIAGE_SYSTEM}, {"role": "user", "content": user}],
                extra_body={"chat_template_kwargs": {"enable_thinking": False}})
            raw = r.choices[0].message.content or ""
            start = raw.find("{")
            out = json.JSONDecoder().raw_decode(raw[start:])[0] if start >= 0 else {}
            label, quote = out.get("label"), str(out.get("quote", ""))
            if label not in ("predicate", "reference", "other"):
                errors.append(f"{model}: invalid label {label!r}")
                continue
            norm = " ".join(snippet.split())
            if not quote or " ".join(quote.split()) not in norm:
                errors.append(f"{model}: quote not found in snippet")
                continue
            return {"ok": True, "label": label, "quote": quote, "model": model,
                    "seconds": round(time.time() - t0, 1)}
        except Exception as e:
            errors.append(f"{model}: {type(e).__name__}")
    return {"ok": False, "error": "; ".join(errors)}


def load_env() -> None:
    """Load ./.env or ../.env (never printed, never written)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parent.parent
    for p in (here / ".env", here.parent / ".env"):
        if p.exists():
            load_dotenv(p, override=False)
