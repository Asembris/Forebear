"""Forebear MCP server (stdio transport, newline-delimited JSON-RPC 2.0, no SDK dependency).

Gives any MCP host (Claude Code, Cursor, Codex, ...) the *domain* tools of the predicate
due-diligence workflow. It talks to the running Forebear API, so the API process stays the
single Relate writer and every agent action (ingest, review, save) lands in the same graph
the UI shows. For raw Cypher, pair it with Relate's own server:
    tools/relate.exe serve --database data/forebear.rl --mcp stdio --read-only

    python -m forebear.mcp_server            # FOREBEAR_URL defaults to http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import os
import sys

import httpx

PROTOCOL = "2025-06-18"
BASE = os.environ.get("FOREBEAR_URL", "http://127.0.0.1:8765")

K = {"type": "string", "pattern": "^[Kk][0-9]{6}$", "description": "510(k) number, e.g. K252078"}
TOOLS = [
    {"name": "search_devices", "description": "Find 510(k) devices in the Forebear graph by name, company or K-number prefix.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "check_predicate",
     "description": "Predicate due-diligence check for one cleared device: verdict (DESIGN_RECALL_ON_FILE / REVIEW_LINEAGE / INSUFFICIENT_LINEAGE / NO_DESIGN_RECALL_SIGNAL), "
                    "recall signals in its predicate ancestry with the citation chain and evidence, coverage gaps, and "
                    "a deterministic note. Use before proposing a device as a 510(k) predicate.",
     "inputSchema": {"type": "object", "properties": {"k_number": K, "generations": {"type": "integer", "minimum": 1, "maximum": 6}},
                     "required": ["k_number"]}},
    {"name": "compare_predicates", "description": "Compare up to 8 candidate predicates side by side.",
     "inputSchema": {"type": "object", "properties": {"k_numbers": {"type": "array", "items": K, "minItems": 1, "maxItems": 8}},
                     "required": ["k_numbers"]}},
    {"name": "recall_reach", "description": "For an FDA recall event number, list recalled clearances and every later device "
                                            "descending from them, split by cleared before/after the recall began.",
     "inputSchema": {"type": "object", "properties": {"event": {"type": "string", "pattern": "^[0-9]+$"}}, "required": ["event"]}},
    {"name": "list_citations", "description": "What a device's 510(k) summary cites (predicate / reference / mention), with page and snippet.",
     "inputSchema": {"type": "object", "properties": {"k_number": K}, "required": ["k_number"]}},
    {"name": "ingest_clearance", "description": "Fetch a 510(k) from FDA (openFDA + summary PDF), extract its predicates and recalls, "
                                                "and MERGE it into the graph. Also extends lineage for a device whose summary was unread.",
     "inputSchema": {"type": "object", "properties": {"k_number": K}, "required": ["k_number"]}},
    {"name": "review_citation", "description": "Record a human-verified judgement on an extracted citation edge: confirmed, rejected, "
                                               "or '' to clear. Rejected edges stop counting in every lineage query. Recorded with reviewer "
                                               "'mcp-client': a confirmation made here does not clear uncertain-evidence flags, "
                                               "which only a person's review in the app does.",
     "inputSchema": {"type": "object", "properties": {"src": K, "dst": K, "status": {"type": "string", "enum": ["confirmed", "rejected", ""]},
                                                      "note": {"type": "string"}}, "required": ["src", "dst", "status"]}},
    {"name": "save_assessment", "description": "Persist the current check as an (:Assessment) node linked to the device and its flagged recalls.",
     "inputSchema": {"type": "object", "properties": {"k_number": K, "note": {"type": "string"}}, "required": ["k_number"]}},
]


def _http(method: str, path: str, **kw):
    r = httpx.request(method, BASE + path, timeout=90, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {"detail": r.text[:300]}
    if r.status_code >= 400:
        raise RuntimeError(data.get("detail") if isinstance(data, dict) else str(data))
    return data


def _compact_assessment(a: dict) -> dict:
    return {
        "k": a["k"], "name": a["device"].get("name"), "applicant": a["device"].get("applicant"),
        "decision_date": a["device"].get("decision_date"), "verdict": a["verdict"], "why": a["verdict_reason"],
        "signals": [{"code": s.get("code"), "severity": s["severity"], "title": s["title"], "chain": s.get("chain"),
                     "recalls": [{k: e.get(k) for k in ("id", "classification", "root_cause", "initiated", "url")}
                                 for e in s["evidence"] if e.get("type") == "recall"][:5],
                     "citation_evidence": [{k: e.get(k) for k in ("src", "dst", "page", "snippet", "source_url",
                                                                 "name_check", "audit", "audit_note", "doubt")}
                                           for e in s["evidence"] if e.get("type") == "citation"],
                     "unresolved_citations": [{k: e.get(k) for k in ("src", "cited", "reason", "page", "quote")}
                                              for e in s["evidence"] if e.get("type") == "unresolved_citation"]}
                    for s in a["signals"]],
        "coverage": a["coverage"], "note": a["memo"],
    }


def call_tool(name: str, args: dict):
    up = lambda k: str(k).strip().upper()  # noqa: E731
    if name == "search_devices":
        return _http("GET", "/api/search", params={"q": args["query"]})
    if name == "check_predicate":
        return _compact_assessment(_http("GET", f"/api/assess/{up(args['k_number'])}",
                                         params={"depth": int(args.get("generations", 4))}))
    if name == "compare_predicates":
        return _http("POST", "/api/compare", json={"ks": [up(k) for k in args["k_numbers"]]})
    if name == "recall_reach":
        return _http("GET", f"/api/recall-event/{args['event']}")
    if name == "list_citations":
        return _http("GET", f"/api/device/{up(args['k_number'])}")["citations"]
    if name == "ingest_clearance":
        r = _http("POST", "/api/ingest", json={"k": up(args["k_number"])})
        return {k: r[k] for k in ("k", "was_present", "summary_status", "summary_url", "new_devices",
                                  "recalls_linked", "extraction")} | {
            "citations_added": [{k: c[k] for k in ("dst", "kind", "page", "snippet")} for c in r["citations_added"]]}
    if name == "review_citation":
        return _http("POST", "/api/citation/review", json={"src": up(args["src"]), "dst": up(args["dst"]),
                                                           "status": args["status"], "note": args.get("note"),
                                                           "via": "mcp-client"})
    if name == "save_assessment":
        return _http("POST", "/api/assessments", json={"k": up(args["k_number"]), "note": args.get("note")})
    raise KeyError(name)


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:                       # notification (e.g. notifications/initialized)
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "forebear", "version": "0.1.0"},
                  "instructions": "Predicate due-diligence over FDA 510(k) lineage stored in Relate. Verdicts are "
                                  "documentation signals, not safety findings; always cite recall ids and K-numbers."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            out = call_tool(p.get("name"), p.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "isError": False}
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {p.get('name')}"}}
        except Exception as e:            # API down, validation error, FDA unreachable
            result = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
