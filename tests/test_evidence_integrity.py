"""Regression tests for the evidence-integrity fixes: compare keeps coverage, recall reach classifies timing per
supported / conditional route with date boundaries, the watchlist compares clearance dates and tracks the supported
generation, and recall links say whether they are FDA-listed associations or name the recalled model."""
import importlib

import pytest
from conftest import build_tiny, cite, dev, recall
from fastapi.testclient import TestClient

from forebear.lineage import assess, classify_reach, compare, date_relation, recall_attribution, recall_reach


def _unresolve(g, src, dst):
    g.q("MATCH (:Device {k:$s})-[r:CITES]->(:Device {k:$d}) SET r.audit = 'unresolved'", {"s": src, "d": dst})


# ---------------------------------------------------------------- date boundaries
@pytest.mark.parametrize("clearance,start,want", [
    ("2021-06-15", "2021-06-14", "after"),
    ("2021-06-13", "2021-06-14", "before"),
    ("2021-06-14", "2021-06-14", "same_day"),
    ("2021-06-14T00:00:00", "2021-06-14", "same_day"),
    (None, "2021-06-14", "unknown"),
    ("2021-06-14", None, "unknown"),
    ("", "", "unknown"),
    ("None", "2021-06-14", "unknown"),
    ("2021-12-31", "2022-01-01", "before"),
])
def test_date_relation_boundaries(clearance, start, want):
    assert date_relation(clearance, start) == want


# ---------------------------------------------------------------- recall reach classification
REC = [{"k": "KA", "name": "A", "initiated": "2020-01-01"}, {"k": "KB", "name": "B", "initiated": "2010-01-01"},
       {"k": "KN", "name": "N", "initiated": None}]


def _row(k, decided, via, supported):
    return {"k": k, "name": k, "applicant": "x", "decision_date": decided, "gen": 1, "supported_gen": 1 if supported
            else None, "via": via, "supported_via": supported}


def test_reach_mixed_confidence_timing_comes_from_supported_route_only():
    # supported route to KA (recall 2020), conditional route to KB (recall 2010); cleared 2015
    r = classify_reach(REC, [_row("KD", "2015-05-05", ["KA", "KB"], ["KA"])])
    d = r["descendants"][0]
    assert d["evidence"] == "supported" and d["supported_via"] == ["KA"] and d["conditional_via"] == ["KB"]
    assert d["timing"] == "before" and d["after_recall"] is False and d["recall_started"] == "2020-01-01"
    assert d["conditional_timing"] == "after" and d["conditional_recall_started"] == "2010-01-01"
    assert r["counts"] == {"after_supported": 0, "after_conditional": 0, "before": 1, "same_day": 0, "unknown": 0,
                           "conditional": 0, "mixed": 1}


def test_reach_conditional_only_after_is_counted_apart_from_supported():
    r = classify_reach(REC, [_row("KD", "2015-05-05", ["KB"], [])])
    d = r["descendants"][0]
    assert d["evidence"] == "conditional" and d["timing"] == "after" and d["conditional_timing"] is None
    assert r["counts"]["after_conditional"] == 1 and r["counts"]["after_supported"] == 0


def test_reach_same_day_and_missing_dates_are_not_before():
    r = classify_reach(REC, [_row("K1", "2020-01-01", ["KA"], ["KA"]), _row("K2", None, ["KA"], ["KA"]),
                             _row("K3", "2022-01-01", ["KN"], ["KN"])])
    t = {d["k"]: d["timing"] for d in r["descendants"]}
    assert t == {"K1": "same_day", "K2": "unknown", "K3": "unknown"}
    assert not any(d["after_recall"] for d in r["descendants"])
    assert r["counts"]["before"] == 0 and r["counts"]["same_day"] == 1 and r["counts"]["unknown"] == 2
    assert r["initiated"] == "2010-01-01"           # the undated holder never becomes the string "None"
    assert {x["k"]: x["initiated"] for x in r["recalled"]}["KN"] is None


def test_reach_graph_conditional_route_does_not_decide_supported_timing(tiny):
    # K000011 (2009) cites K000002 (recall 2008-04-01) only through an unresolved citation, and K000001 (no recall).
    tiny.upsert_devices([dev("K000011", "2009-01-01"), dev("K000012", "2008-04-01")])
    tiny.upsert_citations([cite("K000011", "K000002"), cite("K000012", "K000002")])
    _unresolve(tiny, "K000011", "K000002")
    r = {d["k"]: d for d in recall_reach(tiny, "1", depth=3)["descendants"]}
    assert r["K000011"]["evidence"] == "conditional" and r["K000011"]["conditional_via"] == ["K000002"]
    assert r["K000011"]["timing"] == "after"
    assert r["K000012"]["timing"] == "same_day" and r["K000012"]["after_recall"] is False   # cleared the same day
    assert r["K000003"]["evidence"] == "supported" and r["K000003"]["timing"] == "after"
    out = recall_reach(tiny, "1", depth=3)
    assert out["counts"]["after_conditional"] == 1 and out["counts"]["same_day"] == 1


def test_reach_unknown_event_is_empty(tiny):
    r = recall_reach(tiny, "424242", depth=3)
    assert r["recalled"] == [] and r["descendants"] == [] and r["counts"]["after_supported"] == 0


# ---------------------------------------------------------------- watchlist
@pytest.fixture
def tiny_client(tmp_path, monkeypatch):
    p = tmp_path / "w.rl"
    g = build_tiny(p)
    # K000013 (2011) cites K000002 directly through an unresolved citation, and K000003 through a supported one:
    # the shortest route (gen 1) is conditional, but a supported gen-2 route exists.
    # K000014 is cleared on the day K000002's recall began: not "after".
    g.upsert_devices([dev("K000013", "2011-01-01"), dev("K000014", "2008-04-01")])
    g.upsert_citations([cite("K000013", "K000002"), cite("K000013", "K000003"), cite("K000014", "K000002")])
    _unresolve(g, "K000013", "K000002")
    g.close()
    monkeypatch.setenv("FOREBEAR_DB", str(p))
    from forebear import api
    importlib.reload(api)
    with TestClient(api.app) as c:
        yield c


def test_watchlist_supported_generation_survives_a_shorter_conditional_route(tiny_client):
    w = tiny_client.get("/api/watchlist").json()
    rows = {r["k"]: r for r in w["rows"]}
    r = rows["K000013"]
    assert r["min_gen"] == 1 and r["supported_min_gen"] == 2 and r["conditional"] is False
    assert r["supported_ancestors"] == ["K000002"]
    assert r["recalls"][0]["gen"] == 1 and r["recalls"][0]["supported_gen"] == 2


def test_watchlist_compares_clearance_dates_not_receipt(tiny_client):
    w = tiny_client.get("/api/watchlist").json()
    rows = {r["k"]: r for r in w["rows"]}
    assert "K000014" not in rows                        # same-day clearance is not "after"
    r = rows["K000003"]                                  # cleared 2010-06-01, recall began 2008-04-01
    assert r["timing"] == "after" and r["recall_basis"] == "2008-04-01" and r["days_after_recall"] == 791
    assert "receipt date is not a citation date" in w["compared"]
    assert all(x["attribution"] in ("product_family", "model_named", "listed_only", "unchecked")
               for row in w["rows"] for x in row["recalls"])


def test_reach_api_reports_timing_counts(tiny_client):
    r = tiny_client.get("/api/recall-event/1").json()
    assert set(r["counts"]) >= {"after_supported", "after_conditional", "before", "same_day", "unknown"}
    d = {x["k"]: x for x in r["descendants"]}
    assert d["K000014"]["timing"] == "same_day"
    assert d["K000013"]["evidence"] == "supported" and d["K000013"]["conditional_via"] == []


# ---------------------------------------------------------------- compare keeps coverage
def test_compare_rows_carry_coverage_and_provisional(tiny):
    tiny.upsert_devices([dev("K000015", "2019-01-01")])
    tiny.upsert_citations([cite("K000015", "K000008")])         # direct predicate whose summary was not read
    rows = {r["k"]: r for r in compare(tiny, ["K000009", "K000015", "K000002"])}
    clean, partial = rows["K000009"], rows["K000015"]
    assert clean["verdict"] == partial["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
    assert clean["evidence"] == "complete" and clean["provisional"] is False and clean["evidence_reasons"] == []
    assert partial["evidence"] == "partial" and partial["provisional"] is True
    assert "direct_predicate_summaries_unread" in partial["evidence_reasons"]
    assert partial["verdict_reason"].startswith("Provisional:")
    a = assess(tiny, "K000015")
    assert a["coverage"]["evidence_reasons"] == partial["evidence_reasons"]


def test_compare_marks_review_resting_only_on_unresolved_citation(tiny):
    _unresolve(tiny, "K000003", "K000002")
    row = compare(tiny, ["K000003"])[0]
    assert row["verdict"] == "REVIEW_LINEAGE" and row["conditional"] is True
    row = compare(tiny, ["K000005"])[0]                          # gen 3 from the recall: no medium signal at all
    assert row["conditional"] is False


def test_compare_regression_K012323_vs_K014074(real_copy):
    from forebear.graph import open_graph
    g = open_graph(real_copy, read_only=True)
    try:
        rows = {r["k"]: r for r in compare(g, ["K012323", "K014074"])}
    finally:
        g.close()
    a, b = rows["K012323"], rows["K014074"]
    assert a["verdict"] == b["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
    assert a["evidence"] == "partial" and a["provisional"] is True and a["evidence_reasons"]
    assert a["verdict_reason"].startswith("Provisional:")
    assert b["evidence"] == "complete" and b["provisional"] is False and b["evidence_reasons"] == []
    assert not b["verdict_reason"].startswith("Provisional:")


# ---------------------------------------------------------------- recall attribution
@pytest.mark.parametrize("link,want", [
    ({"linked_before_clearance": True, "link_name_check": "match"}, "product_family"),
    ({"linked_before_clearance": False, "link_name_check": "match"}, "model_named"),
    ({"linked_before_clearance": False, "link_name_check": "mismatch"}, "listed_only"),
    ({"link_name_check": "n/a"}, "unchecked"),
    ({}, "unchecked"),
])
def test_recall_attribution(link, want):
    assert recall_attribution(link) == want


def test_assessment_recall_evidence_carries_attribution(tmp_path):
    g = build_tiny(tmp_path / "a.rl")
    try:
        # FDA lists K000003 on a recall that began before K000003 was cleared: a product-family association
        r = recall("Z-0002-2009", ["K000003"], "2009-01-01", event="2")
        r["links"] = [{"k": "K000003", "name_check": "mismatch", "before_clearance": True}]
        g.upsert_recalls([r])
        a = assess(g, "K000004")
        ev = {e["id"]: e for s in a["signals"] for e in s["evidence"] if e.get("type") == "recall"}
        assert ev["Z-0002-2009"]["attribution"] == "product_family"
        assert ev["Z-0001-2008"]["attribution"] == "unchecked"
    finally:
        g.close()
