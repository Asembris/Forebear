"""Trusted lineage and ingestion integrity.

AI-only lineage: an LLM triage label or an automated-client (MCP) review is advisory. It never changes a
deterministic verdict; only a person's review does. Its evidence and provenance stay visible.
"""
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


# ---------------------------------------------------------------- staleness
def _saved(g, k):
    a = assess(g, k)
    g.save_assessment(k, a["verdict"], {"verdict": a["verdict"]}, "memo", "template", [])
    return a


def test_saved_assessment_is_flagged_after_ai_triage_and_human_review(tiny):
    _flag_k9_mention_to_recalled_k2(tiny)
    _saved(tiny, "K000009")
    tiny.set_triage("K000009", "K000002", "predicate", "compared with K000002", "test-model")
    h = tiny.assessments("K000009")[0]
    assert h["stale"] is True and "K000009->K000002" in h["changed_edges"]
    assert h["verdict"] == assess(tiny, "K000009")["verdict"]      # flagged for re-check, verdict unchanged
    tiny.review_citation("K000009", "K000002", "confirmed", "p.3", reviewer="user")
    assert assess(tiny, "K000009")["verdict"] != h["verdict"]
