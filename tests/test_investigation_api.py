"""Investigation endpoints (start, progress, trace, report, resume, proposals) on a copy of the shipped store,
and the MCP `investigate` tool over a live server. No network: runs are deterministic or use a scripted model."""
import importlib
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from tests.test_investigation import Scripted, tool_results


@pytest.fixture
def api_mod(real_copy, monkeypatch):
    monkeypatch.setenv("FOREBEAR_DB", str(real_copy))
    from forebear import api
    importlib.reload(api)
    return api


@pytest.fixture
def client(api_mod):
    with TestClient(api_mod.app) as c:
        yield c


def wait(client, inv_id, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = client.get(f"/api/investigations/{inv_id}").json()
        if s["status"] not in ("queued", "running") and not s["running_now"]:
            return s
        time.sleep(0.2)
    raise AssertionError(f"{inv_id} did not finish: {s}")


def test_start_poll_trace_report(client):
    r = client.post("/api/investigations", json={"request": "Investigate K201620 and trace recalled predicates",
                                                 "mode": "deterministic"})
    assert r.status_code == 202 and r.json()["target_k"] == "K201620"
    inv = r.json()["id"]
    s = wait(client, inv)
    assert s["status"] == "completed" and s["mode"] == "deterministic_fallback" and s["verdict"] == "REVIEW_LINEAGE"
    tr = client.get(f"/api/investigations/{inv}/trace").json()
    assert tr[0]["tool"] == "check_predicate" and all("result" not in t for t in tr)
    assert "result" in client.get(f"/api/investigations/{inv}/trace", params={"results": True}).json()[0]
    rep = client.get(f"/api/investigations/{inv}/report").json()
    assert rep["conclusion"]["source"].startswith("deterministic") and "not a medical-device safety" in rep["disclaimer"]
    md = client.get(f"/api/investigations/{inv}/report", params={"format": "markdown"})
    assert md.headers["content-type"].startswith("text/markdown") and "NOT an autonomous LLM" in md.text
    assert [x["id"] for x in client.get("/api/investigations", params={"k": "K131982"}).json()] == [inv]
    assert client.get("/api/investigations/I-000000000000").status_code == 404
    assert client.get("/api/investigations/../etc").status_code in (400, 404)
    assert client.post("/api/investigations", json={"request": "no target here"}).status_code == 400
    assert client.post("/api/investigations", json={"request": "Investigate K999999"}).status_code == 404
    # existing endpoints still behave as before
    assert client.get("/api/assess/K252078").json()["verdict"] == "REVIEW_LINEAGE"


def test_auto_without_inference_is_labelled_fallback(real_copy, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    monkeypatch.setenv("FOREBEAR_DB", str(real_copy))
    from forebear import api
    importlib.reload(api)
    with TestClient(api.app) as c:
        inv = c.post("/api/investigations", json={"request": "Investigate K252078", "depth": 2}).json()["id"]
        s = wait(c, inv)
        assert s["mode"] == "deterministic_fallback"
        assert "NVIDIA inference unavailable" in c.get(f"/api/investigations/{inv}/report").json()["mode_note"]


def proposing_policy(turn, messages):
    seen = tool_results(messages)
    if turn == 1:
        return [("coverage_gaps", {"k_number": "K252078", "generations": 4}),
                ("list_citations", {"k_number": "K252078"})]
    if turn == 2:
        unread = next(u["k"] for u in seen[-2]["unread_ancestors"])
        return [("propose_ingest", {"k_number": unread, "reason": "unread ancestor"}),
                ("propose_link_review", {"citing_k": "K252078", "cited_k": "K113053", "suggestion": "needs_review",
                                         "reason": "only predicate link; confirm against page 5-6"})]
    return [("submit_report", {"summary": "s", "findings": [
        {"claim": "K252078 has unread ancestors, so its lineage evidence is incomplete.", "evidence": ["K252078"]}]})]


def test_proposals_need_a_named_person_and_never_change_lineage(api_mod, client, monkeypatch):
    class Factory:
        @staticmethod
        def from_env(models=None, timeout=90):
            return Scripted(proposing_policy)
    monkeypatch.setattr(api_mod.inv_runner, "ChatClient", Factory)
    inv = client.post("/api/investigations", json={"request": "Investigate K252078", "k": "K252078"}).json()["id"]
    s = wait(client, inv)
    assert s["status"] == "completed" and s["mode"] == "llm_agent"
    ps = {p["kind"]: p for p in client.get("/api/proposals", params={"investigation": inv}).json()}
    assert set(ps) == {"ingest_clearance", "link_review"}
    link, ing = ps["link_review"], ps["ingest_clearance"]
    assert client.get("/api/investigations", params={"k": "K252078"}).json()[0]["pending_proposals"] == 2

    url = f"/api/proposals/{link['id']}/decision"
    for bad in ({"decision": "approve", "reviewer": "investigation agent", "human": True},
                {"decision": "approve", "reviewer": "nemotron", "human": True},
                {"decision": "approve", "reviewer": "Jane Doe", "human": False},
                {"decision": "approve", "reviewer": "mcp-client", "human": True}):
        assert client.post(url, json=bad).status_code == 403
    r = client.post(url, json={"decision": "approve", "reviewer": "Jane Doe", "human": True, "note": "will check"})
    assert r.status_code == 200 and r.json()["status"] == "acknowledged" and r.json()["decided_by"] == "Jane Doe"
    cit = next(c for c in client.get("/api/device/K252078").json()["citations"] if c["dst"] == "K113053")
    assert cit["review"] is None and cit["reviewer"] is None             # approving did not review the link
    assert client.post(url, json={"decision": "dismiss", "reviewer": "Jane Doe", "human": True}).status_code == 409

    from forebear.ingest import IngestError

    def offline(k):
        raise IngestError("offline in tests")
    monkeypatch.setattr(api_mod.ingest_mod, "fetch_clearance", offline)
    r = client.post(f"/api/proposals/{ing['id']}/decision", json={"decision": "approve", "reviewer": "Jane Doe",
                                                                  "human": True})
    assert r.json()["status"] == "failed" and "offline" in r.json()["result"]
    assert client.get("/api/proposals", params={"status": "pending_human_decision"}).json() == []


def test_resume_creates_a_linked_run(client):
    first = client.post("/api/investigations", json={"request": "Investigate K251770", "mode": "deterministic",
                                                     "depth": 2}).json()["id"]
    wait(client, first)
    r = client.post(f"/api/investigations/{first}/resume", json={"mode": "deterministic"})
    assert r.status_code == 202 and r.json()["resumed_from"] == first
    second = r.json()["id"]
    s = wait(client, second)
    assert s["resumed_from"] == first and s["status"] == "completed"
    tr = client.get(f"/api/investigations/{second}/trace").json()
    assert tr[0]["origin"] == "resume_replay"
    assert not any(t["origin"] == "deterministic_fallback" and t["tool"] == "check_predicate" for t in tr)


def test_concurrency_limit(api_mod, client):
    api_mod._running.update({"I-aaaaaaaaaaaa", "I-bbbbbbbbbbbb"})
    try:
        r = client.post("/api/investigations", json={"request": "Investigate K252078", "mode": "deterministic"})
        assert r.status_code == 429
    finally:
        api_mod._running.clear()


def test_mcp_investigate_tool(live_api):
    from tests.test_mcp import INIT, rpc_session
    res = rpc_session([sys.executable, "-m", "forebear.mcp_server"], INIT + [
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "investigate", "arguments": {
            "request": "Investigate K252078 and its recalled predicates", "mode": "deterministic", "generations": 2}}},
    ], env=live_api, timeout=180)
    assert {"investigate", "get_investigation"} <= {t["name"] for t in res[2]["result"]["tools"]}
    out = json.loads(res[3]["result"]["content"][0]["text"])
    rep = out["report"]
    assert out["status"]["status"] == "completed" and rep["conclusion"]["verdict"] == "REVIEW_LINEAGE"
    assert rep["mode"] == "deterministic_fallback" and rep["recall_totals"]["records_within_two_generations"] > 0
