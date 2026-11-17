"""Phase 1 regression checks on the shipped store and the committed raw evidence.

The BreathePal demo chain is verified twice: from the raw cache (the PDF text and openFDA records the
graph was built from) and through the graph and API, so a regression in either shows up."""
import json

import pytest

from conftest import ROOT

from forebear import openfda, summaries
from forebear.config import use_raw_cache
from forebear.graph import open_graph
from forebear.lineage import assess
from forebear.predicates import extract_from_summary


@pytest.fixture
def shipped(real_copy):
    g = open_graph(real_copy, read_only=True)
    yield g
    g.close()


@pytest.fixture
def offline():
    use_raw_cache(offline=True)              # cached responses only; never the network
    yield
    use_raw_cache()


def test_breathepal_chain_from_raw_evidence(offline):
    meta = {r["k_number"]: r for r in openfda.clearances_for_product_code("MNS")}
    assert meta["K113053"]["device_name"] == "BIPAP A 30 VENTILATORY SUPPORT SYSTEM"
    assert meta["K113053"]["applicant"] == "Respironics, Inc."
    assert meta["K113053"]["decision_date"] < meta["K252078"]["date_received"]
    s = summaries.load("K252078")
    assert s["status"] == "ok" and s["url"].endswith("/pdf25/K252078.pdf") and len(s["sha256"]) == 64
    assert "Primary Predicate Device BiPAP A30 Ventilatory support system (K113053)" in " ".join(s["pages"][4].split())
    hits = {h["k"]: h for h in extract_from_summary(s, "K252078")}
    assert list(hits) == ["K113053"] and hits["K113053"]["kind"] == "predicate"
    # the 2021 Philips PE-PUR foam recalls name K113053 in FDA's own k_numbers list
    recs = {r["product_res_number"]: r for r in openfda.recalls_for_product_code("MNS")
            if "K113053" in (r.get("k_numbers") or [])}
    for rid in ("Z-1957-2021", "Z-1958-2021", "Z-1973-2021"):
        r = recs[rid]
        assert r["root_cause_description"] == "Device Design" and r["event_date_initiated"] == "2021-06-14"
        assert "foam" in r["reason_for_recall"].lower()


def test_breathepal_chain_in_the_graph(shipped):
    a = assess(shipped, "K252078")
    assert a["verdict"] == "REVIEW_LINEAGE"
    gen1 = next(x for x in a["ancestors"] if x["k"] == "K113053")
    hop = gen1["hops"][0]
    assert gen1["gen"] == 1 and hop["page"] in (5, 6, 7) and "K113053" in hop["quote"]
    assert hop["source_url"].endswith("K252078.pdf") and not hop.get("audit")
    foam = {x["id"]: x for x in gen1["recalls"] if x["event"] in ("88058", "88071")}
    assert {"Z-1957-2021", "Z-1958-2021", "Z-1973-2021"} <= set(foam)
    for x in foam.values():
        assert x["classification"] == "Class I" and x["design_related"] and x["initiated"] < "2026-03-17"
    # Z-1973-2021's product text does not name the A30: the join rests on FDA's k_numbers list, and says so
    assert foam["Z-1973-2021"]["link_name_check"] != "match"     # "BIPAP A 30": no distinctive token -> n/a
    sig = next(s for s in a["signals"] if s["code"] == "ANCESTOR_RECALL" and s["chain"] == ["K252078", "K113053"])
    assert sig["severity"] == "medium"


def test_verified_typos_leave_the_lineage_and_corrections_enter_it(shipped):
    def anc(k):
        return {x["k"] for x in shipped.ancestors(k, 1)}
    assert "K010909" not in anc("K080079") and "K013909" in anc("K080079")        # suture -> S7 Elite
    assert "K131744" not in anc("K180295") and "K131774" in anc("K180295")        # apheresis -> HAMILTON-G5
    assert "K072950" not in anc("K130178") and "K072590" in anc("K130178")        # ECG module -> Inspiration
    c = {x["dst"]: x for x in shipped.direct_citations("K080079")}
    assert c["K010909"]["audit"] == "error" and c["K013909"]["audit"] == "corrected"
    assert c["K013909"]["corrected_from"] == "K010909" and "not human" in c["K013909"]["audit_by"]
    assert c["K013909"]["review"] is None                                         # no invented human approval


def test_no_lineage_edge_points_outside_the_panel_unless_audited(shipped):
    rows = shipped.q("""MATCH (a:Device)-[r:CITES]->(b:Device)
        WHERE r.kind = 'predicate' AND r.panel_check = 'different' AND r.audit IS NULL AND r.review IS NULL
        RETURN a.k AS src, b.k AS dst""")
    assert rows == []


def test_build_report_records_coverage_and_audit():
    rep = json.loads((ROOT / "data" / "build_report.json").read_text())
    assert rep["audit"]["unmatched"] == [] and rep["audit"]["corrections_refused"] == []
    assert rep["in_family_text_from_ocr"] > 0
    assert set(rep["in_family_summary_status"]) >= {"ok", "statement_only", "missing"}


def test_fda_recall_records_settle_a_name_mismatch(shipped):
    """K201620 cites 'DreamStation Auto BiPAP (K131982)'; openFDA's 510(k) record calls K131982 'REMSTAR AUTO
    A-FLEX HT', but FDA's recall records file DreamStation Auto BiPAP under it. Removing that edge hid a Class I
    design recall (review finding); it must stay in the lineage."""
    a = assess(shipped, "K201620")
    assert "K131982" in {x["k"] for x in a["ancestors"] if x["gen"] == 1}
    assert a["verdict"] == "REVIEW_LINEAGE"


def test_corrected_edges_are_never_counted_as_fully_verified(shipped):
    a = assess(shipped, "K080079")
    hop = next(x for x in a["ancestors"] if x["k"] == "K013909")["hops"][0]
    assert hop["audit"] == "corrected"
    assert a["coverage"]["evidence"] != "complete"


def test_no_ai_decision_occupies_the_human_review_field(shipped):
    rows = shipped.q("MATCH ()-[r:CITES]->() WHERE r.review IS NOT NULL RETURN r.reviewer AS who, count(*) AS n")
    assert rows == []                                   # no named person has reviewed any edge yet
    for src in ("K120562", "K120639", "K151120"):
        c = next(c for c in shipped.direct_citations(src) if c["dst"] == "K093416")
        assert c["audit"] == "unresolved" and c["review"] is None
        assert "K093416" in {x["k"] for x in shipped.ancestors(src, 1)}


def test_reviews_file_keeps_the_ai_decisions_for_the_record_only():
    data = json.loads((ROOT / "data" / "reviews.json").read_text(encoding="utf-8"))
    assert data["reviews"] == []
    kept = {(x["src"], x["dst"]): x for x in data["ai_generated_not_applied"]}
    assert set(kept) == {("K120562", "K093416"), ("K120639", "K093416"), ("K151120", "K093416"), ("K092835", "K991646")}
    for x in kept.values():
        assert x["applied_as_human_review"] is False and "AI-generated" in x["provenance"] and x["note"]
