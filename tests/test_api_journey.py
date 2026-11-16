"""Full user journey through the HTTP API on a copy of the shipped Relate store,
plus pinned facts of the demo scenario (so a regression in extraction/queries is caught)."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(real_copy, monkeypatch):
    monkeypatch.setenv("FOREBEAR_DB", str(real_copy))
    from forebear import api
    importlib.reload(api)
    with TestClient(api.app) as c:
        yield c


def test_journey_search_assess_review_save(client):
    assert client.get("/api/health").json()["ok"]
    hits = client.get("/api/search", params={"q": "breathepal"}).json()
    assert hits[0]["k"] == "K252078"

    a = client.get("/api/assess/K252078").json()
    assert a["verdict"] == "REVIEW_LINEAGE"
    direct = [x for x in a["ancestors"] if x["gen"] == 1]
    assert [x["k"] for x in direct] == ["K113053"]                       # BiPAP A30
    hop = direct[0]["hops"][0]
    assert hop["page"] in (5, 6) and "predicate" in hop["snippet"].lower() and "BiPAP A30" in hop["snippet"]
    recall_ids = {e["id"] for s in a["signals"] for e in s["evidence"] if e.get("type") == "recall"}
    assert {"Z-1957-2021", "Z-1958-2021"} <= recall_ids                   # 2021 PE-PUR foam recall records
    assert a["memo"]["source"].startswith("deterministic")

    # human rejects the only predicate edge -> the lineage (and verdict) change immediately
    r = client.post("/api/citation/review", json={"src": "K252078", "dst": "K113053", "status": "rejected"})
    assert r.status_code == 200 and r.json()["review"] == "rejected"
    a2 = client.get("/api/assess/K252078").json()
    assert a2["ancestors"] == [] and a2["verdict"] == "INSUFFICIENT_LINEAGE"
    client.post("/api/citation/review", json={"src": "K252078", "dst": "K113053", "status": ""})
    assert client.get("/api/assess/K252078").json()["verdict"] == "REVIEW_LINEAGE"

    s = client.post("/api/assessments", json={"k": "K252078", "note": "demo"}).json()
    assert s["verdict"] == "REVIEW_LINEAGE" and "Z-1957-2021" in s["flagged_recalls"]
    hist = client.get("/api/assessments", params={"k": "K252078"}).json()
    assert hist[0]["id"] == s["id"] and "Analyst note: demo" in hist[0]["memo"]


def test_recall_reach_of_philips_foam_recall(client):
    r = client.get("/api/recall-event/88058").json()
    recalled = {x["k"] for x in r["recalled"]}
    assert {"K113053", "K131982", "K092818"} <= recalled and len(recalled) == 10
    after = {d["k"] for d in r["descendants"] if d["after_recall"]}
    assert {"K252078", "K251770"} <= after and len(after) == 7
    both = client.get("/api/recall-event/88058,88071").json()   # the same Philips recall, two openFDA events
    assert len(both["recalled"]) == 14 and len(both["descendants"]) == 19
    assert sum(d["after_recall"] for d in both["descendants"]) == 8


def test_watchlist_and_compare(client):
    w = client.get("/api/watchlist").json()
    assert w["count"] == 106 and w["direct"] == 62
    rows = client.post("/api/compare", json={"ks": ["K200480", "K113053", "K999999"]}).json()
    v = {r["k"]: r.get("verdict") for r in rows}
    assert v == {"K200480": "REVIEW_LINEAGE", "K113053": "DESIGN_RECALL_ON_FILE", "K999999": None}


def test_input_validation_and_missing(client):
    assert client.get("/api/assess/notak").status_code == 400
    assert client.get("/api/assess/K000001").status_code == 404
    assert client.get("/api/recall-event/abc").status_code == 400
    assert client.post("/api/citation/review", json={"src": "K252078", "dst": "K000001", "status": "confirmed"}).status_code == 404
    assert client.post("/api/citation/review", json={"src": "K252078", "dst": "K113053", "status": "maybe"}).status_code == 422
    assert client.post("/api/compare", json={"ks": []}).status_code == 422


def test_missing_store_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FOREBEAR_DB", str(tmp_path / "nope.rl"))
    from forebear import api
    importlib.reload(api)
    with TestClient(api.app) as c:
        r = c.get("/api/stats")
        assert r.status_code == 503 and "build_graph.py" in r.json()["detail"]


def test_saved_assessment_goes_stale_when_lineage_is_reviewed(client):
    s = client.post("/api/assessments", json={"k": "K252078"}).json()
    h = client.get("/api/assessments", params={"k": "K252078"}).json()[0]
    assert h["id"] == s["id"] and h["stale"] is False
    client.post("/api/citation/review", json={"src": "K113053", "dst": "K092818", "status": "rejected"})
    h = client.get("/api/assessments", params={"k": "K252078"}).json()[0]
    assert h["stale"] is True and "K113053->K092818" in h["changed_edges"]


def test_search_limit_is_validated(client):
    assert client.get("/api/search", params={"q": "cpap", "limit": -1}).status_code == 422
    assert client.get("/api/search", params={"q": "cpap", "limit": 5}).status_code == 200


def test_curated_reviews_and_name_flags_are_in_the_shipped_store(client):
    cits = {c["dst"]: c for c in client.get("/api/device/K120562").json()["citations"]}
    assert cits["K093416"]["review"] == "rejected" and cits["K093416"]["reviewer"] == "curated"
    assert cits["K093416"]["name_check"] == "mismatch"          # 'Profile Lite' text vs Trilogy 200 record
    a = client.get("/api/assess/K120562").json()
    assert "K093416" not in {x["k"] for x in a["ancestors"]}
    # the Airvo 3 reference-table edge is a reference, not a predicate
    airvo = {c["dst"]: c["kind"] for c in client.get("/api/device/K233643").json()["citations"]}
    assert airvo["K121623"] == "reference"


def test_flagged_links_in_lineage_are_surfaced(client):
    a = client.get("/api/assess/K120562").json()
    sig = [s for s in a["signals"] if s["code"] == "NAME_MISMATCH_IN_LINEAGE"]
    assert sig and any(e["dst"] == "K092043" for e in sig[0]["evidence"])
