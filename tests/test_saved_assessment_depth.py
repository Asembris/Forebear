"""A saved assessment keeps the query depth it was computed at: history recomputes its verdict and checks staleness
at that depth, so an unchanged graph never makes it stale, while a change to evidence that depth reads still does.

Tiny graph lineage used here: K000004 -> K000003 -> K000002 (design-related Class I recall) -> K000001, and
K000004 -> K000008. At depth 1 K000004 reports no signal; from depth 2 the recall makes it REVIEW_LINEAGE.
"""
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from conftest import build_tiny
from forebear.lineage import assess

K = "K000004"


def _legacy(g, aid, verdict, payload):
    """An assessment node as saved before depth was stored on it."""
    g.conn.execute("""MATCH (d:Device {k:$k})
        CREATE (a:Assessment {id:$id, created_at: datetime(), target_k:$k, verdict:$v, payload:$p,
                              memo:'m', memo_source:'template'})-[:ASSESSED]->(d)""",
                   {"k": K, "id": aid, "v": verdict, "p": payload})


@pytest.fixture
def tiny_api(tmp_path, monkeypatch):
    path = tmp_path / "tiny.rl"
    g = build_tiny(path)
    assert [assess(g, K, d)["verdict"] for d in (1, 2, 4)] == \
        ["NO_DESIGN_RECALL_SIGNAL", "REVIEW_LINEAGE", "REVIEW_LINEAGE"]
    _legacy(g, "A-legacy-p1", "NO_DESIGN_RECALL_SIGNAL", json.dumps({"verdict": "NO_DESIGN_RECALL_SIGNAL", "depth": 1}))
    _legacy(g, "A-legacy-none", "REVIEW_LINEAGE", json.dumps({"verdict": "REVIEW_LINEAGE"}))
    _legacy(g, "A-legacy-bad", "REVIEW_LINEAGE", "not json")
    g.close()
    monkeypatch.setenv("FOREBEAR_DB", str(path))
    from forebear import api
    importlib.reload(api)
    with TestClient(api.app) as c:
        yield c, path


def _history(c):
    return {h["id"]: h for h in c.get("/api/assessments", params={"k": K}).json()}


def _save(c, depth):
    r = c.post("/api/assessments", json={"k": K, "depth": depth})
    assert r.status_code == 200
    return r.json()


def test_each_depth_is_saved_and_unchanged_graph_is_not_stale(tiny_api):
    c, _ = tiny_api
    saved = {d: _save(c, d) for d in (1, 2, 4)}
    assert {d: (s["depth"], s["verdict"]) for d, s in saved.items()} == {
        1: (1, "NO_DESIGN_RECALL_SIGNAL"), 2: (2, "REVIEW_LINEAGE"), 4: (4, "REVIEW_LINEAGE")}
    h = _history(c)
    for d, s in saved.items():
        row = h[s["id"]]
        assert (row["depth"], row["depth_source"]) == (d, "recorded")
        # recomputed at its own depth: the depth-1 verdict is not compared with the depth-4 one
        assert row["verdict_now"] == row["verdict"] == s["verdict"]
        assert row["stale"] is False and row["changed_edges"] == [] and row["reingested"] == []


def test_depth_is_stored_on_the_assessment_node(tiny_api):
    c, _ = tiny_api
    ids = {_save(c, d)["id"]: d for d in (1, 2, 4)}
    from forebear import api                 # the API is the single writer: read through its store and thread
    rows = c.portal.call(api.run, lambda g: g.q(
        "MATCH (a:Assessment) WHERE a.id IN $ids RETURN a.id AS id, a.depth AS depth, a.payload AS p",
        {"ids": list(ids)}))
    assert {r["id"]: r["depth"] for r in rows} == ids
    assert {r["id"]: json.loads(r["p"])["depth"] for r in rows} == ids


def test_a_change_within_the_saved_depth_makes_it_stale_and_one_beyond_does_not(tiny_api):
    c, _ = tiny_api
    ids = {d: _save(c, d)["id"] for d in (1, 2, 4)}
    # K000002 -> K000001 leaves the generation-2 ancestor: read at depth 2 and 4, not at depth 1
    assert c.post("/api/citation/review", json={"src": "K000002", "dst": "K000001", "status": "confirmed"}).status_code == 200
    h = _history(c)
    assert h[ids[1]]["stale"] is False and h[ids[1]]["changed_edges"] == []
    for d in (2, 4):
        assert h[ids[d]]["stale"] is True and h[ids[d]]["changed_edges"] == ["K000002->K000001"]
        assert h[ids[d]]["verdict_now"] == h[ids[d]]["verdict"]


def test_a_relevant_citation_change_flags_every_depth_and_reports_the_new_verdict(tiny_api):
    c, _ = tiny_api
    ids = {d: _save(c, d)["id"] for d in (1, 2, 4)}
    # rejecting the direct predicate removes the whole ancestry: relevant at every depth
    assert c.post("/api/citation/review", json={"src": K, "dst": "K000003", "status": "rejected"}).status_code == 200
    h = _history(c)
    for d in (1, 2, 4):
        assert h[ids[d]]["stale"] is True and f"{K}->K000003" in h[ids[d]]["changed_edges"]
        assert h[ids[d]]["verdict_now"] == assess_now(c, d)
    assert h[ids[2]]["verdict_now"] != h[ids[2]]["verdict"]
    assert h[ids[4]]["verdict_now"] != h[ids[4]]["verdict"]


def assess_now(c, depth):
    return c.get(f"/api/assess/{K}", params={"depth": depth}).json()["verdict"]


def test_legacy_assessments_use_the_payload_depth_or_the_old_default(tiny_api):
    c, _ = tiny_api
    h = _history(c)
    # saved before depth was stored: the payload records the depth its verdict was computed at
    assert (h["A-legacy-p1"]["depth"], h["A-legacy-p1"]["depth_source"]) == (1, "legacy_payload")
    assert h["A-legacy-p1"]["verdict_now"] == "NO_DESIGN_RECALL_SIGNAL" and h["A-legacy-p1"]["stale"] is False
    # no depth anywhere (or an unreadable payload): the API default the assessment was saved with
    for aid in ("A-legacy-none", "A-legacy-bad"):
        assert (h[aid]["depth"], h[aid]["depth_source"]) == (4, "legacy_default")
        assert h[aid]["verdict_now"] == "REVIEW_LINEAGE" and h[aid]["stale"] is False
    # and genuine changes still flag legacy records, scoped to their depth
    c.post("/api/citation/review", json={"src": "K000002", "dst": "K000001", "status": "confirmed"})
    h = _history(c)
    assert h["A-legacy-p1"]["stale"] is False
    assert h["A-legacy-none"]["stale"] is True and h["A-legacy-bad"]["stale"] is True


def test_depth_parsing_falls_back_safely():
    from forebear.graph import _assessment_depth
    assert _assessment_depth(2) == (2, True)
    assert _assessment_depth("3") == (3, True)
    assert _assessment_depth(0) == (1, True) and _assessment_depth(99) == (8, True)
    for bad in (None, True, "x", [], {}, float("inf")):
        assert _assessment_depth(bad) == (4, False)
