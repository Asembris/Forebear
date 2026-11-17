"""Agent access: the Forebear MCP server over a live API, and Relate's own MCP server
(read-only Cypher) over the same store. Both use the real stdio transport."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RELATE = ROOT / "tools" / "relate.exe"


def rpc_session(cmd, messages, env=None, timeout=60):
    lines = "\n".join(json.dumps(m) for m in messages) + "\n"
    p = subprocess.run(cmd, input=lines, capture_output=True, text=True, timeout=timeout, cwd=ROOT, env=env)
    return {r["id"]: r for r in (json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")) if "id" in r}


INIT = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"}]


def test_forebear_mcp_agent_workflow(live_api):
    call = lambda i, name, args: {"jsonrpc": "2.0", "id": i, "method": "tools/call",  # noqa: E731
                                  "params": {"name": name, "arguments": args}}
    res = rpc_session([sys.executable, "-m", "forebear.mcp_server"], INIT + [
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        call(3, "check_predicate", {"k_number": "k252078"}),
        call(4, "review_citation", {"src": "K252078", "dst": "K113053", "status": "confirmed", "note": "checked p.5"}),
        call(5, "save_assessment", {"k_number": "K252078", "note": "agent run"}),
        call(6, "check_predicate", {"k_number": "K1"}),
        {"jsonrpc": "2.0", "id": 7, "method": "nope"},
    ], env=live_api)
    assert res[1]["result"]["serverInfo"]["name"] == "forebear"
    assert {t["name"] for t in res[2]["result"]["tools"]} >= {"check_predicate", "ingest_clearance", "review_citation"}
    a = json.loads(res[3]["result"]["content"][0]["text"])
    assert a["verdict"] == "REVIEW_LINEAGE" and a["signals"][0]["chain"] == ["K252078", "K113053"]
    assert json.loads(res[4]["result"]["content"][0]["text"])["review"] == "confirmed"
    # the write is attributed to the MCP client, so it does not count as a person's confirmation
    import httpx
    cits = httpx.get(live_api["FOREBEAR_URL"] + "/api/device/K252078").json()["citations"]
    assert next(c for c in cits if c["dst"] == "K113053")["reviewer"] == "mcp-client"
    assert json.loads(res[5]["result"]["content"][0]["text"])["id"].startswith("A-")
    assert res[6]["result"]["isError"] is True
    assert res[7]["error"]["code"] == -32601


@pytest.mark.skipif(not RELATE.exists(), reason="Relate CLI not installed in tools/")
def test_relate_native_mcp_read_cypher(real_copy):
    res = rpc_session([str(RELATE), "serve", "--database", str(real_copy), "--mcp", "stdio", "--read-only"], INIT + [
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "read_cypher", "arguments": {
            "statement": "MATCH (:Device {k:$k})-[:CITES]->(p)-[:SUBJECT_OF]->(r:Recall {event:'88058'}) RETURN p.k AS p, count(r) AS n",
            "parameters": {"k": "K252078"}}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "read_cypher", "arguments": {
            "statement": "CREATE (:Device {k:'K000000'})"}}},
    ])
    body = json.loads(res[2]["result"]["content"][0]["text"])
    assert body["rows"] == [{"p": "K113053", "n": 1}]                # Z-1973-2021 (event 88058; Z-1957/1958 are event 88071)
    assert res[3]["result"]["isError"] is True                      # writes refused on the read-only surface
