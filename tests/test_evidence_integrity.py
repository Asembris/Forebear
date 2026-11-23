"""Regression tests for the evidence-integrity fixes: compare keeps coverage, recall reach classifies timing per
supported / conditional route with date boundaries, the watchlist compares clearance dates and tracks the supported
generation, and recall links say whether they are FDA-listed associations or name the recalled model."""
import pytest
from conftest import build_tiny, recall

from forebear.lineage import assess, recall_attribution


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
