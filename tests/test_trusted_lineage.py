"""Trusted lineage and ingestion integrity.

1. AI-only lineage: an LLM triage label or an automated-client (MCP) review is advisory. It never changes a
   deterministic verdict; only a person's review does. Its evidence and provenance stay visible.
2. Live re-ingest reconciliation: citations a refreshed FDA summary no longer supports are retired atomically,
   never deleted, keeping human reviews, labels, audit fields and provenance.
"""
import pytest

from forebear import dataset, ingest
from forebear.lineage import assess, compare, recall_reach


def _flag_k9_mention_to_recalled_k2(tiny):
    """K000009 -> K000001 is a clean, complete, green lineage. Add a *mention* of K000002 (design-related Class I
    recall) to K000009's summary: as a mention it is not lineage."""
    tiny.upsert_citations([{"src": "K000009", "dst": "K000002", "kind": "mention", "confidence": 0.4, "page": 3,
                            "snippet": "compared with K000002", "quote": "compared with K000002", "method": "test",
                            "source_url": "https://example.invalid/K000009.pdf", "source_sha256": "s9"}])


# ---------------------------------------------------------------- 1. AI-only lineage is advisory
def test_ai_label_alone_does_not_change_the_verdict(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    before = assess(tiny, "K000009")
    assert before["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and before["coverage"]["evidence"] == "complete"

    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    a = assess(tiny, "K000009")
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL"                 # was REVIEW_LINEAGE before the fix
    assert "K000002" not in {x["k"] for x in a["ancestors"]}
    assert not [s for s in a["signals"] if s["severity"] in ("high", "medium")]
    # ... but it is not presented as fully supported either
    assert a["coverage"]["evidence"] == "partial" and a["verdict_reason"].startswith("Provisional")
    assert "advisory_links_pending_review" in a["coverage"]["evidence_reasons"]
    assert compare(tiny, ["K000009"])[0]["provisional"] is True


def test_advisory_link_keeps_its_evidence_and_provenance(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    s = next(s for s in assess(tiny, "K000009")["signals"] if s["code"] == "ADVISORY_LINK_PENDING_REVIEW")
    assert s["severity"] == "info" and "not used for the verdict" in s["title"] and "design-related" in s["title"]
    link = next(e for e in s["evidence"] if e["type"] == "advisory_citation")
    assert link["trust"] == "advisory" and link["basis"] == ["llm_label"] and link["gen"] == 1
    assert (link["ai_label"], link["ai_model"], link["ai_quote"]) == ("predicate", "test-model", "compared with K000002")
    assert link["ai_at"] and link["page"] == 3 and link["source_sha256"] == "s9"
    rec = next(e for e in s["evidence"] if e["type"] == "recall")
    assert rec["id"] == "Z-0001-2008" and rec["via_advisory"] == "K000009->K000002"


def test_ai_label_never_reaches_recall_reach_or_watchlist(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    assert "K000009" not in {d["k"] for d in recall_reach(tiny, "1")["descendants"]}
    assert not any(r["k"] == "K000009" for r in tiny.cited_after_recall(design_only=True))


def test_human_approval_makes_an_advisory_link_trusted(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    tiny.review_citation("K000009", "K000002", "confirmed", "PDF p.3 names it as a predicate", reviewer="user")
    a = assess(tiny, "K000009")
    assert a["verdict"] == "REVIEW_LINEAGE"
    sig = next(s for s in a["signals"] if s["code"] == "ANCESTOR_RECALL" and s["chain"] == ["K000009", "K000002"])
    hop = next(e for e in sig["evidence"] if e["type"] == "citation")
    assert hop["trust"] == "human_verified" and hop["reviewer"] == "user" and hop["ai_label"] == "predicate"
    assert not any(s["code"] == "ADVISORY_LINK_PENDING_REVIEW" for s in a["signals"])
    assert "K000009" in {d["k"] for d in recall_reach(tiny, "1")["descendants"]}


def test_human_rejection_removes_the_advisory_link(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    tiny.review_citation("K000009", "K000002", "rejected", "only a comparison", reviewer="user")
    a = assess(tiny, "K000009")
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["coverage"]["evidence"] == "complete"
    assert not any(s["code"] == "ADVISORY_LINK_PENDING_REVIEW" for s in a["signals"])


def test_mcp_client_confirmation_is_advisory_too(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    tiny.review_citation("K000009", "K000002", "confirmed", "agent says predicate", reviewer="mcp-client")
    a = assess(tiny, "K000009")
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["coverage"]["advisory_links"] == 1
    link = next(e for s in a["signals"] if s["code"] == "ADVISORY_LINK_PENDING_REVIEW"
                for e in s["evidence"] if e["type"] == "advisory_citation")
    assert link["basis"] == ["client_confirmation"]


def test_mcp_client_rejection_does_not_drop_a_recall_from_the_verdict(tiny):
    assert assess(tiny, "K000004")["verdict"] == "REVIEW_LINEAGE"   # K000004 -> K000003 -> K000002 (recalled)
    tiny.review_citation("K000004", "K000003", "rejected", "agent disagrees", reviewer="mcp-client")
    a = assess(tiny, "K000004")
    assert a["verdict"] == "REVIEW_LINEAGE"
    assert "K000003" in {x["k"] for x in a["ancestors"]}
    unc = next(s for s in a["signals"] if s["code"] == "UNCERTAIN_LINK_IN_LINEAGE")
    assert any(e["dst"] == "K000003" and "client_rejection_pending" in e["doubt"] for e in unc["evidence"])


def test_mcp_client_review_never_overwrites_a_person(tiny):
    tiny.review_citation("K000004", "K000003", "confirmed", "checked p.2", reviewer="user")
    r = tiny.review_citation("K000004", "K000003", "rejected", "agent disagrees", reviewer="mcp-client")
    assert r["kept_human_review"] is True and r["review"] == "confirmed" and r["reviewer"] == "user"
    c = next(c for c in tiny.direct_citations("K000004") if c["dst"] == "K000003")
    assert (c["review"], c["reviewer"], c["review_note"], c["in_lineage"]) == ("confirmed", "user", "checked p.2", True)


def test_direct_citations_report_trust_standing(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    by = {c["dst"]: c for c in tiny.direct_citations("K000009")}
    assert (by["K000001"]["in_lineage"], by["K000001"]["advisory"]) == (True, False)
    assert (by["K000002"]["in_lineage"], by["K000002"]["advisory"]) == (False, True)


# ---------------------------------------------------------------- 2. live re-ingest reconciliation
META = [{"k_number": "K261000", "device_name": "New CPAP", "applicant": "NewCo", "decision_date": "2026-05-01",
         "date_received": "2026-01-01", "product_code": "BZD", "statement_or_summary": "Summary"}]


def _network(monkeypatch, pages, sha, status="ok"):
    summary = {"k": "K261000", "status": status, "url": "https://example.invalid/K261000.pdf", "sha256": sha,
               "pages": pages}
    monkeypatch.setattr(ingest.openfda, "clearances_by_k",
                        lambda ks, use_cache=True: [m for m in META if m["k_number"] in ks])
    monkeypatch.setattr(ingest.summaries, "fetch", lambda k: summary)
    monkeypatch.setattr(dataset.summaries, "load", lambda k: summary if k == "K261000" else None)
    monkeypatch.setattr(ingest, "fetch_recalls_for", lambda ks, use_cache=True: [])


V1 = ["Primary Predicate Device: Device K000003 (K000003). Secondary predicate device: Device K000009 (K000009)."]
V2 = ["Primary Predicate Device: Device K000009 (K000009)."]


def _edges(g, k="K261000"):
    return {c["dst"]: c for c in g.direct_citations(k)}


def test_repeated_ingest_of_the_same_summary_is_a_no_op(tiny, monkeypatch):
    _network(monkeypatch, V1, "v1")
    ingest.add_clearance(tiny, "K261000")
    stats, edges = tiny.stats(), _edges(tiny)
    res = ingest.add_clearance(tiny, "K261000")
    assert tiny.stats() == stats and res["reconciliation"]["retired"] == [] and res["reconciliation"]["new"] == []
    assert {k: (e["in_lineage"], e["retired_at"]) for k, e in _edges(tiny).items()} == \
        {k: (e["in_lineage"], e["retired_at"]) for k, e in edges.items()}


def test_removed_citation_is_retired_with_reviews_and_provenance_kept(tiny, monkeypatch):
    _network(monkeypatch, V1, "v1")
    ingest.add_clearance(tiny, "K261000")
    assert assess(tiny, "K261000")["verdict"] == "REVIEW_LINEAGE"   # via K000003 -> K000002 (design recall)
    tiny.review_citation("K261000", "K000003", "confirmed", "checked v1 p.1", reviewer="user")
    tiny.set_triage("K261000", "K000003", "predicate", "Primary Predicate Device", "test-model")

    _network(monkeypatch, V2, "v2")                                 # FDA's refreshed summary drops K000003
    res = ingest.add_clearance(tiny, "K261000")
    rec = res["reconciliation"]
    assert rec["ran"] is True and [r["dst"] for r in rec["retired"]] == ["K000003"]
    assert rec["retired_with_human_review"] == ["K000003"]

    e = _edges(tiny)["K000003"]                                     # the edge still exists, nothing destroyed
    assert e["retired_at"] and e["retired_reason"] == "not_in_refreshed_summary" and e["in_lineage"] is False
    assert (e["review"], e["reviewer"], e["review_note"]) == ("confirmed", "user", "checked v1 p.1")
    assert (e["ai_label"], e["ai_model"]) == ("predicate", "test-model")
    assert e["source_sha256"] == "v1" and e["reviewed_source_sha256"] == "v1" and e["page"] == 1
    assert e["advisory"] is False

    a = assess(tiny, "K261000")
    assert "K000003" not in {x["k"] for x in a["ancestors"]}
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
    assert a["coverage"]["evidence"] == "partial"                   # a person's decision rested on the old text
    assert "human_confirmed_citation_retired" in a["coverage"]["evidence_reasons"]
    sig = next(s for s in a["signals"] if s["code"] == "CITATION_RETIRED_BY_REINGEST")
    assert sig["evidence"][0]["retired_by_sha256"] == "v2" and "re-review" in sig["title"]
    assert not any(s["code"] == "PREDICATE_CITATION_UNRESOLVED" for s in a["signals"])


def test_retired_citation_is_restored_when_a_later_summary_cites_it_again(tiny, monkeypatch):
    _network(monkeypatch, V1, "v1")
    ingest.add_clearance(tiny, "K261000")
    _network(monkeypatch, V2, "v2")
    ingest.add_clearance(tiny, "K261000")
    _network(monkeypatch, V1, "v3")
    res = ingest.add_clearance(tiny, "K261000")
    assert res["reconciliation"]["restored"] == ["K000003"] and res["reconciliation"]["retired"] == []
    e = _edges(tiny)["K000003"]
    assert e["retired_at"] is None and e["in_lineage"] is True and e["source_sha256"] == "v3"
    assert assess(tiny, "K261000")["verdict"] == "REVIEW_LINEAGE"


def test_unreadable_refresh_never_wipes_existing_lineage(tiny, monkeypatch):
    _network(monkeypatch, V1, "v1")
    ingest.add_clearance(tiny, "K261000")
    _network(monkeypatch, [""], "v2", status="no_text")
    res = ingest.add_clearance(tiny, "K261000")
    assert res["reconciliation"]["ran"] is False and res["reconciliation"]["retired"] == []
    assert all(e["retired_at"] is None for e in _edges(tiny).values())


def test_reconciliation_rolls_back_with_the_rest_of_the_write(tiny, monkeypatch):
    _network(monkeypatch, V1, "v1")
    ingest.add_clearance(tiny, "K261000")
    tiny.review_citation("K261000", "K000003", "confirmed", "checked", reviewer="user")
    stats, before = tiny.stats(), _edges(tiny)

    _network(monkeypatch, V2, "v2")

    def boom(rows):
        raise RuntimeError("disk full")
    monkeypatch.setattr(tiny, "upsert_recalls", boom)               # fails after the retire in the same tx
    with pytest.raises(RuntimeError):
        ingest.add_clearance(tiny, "K261000")
    after = _edges(tiny)
    assert tiny.stats() == stats
    assert after["K000003"]["retired_at"] is None and after["K000003"]["in_lineage"] is True
    assert after["K000003"]["review"] == "confirmed"
    assert {k: e["source_sha256"] for k, e in after.items()} == {k: e["source_sha256"] for k, e in before.items()}


# ---------------------------------------------------------------- staleness
def _saved(g, k):
    a = assess(g, k)
    g.save_assessment(k, a["verdict"], {"verdict": a["verdict"]}, "memo", "template", [])
    return a


def test_saved_assessment_goes_stale_when_reingest_retires_a_citation(tiny, monkeypatch):
    _network(monkeypatch, V1, "v1")
    ingest.add_clearance(tiny, "K261000")
    _saved(tiny, "K261000")
    _saved(tiny, "K000005")                                         # unrelated lineage
    assert not any(h["stale"] for h in tiny.assessments())
    _network(monkeypatch, V2, "v2")
    ingest.add_clearance(tiny, "K261000")
    by = {h["k"]: h for h in tiny.assessments()}
    assert by["K261000"]["stale"] is True and by["K261000"]["reingested"] == ["K261000"]
    assert by["K000005"]["stale"] is False


def test_saved_assessment_is_flagged_after_ai_triage_and_human_review(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    _saved(tiny, "K000009")
    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    h = tiny.assessments("K000009")[0]
    assert h["stale"] is True and "K000009->K000002" in h["changed_edges"]
    assert h["verdict"] == assess(tiny, "K000009")["verdict"]      # flagged for re-check, verdict unchanged
    tiny.review_citation("K000009", "K000002", "confirmed", "p.3", reviewer="user")
    assert assess(tiny, "K000009")["verdict"] != h["verdict"]


# ---------------------------------------------------------------- reviews are bound to the evidence version
def test_an_outdated_confirmation_of_a_mention_is_advisory_not_lineage(tiny):
    tiny.upsert_citations([{"src": "K000009", "dst": "K000002", "kind": "mention", "confidence": 0.4, "page": 3,
                            "snippet": "see K000002", "quote": "see K000002", "method": "test",
                            "source_url": "u", "source_sha256": "s1"}])
    tiny.review_citation("K000009", "K000002", "confirmed", "a predicate on p.3", reviewer="user")
    assert assess(tiny, "K000009")["verdict"] == "REVIEW_LINEAGE"
    tiny.upsert_citations([{"src": "K000009", "dst": "K000002", "kind": "mention", "confidence": 0.4, "page": 3,
                            "snippet": "see K000002", "quote": "see K000002", "method": "test",
                            "source_url": "u", "source_sha256": "s2"}])
    a = assess(tiny, "K000009")
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["coverage"]["evidence"] == "partial"
    link = next(e for s in a["signals"] if s["code"] == "ADVISORY_LINK_PENDING_REVIEW"
                for e in s["evidence"] if e["type"] == "advisory_citation")
    assert link["basis"] == ["outdated_human_confirmation"] and link["review_note"] == "a predicate on p.3"
