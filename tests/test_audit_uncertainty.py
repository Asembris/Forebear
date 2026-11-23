"""Phase 1: audit decisions, uncertainty in assessments, recall-link evidence, offline guard."""
import json

import pytest

from conftest import build_tiny, cite, dev, recall

from forebear import audit, dataset, openfda
from forebear.config import CACHE_MODE, use_raw_cache
from forebear.lineage import assess, doubt


# ---------------------------------------------------------------- audit decisions
def _row(src, dst, kind="predicate"):
    return {"src": src, "dst": dst, "kind": kind, "confidence": 0.9, "page": 1, "snippet": "s",
            "quote": f"S7 Elite ({dst})", "method": "regex-context-v3", "text_source": "pdf_text_layer",
            "source_url": "u", "source_sha256": "h", "name_check": "mismatch", "name_check_method": "v2",
            "panel_check": "different", "src_panel": "AN", "explicit_label": True}


def test_audit_apply_annotates_corrects_and_counts_unmatched():
    rows = [_row("K080079", "K010909"), _row("K080079", "K033841")]
    known = {"K013909": {"device_name": "S7 ELITE CP AP SYSTEM", "decision_date": "2002-07-08",
                         "advisory_committee": "AN"},
             "K020000": {"device_name": "LATER", "decision_date": "2030-01-01"}}
    data = {"auditor": "test-audit", "decisions": [
        {"src": "K080079", "dst": "K010909", "decision": "error", "correct_to": "K013909", "note": "typo"},
        {"src": "K080079", "dst": "K033841", "decision": "error", "correct_to": "K020000", "note": "too late"},
        {"src": "K111111", "dst": "K222222", "decision": "variant", "note": "edge no longer extracted"}]}
    rep = {}
    extra = audit.apply(rows, known, data, {"K080079": "2008-04-08"}, rep)
    assert rows[0]["audit"] == "error" and rows[0]["audit_by"] == "test-audit"
    assert len(extra) == 1 and extra[0]["dst"] == "K013909" and extra[0]["audit"] == "corrected"
    assert extra[0]["corrected_from"] == "K010909" and extra[0]["name_check"] == "match"
    assert rep["corrections_refused"] == ["K080079->K020000"]       # would predate nothing: refused
    assert rep["unmatched"] == ["K111111->K222222"]                 # never silently re-targeted


def test_audit_file_is_valid_and_never_claims_a_human_reviewer():
    data = audit.load()
    assert "not human" in data["auditor"]
    for d in data["decisions"]:
        assert d["decision"] in audit.STATUSES and d["note"]
        assert not d.get("correct_to") or d["decision"] == "error"
        assert not d.get("auditor") or "not human" in d["auditor"]
    with pytest.raises(ValueError):
        bad = {"decisions": [{"src": "K1", "dst": "K2", "decision": "variant", "correct_to": "K3", "note": "x"}]}
        p = audit.AUDIT / "_bad_test.json"
        try:
            p.write_text(json.dumps(bad))
            audit.load(p)
        finally:
            p.unlink(missing_ok=True)


@pytest.mark.parametrize("source_change", [{"sha256": "changed"}, {"page": 2},
                                          {"quote": "K000001 different device"}])
def test_source_audit_requires_matching_pdf_and_literal_page(monkeypatch, source_change):
    row = _row("K000002", "K000001", "reference")
    source = {"sha256": "h", "page": 1, "quote": "Predicate device K000001"}
    monkeypatch.setattr(audit.summaries, "load_text",
                        lambda k: {"sha256": "h", "pages": ["Predicate device\nK000001"]})
    decision = {"src": row["src"], "dst": row["dst"], "decision": "role_corrected",
                "kind": "predicate", "note": "FDA table", "source": source | source_change}
    with pytest.raises(ValueError, match="audit source changed or quote missing"):
        audit.apply([row], {}, {"decisions": [decision]}, {})
    assert row["kind"] == "reference"


def test_source_role_corrections_outrank_machine_labels_and_reviews(tiny):
    src, dst = "K000007", "K000004"
    tiny.review_citation(src, dst, "confirmed", "automated", reviewer="mcp-client")
    assert tiny.ancestors(src, 1) == []                            # a client confirmation alone is advisory
    assert [h["dst"] for h in tiny.advisory_edges_from([src])] == [dst]
    tiny.upsert_citations([{**cite(src, dst, "reference"), "audit": "role_corrected"}])
    tiny.set_triage(src, dst, "predicate", "machine triage", "test")
    tiny.review_citation(src, dst, "confirmed", "automated", reviewer="mcp-client")
    assert tiny.ancestors(src, 1) == []
    tiny.review_citation(src, dst, "confirmed", "page reviewed", reviewer="Reviewer Name")
    assert [a["k"] for a in tiny.ancestors(src, 1)] == [dst]

    tiny.upsert_citations([{**cite(src, dst), "audit": "role_corrected"}])
    tiny.review_citation(src, dst, "rejected", "automated", reviewer="mcp-client")
    assert [a["k"] for a in tiny.ancestors(src, 1)] == [dst]


def test_lineage_honours_audit_and_humans_override_it(tiny):
    tiny.conn.execute("MATCH (:Device {k:'K000004'})-[c:CITES]->(:Device {k:'K000003'}) SET c.audit = 'error'")
    assert "K000003" not in {a["k"] for a in tiny.ancestors("K000004")}
    tiny.review_citation("K000004", "K000003", "confirmed", "checked the PDF", reviewer="person")
    assert "K000003" in {a["k"] for a in tiny.ancestors("K000004")}

# ---------------------------------------------------------------- uncertainty in assessments
def test_doubt_rules():
    assert doubt({"name_check": "mismatch"}) == ["name_mismatch"]
    assert doubt({"name_check": "mismatch", "audit": "variant"}) == []
    assert doubt({"audit": "unresolved", "review": "confirmed"}) == []
    assert doubt({"kind": "mention", "ai_label": "predicate"}) == ["llm_label_only"]
    assert doubt({"panel_check": "different"}) == ["different_fda_panel"]
    assert doubt({"audit": "corrected", "name_check": "match"}) == ["audit_correction"]


def test_uncertain_only_predicate_link_is_not_green(tiny):
    # K000009 -> K000001 is a clean, recall-free lineage: green until its only link becomes doubtful
    assert assess(tiny, "K000009")["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
    tiny.conn.execute("MATCH (:Device {k:'K000009'})-[c:CITES]->() SET c.audit = 'unresolved'")
    a = assess(tiny, "K000009")
    assert a["verdict"] == "INSUFFICIENT_LINEAGE" and a["coverage"]["evidence"] == "uncertain"
    assert any(s["code"] == "UNCERTAIN_LINK_IN_LINEAGE" for s in a["signals"])
    tiny.review_citation("K000009", "K000001", "confirmed", None, reviewer="person")
    assert assess(tiny, "K000009")["verdict"] == "NO_DESIGN_RECALL_SIGNAL"


def test_unresolved_predicate_citation_makes_a_green_result_provisional(tiny):
    tiny.conn.execute("MATCH (d:Device {k:'K000009'}) SET d.unresolved_citations = $u, d.unresolved_predicates = 1",
                      {"u": json.dumps([{"src": "K000009", "cited": "K123456", "kind": "predicate",
                                         "reason": "not_in_openfda", "page": 2, "quote": "Predicate: X (K123456)"}])})
    a = assess(tiny, "K000009")
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["verdict_reason"].startswith("Provisional")
    sig = next(s for s in a["signals"] if s["code"] == "PREDICATE_CITATION_UNRESOLVED")
    assert sig["evidence"][0]["cited"] == "K123456" and a["coverage"]["unresolved_predicate_citations"] == 1


def test_audit_removed_predicate_is_reported_but_a_corrected_one_is_not(tmp_path):
    g = build_tiny(tmp_path / "t.rl")
    try:
        g.upsert_devices([dev("K000010", "2019-01-01")])
        g.upsert_citations([{**cite("K000010", "K000008"), "audit": "error", "audit_note": "typo"},
                            {**cite("K000010", "K000001"), "audit": "corrected", "corrected_from": "K000008"},
                            {**cite("K000010", "K000003"), "audit": "not_predicate"}])
        missing = {m["cited"]: m["reason"] for m in
                   next(s for s in assess(g, "K000010")["signals"] if s["code"] == "PREDICATE_CITATION_UNRESOLVED")[
                       "evidence"]}
        assert missing == {"K000003": "audit_not_predicate"}         # K000008 was corrected to K000001
    finally:
        g.close()

# ---------------------------------------------------------------- reproducibility guard
def test_offline_build_never_calls_the_network(monkeypatch, tmp_path):
    monkeypatch.setattr(openfda, "OPENFDA_CACHE", tmp_path)
    use_raw_cache(offline=True)
    try:
        with pytest.raises(RuntimeError, match="offline build"):
            openfda.clearances_by_k(["K999998"])
    finally:
        use_raw_cache()
    assert CACHE_MODE["offline"] is False


# ---------------------------------------------------------------- graph integrity
def test_edge_provenance_persists_across_reopen(tmp_path):
    from forebear.graph import open_graph
    p = tmp_path / "p.rl"
    g = build_tiny(p)
    g.upsert_citations([{**cite("K000005", "K000004"), "quote": "Predicate: Device K000004 (K000004)",
                         "text_source": "ocr", "source_sha256": "abc", "name_check": "match",
                         "panel_check": "same", "audit": "variant", "audit_note": "checked", "audit_by": "audit"}])
    g.close()
    g = open_graph(p, read_only=True)
    try:
        c = next(c for c in g.direct_citations("K000005") if c["dst"] == "K000004")
        assert (c["quote"], c["text_source"], c["audit"], c["panel_check"]) == (
            "Predicate: Device K000004 (K000004)", "ocr", "variant", "same")
        hop = next(a for a in g.ancestors("K000005") if a["k"] == "K000004")["hops"][0]
        assert hop["audit"] == "variant" and hop["text_source"] == "ocr" and hop["quote"]
    finally:
        g.close()


def test_reingest_keeps_human_review_and_reapplies_the_audit(tiny, monkeypatch):
    from forebear import ingest
    meta = [{"k_number": "K261000", "device_name": "New CPAP", "applicant": "NewCo", "decision_date": "2026-05-01",
             "date_received": "2026-01-01", "product_code": "BZD", "statement_or_summary": "Summary",
             "advisory_committee": "AN"}]
    summary = {"k": "K261000", "status": "ok", "url": "u", "sha256": "x",
               "pages": ["Primary Predicate Device: Mystery mask (K000004). Secondary predicate: Device K000003."]}
    monkeypatch.setattr(ingest.openfda, "clearances_by_k", lambda ks, use_cache=True: [m for m in meta if m["k_number"] in ks])
    monkeypatch.setattr(ingest.summaries, "fetch", lambda k: summary)
    monkeypatch.setattr(dataset.summaries, "load", lambda k: summary if k == summary["k"] else None)
    monkeypatch.setattr(ingest, "fetch_recalls_for", lambda ks, use_cache=True: [])
    monkeypatch.setattr(ingest.audit, "load", lambda: {"auditor": "test-audit", "decisions": [
        {"src": "K261000", "dst": "K000004", "decision": "unresolved", "note": "name differs"}]})
    ingest.add_clearance(tiny, "K261000")
    tiny.review_citation("K261000", "K000003", "rejected", "not a predicate", reviewer="person")
    ingest.add_clearance(tiny, "K261000")                       # re-ingest: MERGE, same rows again
    cits = {c["dst"]: c for c in tiny.direct_citations("K261000")}
    assert cits["K000004"]["audit"] == "unresolved" and cits["K000004"]["audit_by"] == "test-audit"
    assert cits["K000003"]["review"] == "rejected" and cits["K000003"]["reviewer"] == "person"
    a = assess(tiny, "K261000")
    assert a["coverage"]["evidence"] == "uncertain"             # its only remaining predicate link is unresolved


def test_recall_with_unknown_cause_or_class_makes_a_green_result_provisional(tiny):
    assert assess(tiny, "K000009")["coverage"]["evidence"] == "complete"
    tiny.upsert_recalls([{**recall("Z-0100-2010", ["K000001"], "2010-01-01", design=False, cls=None),
                          "root_cause": "Other"}])
    a = assess(tiny, "K000009")
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["verdict_reason"].startswith("Provisional")
    assert any(s["code"] == "RECALL_CAUSE_OR_CLASS_UNKNOWN" for s in a["signals"])


def test_known_non_design_classified_recall_does_not_lower_completeness(tiny):
    tiny.upsert_recalls([recall("Z-0101-2010", ["K000001"], "2010-01-01", design=False, cls="Class II")])
    assert assess(tiny, "K000009")["coverage"]["evidence"] == "complete"


def test_unattributed_design_recalls_in_the_product_code_make_green_provisional(tiny):
    tiny.upsert_product_codes([{"code": "BZD", "name": "CPAP", "device_class": "2", "regulation": "868.5905",
                                "unattributed_recalls": json.dumps([{"id": "Z-9", "design_related": True}]),
                                "unattributed_recalls_n": 1, "unattributed_design_recalls_n": 1}])
    a = assess(tiny, "K000009")
    assert a["coverage"]["evidence"] == "partial"
    assert any(s["code"] == "UNATTRIBUTED_RECALLS_IN_PRODUCT_CODE" for s in a["signals"])


def test_build_refuses_a_review_that_does_not_name_a_person(tmp_path):
    from scripts.build_graph import load_human_reviews
    p = tmp_path / "reviews.json"
    for who in ("curated", "", "Claude", "extraction-audit", "Claude Code agent", "gpt-4o", "Curated review",
                "user", "AI", "mcp-client"):
        p.write_text(json.dumps({"reviews": [{"src": "K1", "dst": "K2", "status": "rejected", "reviewer": who,
                                              "human": True, "note": "x"}]}))
        with pytest.raises(ValueError, match="must name the person"):
            load_human_reviews(p)
    # a person's name without the explicit attestation is refused too
    p.write_text(json.dumps({"reviews": [{"src": "K1", "dst": "K2", "status": "rejected", "reviewer": "Jane Doe, RA",
                                          "note": "checked p4"}]}))
    with pytest.raises(ValueError, match="must name the person"):
        load_human_reviews(p)
    p.write_text(json.dumps({"reviews": [{"src": "K1", "dst": "K2", "status": "rejected", "reviewer": "Jane Doe, RA",
                                          "human": True, "note": "checked p4"}],
                             "ai_generated_not_applied": [{"src": "K3", "dst": "K4"}]}))
    reviews, ai = load_human_reviews(p)
    assert [r["reviewer"] for r in reviews] == ["Jane Doe, RA"] and len(ai) == 1
