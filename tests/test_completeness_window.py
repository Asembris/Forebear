"""Adversarial tests: gaps anywhere in the requested ancestry must never read as a complete, clean result.

Chain used below (each device cites the next as its predicate):

    C (2020) -> A (2015) -> B (2010) -> D (2005) -> E (2000)

E and D carry a design-related Class I recall unless a test says otherwise. Every test then breaks the
chain somewhere, the way a typo'd or rejected citation does in real data, and checks what the assessment
says about the part it can no longer see.
"""
import json

import pytest

from conftest import cite, dev, recall

from forebear.graph import open_graph
from forebear.lineage import EVIDENCE_WINDOW, assess


def chain(path, recalled=("K000005",)):
    g = open_graph(path)
    g.upsert_product_codes([{"code": "BZD", "name": "CPAP", "device_class": "2", "regulation": "868.5905"}])
    g.upsert_devices([dev("K000001", "2020-01-01"), dev("K000002", "2015-01-01"), dev("K000003", "2010-01-01"),
                      dev("K000004", "2005-01-01"), dev("K000005", "2000-01-01")])
    g.upsert_citations([cite("K000001", "K000002"), cite("K000002", "K000003"), cite("K000003", "K000004"),
                        cite("K000004", "K000005")])
    for i, k in enumerate(recalled):
        g.upsert_recalls([recall(f"Z-{i:04d}-2009", [k], "2009-01-01")])
    return g


@pytest.fixture
def g(tmp_path):
    g = chain(tmp_path / "c.rl")
    yield g
    g.close()


def _remove(g, src, dst, how="audit"):
    if how == "audit":
        g.conn.execute("MATCH (:Device {k:$s})-[r:CITES]->(:Device {k:$d}) SET r.audit = 'error', r.audit_note = 'typo'",
                       {"s": src, "d": dst})
    else:
        g.review_citation(src, dst, "rejected", "not the predicate", reviewer="person")


def codes(a):
    return {s["code"] for s in a["signals"]}


def test_baseline_clean_and_complete(g):
    a = assess(g, "K000001", 4)          # E (gen 4) has the recall: low severity only
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["coverage"]["evidence"] == "complete"
    assert a["coverage"]["deeper_gaps"] == {"missing_predicate_citations": 0, "doubtful_links": 0, "unread_ancestors": 0}
    assert "DEEPER_ANCESTRY_GAPS" not in codes(a)


def test_shallow_request_never_claims_completeness(tmp_path):
    g = chain(tmp_path / "s.rl", recalled=("K000003",))        # recall on the grand-predicate B
    try:
        assert assess(g, "K000001", 2)["verdict"] == "REVIEW_LINEAGE"
        a = assess(g, "K000001", 1)                             # B is not traversed at depth 1
        assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
        assert a["coverage"]["evidence"] == "partial" and a["coverage"]["generations_traversed"] == 1
        assert a["verdict_reason"].startswith("Provisional") and "grand-predicate recalls were not checked" in a["verdict_reason"]
    finally:
        g.close()


@pytest.mark.parametrize("how", ["audit", "human"])
def test_missing_link_at_generation_two_hides_a_design_recall_and_is_partial(tmp_path, how):
    g = chain(tmp_path / "m2.rl", recalled=("K000003",))      # B (would be gen 2) is recalled
    try:
        _remove(g, "K000002", "K000003", how)                   # A's citation of B is removed
        a = assess(g, "K000001", 4)
        assert "K000003" not in {x["k"] for x in a["ancestors"]}
        assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["coverage"]["evidence"] == "partial"
        assert a["verdict_reason"].startswith("Provisional")
        m = next(s for s in a["signals"] if s["code"] == "PREDICATE_CITATION_UNRESOLVED")["evidence"]
        assert [(x["src"], x["cited"], x["gen"]) for x in m] == [("K000002", "K000003", 2)]
    finally:
        g.close()


def test_missing_link_at_generation_three_is_reported_not_called_complete_silently(g):
    _remove(g, "K000003", "K000004")                           # B's citation of D (gen 3) removed
    a = assess(g, "K000001", 4)
    assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
    assert a["coverage"]["evidence"] == "complete"             # nothing missing inside the verdict window
    assert a["coverage"]["deeper_gaps"]["missing_predicate_citations"] == 1
    assert "DEEPER_ANCESTRY_GAPS" in codes(a) and "lower-severity list may be incomplete" in a["verdict_reason"]
    # the same gap lies beyond a depth-2 request, so it is not reported there
    a2 = assess(g, "K000001", 2)
    assert a2["coverage"]["deeper_gaps"]["missing_predicate_citations"] == 0


def test_unresolvable_citation_deep_in_the_chain_is_counted(g):
    g.conn.execute("MATCH (d:Device {k:'K000003'}) SET d.unresolved_citations = $u, d.unresolved_predicates = 1",
                   {"u": json.dumps([{"src": "K000003", "cited": "K481744", "kind": "predicate",
                                      "reason": "not_in_openfda", "page": 1, "quote": "Predicate (K481744)"}])})
    a = assess(g, "K000001", 4)
    assert a["coverage"]["deeper_gaps"]["missing_predicate_citations"] == 1
    ev = next(s for s in a["signals"] if s["code"] == "PREDICATE_CITATION_UNRESOLVED")["evidence"]
    assert ev[0]["cited"] == "K481744" and ev[0]["gen"] == 3


def test_doubtful_link_beyond_the_window_is_counted(g):
    g.conn.execute("MATCH (:Device {k:'K000003'})-[r:CITES]->(:Device {k:'K000004'}) SET r.audit = 'unresolved'")
    a = assess(g, "K000001", 4)
    assert a["coverage"]["evidence"] == "complete"               # the doubtful hop is generation 3
    assert a["coverage"]["deeper_gaps"]["doubtful_links"] == 1 and "DEEPER_ANCESTRY_GAPS" in codes(a)
    # the same doubt one generation closer is inside the window and makes the result provisional
    g.conn.execute("MATCH (:Device {k:'K000002'})-[r:CITES]->(:Device {k:'K000003'}) SET r.audit = 'unresolved'")
    assert assess(g, "K000001", 4)["coverage"]["evidence"] == "partial"


def test_unread_ancestor_beyond_the_window_is_counted(tmp_path):
    g = chain(tmp_path / "u.rl")
    try:
        g.upsert_devices([dev("K000003", "2010-01-01", lineage_known=False)])   # B (gen 2) never read
        a = assess(g, "K000001", 4)
        assert a["coverage"]["deeper_gaps"]["unread_ancestors"] == 1
        assert "DEEPER_ANCESTRY_GAPS" in codes(a)
    finally:
        g.close()


def test_window_constant_matches_the_severity_rules():
    """The completeness guarantee is only as wide as the rules that can raise a verdict (gen <= 2)."""
    assert EVIDENCE_WINDOW == 2


def _routes(path):
    """C -> A, C -> X, A -> X: X is reached directly (gen 1), so the ancestor query keeps the short route and
    never shows the A -> X hop. A also cites B; B -> X gives a second, equal-length route in some tests."""
    g = open_graph(path)
    g.upsert_product_codes([{"code": "BZD", "name": "CPAP", "device_class": "2", "regulation": "868.5905"}])
    g.upsert_devices([dev("K000010", "2020-01-01"), dev("K000011", "2015-01-01"), dev("K000012", "2010-01-01"),
                      dev("K000014", "2016-01-01")])
    g.upsert_citations([cite("K000010", "K000011"), cite("K000010", "K000012"), cite("K000011", "K000012")])
    return g


@pytest.mark.parametrize("doubt_props", [
    "r.name_check = 'mismatch'", "r.audit = 'unresolved'", "r.audit = 'corrected'", "r.panel_check = 'different'"])
def test_doubtful_link_off_the_shortest_route_is_seen(tmp_path, doubt_props):
    g = _routes(tmp_path / "r.rl")
    try:
        g.conn.execute(f"MATCH (:Device {{k:'K000011'}})-[r:CITES]->(:Device {{k:'K000012'}}) SET {doubt_props}")
        a = assess(g, "K000010", 2)
        assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL"
        assert a["coverage"]["evidence"] == "partial" and a["coverage"]["doubtful_links"] == 1
        assert a["verdict_reason"].startswith("Provisional")
    finally:
        g.close()


def test_equal_length_routes_do_not_make_completeness_depend_on_query_order(tmp_path):
    g = _routes(tmp_path / "e.rl")
    try:
        # C -> B -> X as a clean route of the same length as C -> A -> X, which is doubtful
        g.conn.execute("MATCH (:Device {k:'K000010'})-[r:CITES]->(:Device {k:'K000012'}) DELETE r")
        g.upsert_citations([cite("K000010", "K000014"), cite("K000014", "K000012")])
        g.conn.execute("MATCH (:Device {k:'K000011'})-[r:CITES]->(:Device {k:'K000012'}) SET r.audit = 'unresolved'")
        a = assess(g, "K000010", 2)
        assert a["coverage"]["evidence"] == "partial"
        assert any(d["src"] == "K000011" and d["dst"] == "K000012" and d["gen"] == 2
                   for d in next(s for s in a["signals"] if s["code"] == "UNCERTAIN_LINK_IN_LINEAGE")["evidence"])
    finally:
        g.close()


def test_depth_is_reported_as_traversed(g):
    assert assess(g, "K000001", 0)["coverage"]["generations_traversed"] == 1
    assert assess(g, "K000001", 10)["coverage"]["generations_traversed"] == 8


def test_confirmation_through_the_mcp_client_is_not_a_human_confirmation(g):
    g.conn.execute("MATCH (:Device {k:'K000001'})-[r:CITES]->(:Device {k:'K000002'}) SET r.audit = 'unresolved'")
    g.review_citation("K000001", "K000002", "confirmed", "looks right", reviewer="mcp-client")
    assert assess(g, "K000001", 4)["coverage"]["evidence"] == "uncertain"      # still doubtful
    g.review_citation("K000001", "K000002", "confirmed", "checked p.4", reviewer="user")
    assert assess(g, "K000001", 4)["coverage"]["evidence"] == "complete"


def test_ai_labelled_link_off_the_shortest_route_is_advisory_not_lineage(tmp_path):
    g = _routes(tmp_path / "a.rl")
    try:
        g.conn.execute("MATCH (:Device {k:'K000011'})-[r:CITES]->(:Device {k:'K000012'}) "
                       "SET r.kind = 'mention', r.ai_label = 'predicate'")
        a = assess(g, "K000010", 2)
        assert a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["verdict_reason"].startswith("Provisional")
        assert a["coverage"]["doubtful_links"] == 0 and a["coverage"]["advisory_links_in_window"] == 1
        assert a["coverage"]["evidence"] == "partial"
        assert "advisory_links_pending_review" in a["coverage"]["evidence_reasons"]
    finally:
        g.close()


def test_mention_promoted_only_by_the_mcp_client_is_advisory(g):
    g.conn.execute("MATCH (:Device {k:'K000001'})-[r:CITES]->(:Device {k:'K000002'}) SET r.kind = 'mention'")
    g.review_citation("K000001", "K000002", "confirmed", None, reviewer="mcp-client")
    a = assess(g, "K000001", 4)
    assert "K000002" not in {x["k"] for x in a["ancestors"]}
    assert a["verdict"] == "INSUFFICIENT_LINEAGE" and "automated source" in a["verdict_reason"]
    adv = next(s for s in a["signals"] if s["code"] == "ADVISORY_LINK_PENDING_REVIEW")
    assert adv["evidence"][0]["basis"] == ["client_confirmation"] and adv["evidence"][0]["trust"] == "advisory"
