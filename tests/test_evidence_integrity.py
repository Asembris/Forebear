"""Regression tests for the evidence-integrity fixes: compare keeps coverage, recall reach classifies timing per
supported / conditional route with date boundaries, the watchlist compares clearance dates and tracks the supported
generation, and recall links say whether they are FDA-listed associations or name the recalled model."""
import pytest
from conftest import build_tiny, cite, dev, recall

from forebear.lineage import assess, compare, recall_attribution


def _unresolve(g, src, dst):
    g.q("MATCH (:Device {k:$s})-[r:CITES]->(:Device {k:$d}) SET r.audit = 'unresolved'", {"s": src, "d": dst})


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
