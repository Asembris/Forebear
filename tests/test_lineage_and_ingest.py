"""Verdict rules, coverage reporting, dataset validation and incremental ingestion."""
import pytest

from conftest import recall

from forebear import dataset, ingest
from forebear.agent import template_memo
from forebear.lineage import assess, compare, evidence_ids


def test_avoid_when_candidate_has_design_recall(tiny):
    a = assess(tiny, "K000002")
    assert a["verdict"] == "DESIGN_RECALL_ON_FILE"
    assert a["signals"][0]["code"] == "DIRECT_RECALL"


def test_review_when_grand_predicate_has_design_recall(tiny):
    a = assess(tiny, "K000004")          # K000004 -> K000003 -> K000002 (recalled)
    assert a["verdict"] == "REVIEW_LINEAGE"
    s = next(s for s in a["signals"] if s["code"] == "ANCESTOR_RECALL")
    assert s["gen"] == 2 and s["chain"] == ["K000004", "K000003", "K000002"]


def test_far_ancestor_is_low_not_review(tiny):
    a = assess(tiny, "K000005")          # recalled device is 3 generations up
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
    assert any(s["code"] == "ANCESTOR_RECALL" and s["severity"] == "low" for s in a["signals"])


def test_negative_case_no_recalls_anywhere(tiny):
    a = assess(tiny, "K000009")
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
    assert not [s for s in a["signals"] if s["severity"] in ("high", "medium", "low")]


def test_uncheckable_devices_are_never_green(tiny):
    assert assess(tiny, "K000008")["verdict"] == "INSUFFICIENT_LINEAGE"     # summary not readable
    assert assess(tiny, "K000001")["verdict"] == "INSUFFICIENT_LINEAGE"     # no predicate citations found


def test_unclassified_design_recall_on_predicate_is_review(tiny):
    tiny.upsert_recalls([recall("Z-0003-2019", ["K000001"], "2019-01-01", cls=None, event="3")])
    assert assess(tiny, "K000009")["verdict"] == "REVIEW_LINEAGE"


def test_class1_non_design_recall_on_direct_predicate_is_review(tiny):
    tiny.upsert_recalls([recall("Z-0004-2019", ["K000001"], "2019-01-01", design=False, cls="Class I", event="4")])
    a = assess(tiny, "K000009")
    assert a["verdict"] == "REVIEW_LINEAGE"
    assert "1 recall event(s) (1 product record(s))" in a["signals"][0]["title"]


def test_non_design_class2_recall_is_not_a_signal(tiny):
    tiny.upsert_recalls([recall("Z-0002-2019", ["K000003"], "2019-01-01", design=False, cls="Class II", event="2")])
    a = assess(tiny, "K000004")
    cited = {e["id"] for s in a["signals"] for e in s["evidence"] if e.get("type") == "recall"}
    assert "Z-0002-2019" not in cited and "Z-0001-2008" in cited


def test_coverage_reports_unread_ancestors(tiny):
    a = assess(tiny, "K000004")
    assert a["coverage"]["ancestors_lineage_unknown"] == 1          # K000008
    assert any(s["code"] == "LINEAGE_TRUNCATED" for s in a["signals"])


def test_unknown_device_returns_none(tiny):
    assert assess(tiny, "K123456") is None
    rows = compare(tiny, ["K000004", "K123456"])
    assert rows[1] == {"k": "K123456", "found": False}


def test_memo_only_states_graph_ids(tiny):
    a = assess(tiny, "K000004")
    memo = template_memo(a)
    allowed = evidence_ids(a)
    for p in memo["paragraphs"]:
        assert set(p["cites"]) <= allowed


def test_citation_rows_validate_against_openfda(monkeypatch):
    rec = {"status": "ok", "url": "u", "pages": [
        "Predicate Device: A (K111111). Predicate Device: B (K222222). Predicate: C (K333333)."]}
    monkeypatch.setattr(dataset.summaries, "load", lambda k: rec)
    known = {"K111111": {"decision_date": "2010-01-01"},          # valid
             "K222222": {"decision_date": "2030-01-01"}}          # cleared after the citing device
    report = {}
    rows = dataset.citation_rows("K999999", "2020-01-01", "2020-06-01", known, report)
    assert [r["dst"] for r in rows] == ["K111111"]
    assert report == {"kept_predicate": 1, "dropped_future": 1, "dropped_unresolved": 1}


def test_unreadable_summary_yields_no_edges(monkeypatch):
    monkeypatch.setattr(dataset.summaries, "load", lambda k: {"status": "no_text", "pages": [""]})
    assert dataset.citation_rows("K999999", None, None, {}, {}) == []


def _fake_network(monkeypatch, meta, summary, recalls=()):
    monkeypatch.setattr(ingest.openfda, "clearances_by_k", lambda ks, use_cache=True: [m for m in meta if m["k_number"] in ks])
    monkeypatch.setattr(ingest.summaries, "fetch", lambda k: summary)
    monkeypatch.setattr(dataset.summaries, "load", lambda k: summary if k == summary["k"] else None)
    monkeypatch.setattr(ingest, "fetch_recalls_for", lambda ks, use_cache=True: list(recalls))


def test_incremental_ingest_adds_device_edges_and_recalls(tiny, monkeypatch):
    meta = [{"k_number": "K261000", "device_name": "New CPAP", "applicant": "NewCo", "decision_date": "2026-05-01",
             "date_received": "2026-01-01", "product_code": "BZD", "statement_or_summary": "Summary"},
            {"k_number": "K190000", "device_name": "Outside predicate", "applicant": "Other",
             "decision_date": "2019-01-01", "product_code": "CBK"}]
    summary = {"k": "K261000", "status": "ok", "url": "https://example.invalid/K261000.pdf", "sha256": "x",
               "pages": ["Primary Predicate Device: Device K000004 (K000004). Secondary predicate: K190000."]}
    _fake_network(monkeypatch, meta, summary, [recall("Z-0009-2022", ["K190000"], "2022-02-02")])
    before = tiny.stats()
    res = ingest.add_clearance(tiny, "k261000")
    assert {c["dst"] for c in res["citations_added"]} == {"K000004", "K190000"}
    assert res["new_devices"] == ["K190000"]
    after = tiny.stats()
    assert after["nodes"]["Device"] == before["nodes"]["Device"] + 2
    a = assess(tiny, "K261000")
    assert a["verdict"] == "REVIEW_LINEAGE"                              # direct predicate K190000 recalled for design
    assert {"K000004", "K000003", "K190000"} <= {x["k"] for x in a["ancestors"]}
    # second ingest is a no-op on the graph
    ingest.add_clearance(tiny, "K261000")
    assert tiny.stats() == after


def test_ingest_rejects_bad_input_and_unknown_k(tiny, monkeypatch):
    with pytest.raises(ingest.IngestError):
        ingest.add_clearance(tiny, "12345")
    _fake_network(monkeypatch, [], {"k": "K777777", "status": "missing", "pages": []})
    with pytest.raises(ingest.IngestError, match="not a 510"):
        ingest.add_clearance(tiny, "K777777")


def test_ingest_network_failure_is_reported(tiny, monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(ingest.openfda, "clearances_by_k", boom)
    with pytest.raises(ingest.IngestError, match="openFDA lookup failed"):
        ingest.add_clearance(tiny, "K261001")


def test_ingest_write_failure_rolls_back_everything(tiny, monkeypatch):
    meta = [{"k_number": "K261000", "device_name": "New CPAP", "applicant": "NewCo", "decision_date": "2026-05-01",
             "date_received": "2026-01-01", "product_code": "BZD", "statement_or_summary": "Summary"}]
    summary = {"k": "K261000", "status": "ok", "url": "u", "sha256": "x",
               "pages": ["Primary Predicate Device: Device K000004 (K000004)."]}
    _fake_network(monkeypatch, meta, summary)
    before = tiny.stats()

    def boom(rows):
        raise RuntimeError("disk full")
    monkeypatch.setattr(tiny, "upsert_recalls", boom)      # devices + citations already written in the tx
    with pytest.raises(RuntimeError):
        ingest.add_clearance(tiny, "K261000")
    assert tiny.stats() == before and tiny.device("K261000") is None
