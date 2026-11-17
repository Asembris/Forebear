"""Pre-merge fixes: tool results are bounded structurally (never cut mid-JSON), the evidence ledger holds only what
the model was shown, and stored traces stay valid, inspectable and hash-faithful for results of any size."""
import hashlib
import json
import re

import pytest

from forebear.graph import open_graph
from forebear.investigation import runner, store
from forebear.investigation import tools as T
from forebear.investigation.tools import (MAX_RESULT_CHARS, Ledger, RunContext, absorb_visible, bound_result,
                                          canonical_json, run_tool, to_message)
from forebear.investigation.verify import verify_finding
from tests.test_investigation import Scripted, start


@pytest.fixture
def real(real_copy):
    g = open_graph(real_copy)
    yield g
    g.close()


def body(msg: str):
    """Parse the JSON part of a model-visible tool message (raises if it is not valid JSON)."""
    return json.loads(msg.split("\n", 1)[1])


def big(n_items=400, text=120):
    return {"k": "K252078", "verdict": "REVIEW_LINEAGE", "coverage": {"evidence": "partial"},
            "ancestors": [{"k": f"K{100000 + i:06d}", "gen": 1 + i % 4, "chain": ["K252078", f"K{100000 + i:06d}"],
                           "recall_ids": [f"Z-{1000 + i:04d}-2021"], "name": "x" * text} for i in range(n_items)],
            "total_ancestors": n_items}


# ------------------------------------------------------------------ bounding
@pytest.mark.parametrize("limit", [1200, 3000, MAX_RESULT_CHARS, 20000])
def test_bounded_result_is_valid_json_within_limit_and_discloses(limit):
    obj = big()
    shown, omitted = bound_result(obj, limit)
    text = canonical_json(shown)
    assert len(text) <= limit and json.loads(text) == shown
    assert shown["k"] == "K252078" and shown["verdict"] == "REVIEW_LINEAGE" and shown["coverage"]
    assert omitted and omitted[0]["path"] == "ancestors" and omitted[0]["total"] == 400
    assert shown["_truncated"]["omitted_lists"][0]["shown"] == len(shown["ancestors"]) < 400
    assert shown["_omitted_items"]["ancestors"] == {"shown": len(shown["ancestors"]), "total": 400}
    assert obj["total_ancestors"] == 400 and len(obj["ancestors"]) == 400          # the input is not mutated


def test_truncation_boundary_exactly_at_and_one_over_the_limit():
    obj = {"k": "K252078", "items": ["a" * 10] * 50}
    exact = len(canonical_json(obj))
    assert bound_result(obj, exact) == (obj, [])                              # fits: returned unchanged
    shown, omitted = bound_result(obj, exact - 1)                             # one over: shortened, valid, disclosed
    assert omitted and len(canonical_json(shown)) <= exact - 1 and "_truncated" in shown


def test_nested_lists_huge_strings_and_non_dicts_stay_valid():
    nested = {"k": "K252078", "signals": [{"code": "ANCESTOR_RECALL", "chain": ["K252078", "K113053"],
                                           "recall_ids": [f"Z-{i:04d}-2021" for i in range(300)]}] * 5,
              "untrusted_reason": "y" * 50000}
    shown, _ = bound_result(nested, 4000)
    assert len(canonical_json(shown)) <= 4000 and json.loads(canonical_json(shown))
    assert shown["signals"][0]["chain"] == ["K252078", "K113053"]              # small structural lists kept whole
    shown, _ = bound_result(["x" * 100] * 500, 2000)                          # a bare list
    assert len(canonical_json(shown)) <= 2000 and shown["_truncated"]
    hopeless = {"k": "K252078", "blob": "z" * 100000, "more": {"deep": "w" * 100000}}
    shown, omitted = bound_result(hopeless, 1500)
    assert len(canonical_json(shown)) <= 1500 and shown["k"] == "K252078"


def test_to_message_never_cuts_json(monkeypatch):
    msg = to_message(big(2000, 300))                                           # far beyond the limit
    data = body(msg)
    assert data["_truncated"]["omitted_lists"] and len(msg) < MAX_RESULT_CHARS + 200


# ------------------------------------------------------------------ the visible-evidence ledger
def test_ledger_holds_only_what_the_model_saw():
    full = big(400)
    del full["total_ancestors"]                     # so "400" appears only in the disclosure metadata
    shown, _ = bound_result(full, 3000)
    led = Ledger()
    absorb_visible(led, "trace_ancestry", shown)
    visible = {a["k"] for a in shown["ancestors"]}
    hidden = {a["k"] for a in full["ancestors"]} - visible
    assert visible <= set(led.devices) and not hidden & set(led.devices)
    hidden_recall = next(a["recall_ids"][0] for a in full["ancestors"] if a["k"] in hidden)
    assert hidden_recall not in led.recalls and not any(k in hidden for k in led.recall_links.get(hidden_recall, ()))
    assert "400" not in led.numbers                                           # the disclosed total is metadata, not evidence


def test_check_predicate_no_longer_leaks_unshown_ancestors(real):
    ctx = RunContext("I-x", "K252078")
    ok, shown = run_tool(real, "check_predicate", {"k_number": "K252078", "generations": 4}, ctx)
    text = canonical_json(shown)
    all_ancestors = {a["k"] for a in real.ancestors("K252078", 4)}
    unseen = {k for k in all_ancestors if k not in text}
    assert unseen and not unseen & set(ctx.ledger.devices)
    # and a finding about an ancestor the model never saw is rejected, even though the graph would confirm it
    k = sorted(unseen)[0]
    v = verify_finding({"claim": f"{k} is an ancestor of K252078.", "evidence": [k]}, ctx.ledger, {})
    assert v["status"] == "rejected" and "not returned by any tool" in v["reasons"][0]


def test_oversized_tool_result_hides_its_tail_from_verification(real, monkeypatch):
    """With a small limit, ancestors cut from trace_ancestry cannot support findings; shown ones can."""
    monkeypatch.setattr(T, "MAX_RESULT_CHARS", 2500)
    ctx = RunContext("I-x", "K252078")
    ok, shown = run_tool(real, "trace_ancestry", {"k_number": "K252078", "generations": 6}, ctx)
    assert ok and len(canonical_json(shown)) <= 2500 and ctx.last_omitted
    full_ks = [a["k"] for a in ctx.last_full["ancestors"]]
    shown_ks = [a["k"] for a in shown["ancestors"]]
    hidden = [k for k in full_ks if k not in canonical_json(shown)]
    assert len(full_ks) > len(shown_ks) and hidden
    ok_f = verify_finding({"claim": f"{shown_ks[0]} is in the ancestry of K252078.", "evidence": [shown_ks[0]]},
                          ctx.ledger, {})
    bad_f = verify_finding({"claim": f"{hidden[0]} is in the ancestry of K252078.", "evidence": [hidden[0]]},
                           ctx.ledger, {})
    assert ok_f["status"] == "verified" and bad_f["status"] == "rejected"


def test_numbers_only_from_shown_results(real, monkeypatch):
    monkeypatch.setattr(T, "MAX_RESULT_CHARS", 2500)
    ctx = RunContext("I-x", "K252078")
    run_tool(real, "trace_ancestry", {"k_number": "K252078", "generations": 6}, ctx)
    led = Ledger()
    T.Ledger.absorb_numbers(led, {k: v for k, v in ctx.last_full.items()})
    assert ctx.ledger.numbers < led.numbers                                    # strictly fewer than the full result


# ------------------------------------------------------------------ the runner and the store
def test_run_with_oversized_results_sends_valid_json_and_rejects_unseen_evidence(real, monkeypatch):
    monkeypatch.setattr(T, "MAX_RESULT_CHARS", 2500)
    seen_messages = []

    def policy(turn, messages):
        seen_messages[:] = [m["content"] for m in messages if m["role"] == "tool"]
        if turn == 1:
            return [("trace_ancestry", {"k_number": "K252078", "generations": 6}),
                    ("check_predicate", {"k_number": "K252078", "generations": 6})]
        shown = body(seen_messages[0])
        visible = shown["ancestors"][0]["k"]
        hidden = next(k for k in ("K970839", "K981072", "K060705", "K091319", "K003068")
                      if k not in " ".join(seen_messages))
        return [("submit_report", {"summary": "s", "findings": [
            {"claim": f"{visible} is in K252078's ancestry.", "evidence": [visible]},
            {"claim": f"{hidden} is in K252078's ancestry.", "evidence": [hidden]}]})]
    inv = start(real, "K252078", depth=6)
    rep = runner.run(lambda fn: fn(real), inv, client=Scripted(policy))
    for m in seen_messages:
        assert len(m) < 2500 + 200 and body(m) is not None                   # every message is valid JSON
    assert len(rep["agent"]["findings_verified"]) == 1 and len(rep["agent"]["findings_rejected"]) == 1
    assert "not returned by any tool" in rep["agent"]["findings_rejected"][0]["reasons"][0]
    calls = rep["reproducibility"]["tool_calls"]
    assert calls[0]["shown_truncated"] is True and calls[0]["shown_sha256"] != calls[0]["result_sha256"]


def test_stored_trace_is_valid_complete_and_hash_faithful(real, monkeypatch):
    monkeypatch.setattr(store, "STORE_MAX_CHARS", 3000)                      # force the store's bounding too
    monkeypatch.setattr(T, "MAX_RESULT_CHARS", 2500)
    inv = start(real, "K252078", depth=6)
    runner.run(lambda fn: fn(real), inv, client=Scripted(
        lambda n, m: [("trace_ancestry", {"k_number": "K252078", "generations": 6})] if n == 1 else
        [("submit_report", {"summary": "s", "findings": [{"claim": "K252078 was traced.", "evidence": ["K252078"]}]})]))
    t = store.trace(real, inv["id"], with_results=True)[0]
    # the full result is larger than the store limit: kept as valid JSON, shortened with disclosure
    assert t["result_complete"] is False and t["result_omitted"] and t["result"]["_truncated"]
    assert t["result_chars"] > 3000
    # the hash describes the complete result, which a replay reproduces exactly
    ctx = RunContext("I-y", "K252078")
    run_tool(real, "trace_ancestry", {"k_number": "K252078", "generations": 6}, ctx)
    full_text = canonical_json(ctx.last_full)
    assert t["result_sha256"] == hashlib.sha256(full_text.encode()).hexdigest() and t["result_chars"] == len(full_text)
    # what the model saw is stored whole and matches its hash
    assert t["shown_truncated"] is True and t["shown_omitted"][0]["path"] == "ancestors"
    assert t["shown_sha256"] == hashlib.sha256(canonical_json(t["shown"]).encode()).hexdigest()


def test_small_results_are_stored_complete(real):
    inv = start(real, "K252078", depth=2, mode="deterministic")
    runner.run(lambda fn: fn(real), inv)
    for t in store.trace(real, inv["id"], with_results=True):
        assert t["result_complete"] is True and t["result"] is not None
        assert t["result_sha256"] == hashlib.sha256(canonical_json(t["result"]).encode()).hexdigest()


def test_legacy_cut_records_are_disclosed_not_fatal(real):
    inv = start(real, "K252078", depth=2)
    real.conn.execute(
        """MATCH (i:Investigation {id:$id}) CREATE (t:ToolCall {id:'T-legacy', investigation_id:$id, seq:1, step:1,
           tool:'trace_ancestry', args:'{}', ok:true, summary:'s', result:$cut, result_sha256:'x', origin:'llm'})
           CREATE (i)-[:RAN {seq:1}]->(t)""", {"id": inv["id"], "cut": '{"ancestors": [{"k": "K1' + "x" * 11990})
    t = store.trace(real, inv["id"], with_results=True)[0]
    assert t["result"]["_unparseable_legacy_record"] is True and t["result_complete"] is False


def test_resume_rebuilds_the_same_visible_ledger(real, monkeypatch):
    monkeypatch.setattr(T, "MAX_RESULT_CHARS", 2500)
    first = start(real, "K252078", depth=6)
    runner.run(lambda fn: fn(real), first, client=Scripted(
        lambda n, m: [("trace_ancestry", {"k_number": "K252078", "generations": 6})] if n == 1 else
        __import__("forebear.investigation.llm", fromlist=["x"]).LLMUnavailable("down")))
    prior = store.trace(real, first["id"])
    again = start(real, "K252078", depth=6)
    again["resumed_from"] = first["id"]
    captured = {}

    def policy(turn, messages):
        hidden = [k for k in ("K970839", "K981072", "K060705", "K091319", "K003068")
                  if k not in " ".join(m["content"] for m in messages if m["role"] == "tool")]
        captured["hidden"] = hidden
        return [("submit_report", {"summary": "s", "findings": [
            {"claim": f"{hidden[0]} is in K252078's ancestry.", "evidence": [hidden[0]]}]})]
    rep = runner.run(lambda fn: fn(real), again, client=Scripted(policy), prior=prior)
    replay = next(t for t in store.trace(real, again["id"]) if t["origin"] == "resume_replay")
    original = next(t for t in prior if t["tool"] == "trace_ancestry")
    assert replay["shown_sha256"] == original["shown_sha256"] and replay["shown_truncated"] is True
    assert rep["agent"]["findings_verified"] == [] and captured["hidden"]   # replay does not widen the evidence


def test_report_discloses_shortened_tool_results(real, monkeypatch):
    monkeypatch.setattr(T, "MAX_RESULT_CHARS", 2500)
    inv = start(real, "K252078", depth=6, mode="deterministic")
    rep = runner.run(lambda fn: fn(real), inv)
    md = store.report(real, inv["id"])[1]
    assert any(c["shown_truncated"] for c in rep["reproducibility"]["tool_calls"])
    assert re.search(r"shortened \(omitted items are not evidence\)", md)
