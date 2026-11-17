"""Relate persistence for investigations.

    (:Investigation {id, created_at, updated_at, status, request, target_k, depth, mode, models, model_used,
                     steps, tool_calls, prompt_tokens, completion_tokens, error, verdict, evidence, stance,
                     report, report_md, generated_by, agent_version, resumed_from})
    (:ToolCall {id, investigation_id, seq, step, tool, args, ok, summary,
                result, result_complete, result_chars, result_omitted, result_sha256,     <- full internal result
                shown, shown_sha256, shown_truncated, shown_omitted,                    <- what the model saw
                duration_ms, at, rationale, model, origin})
    (:Finding {id, investigation_id, seq, kind, claim, status, reasons, evidence, certainty, origin,
               human_approved})
    (:Proposal {id, investigation_id, kind, k, src, dst, suggestion, reason, status, created_by, created_at,
                decided_by, decided_at, decision_note, result})

    (Investigation)-[:INVESTIGATES]->(Device)          the target
    (Investigation)-[:RAN {seq}]->(ToolCall)          the execution trace, in order
    (Investigation)-[:EXAMINED]->(Device|Recall)      everything a tool looked at (answers "who looked at X?")
    (Investigation)-[:FOUND]->(Finding)-[:REFERS_TO]->(Device|Recall)
    (Investigation)-[:PROPOSED]->(Proposal)-[:ABOUT]->(Device)
    (Investigation)-[:RESUMES]->(Investigation)

Everything here is machine-generated and labelled so (`generated_by`, `origin`, `human_approved: false`). These
writes never touch CITES edges, their review fields, or Assessment nodes.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from ..graph import Graph, _clean
from .tools import bound_result, canonical_json

SCHEMA = [
    "CREATE INDEX investigation_id IF NOT EXISTS FOR (i:Investigation) ON (i.id)",
    "CREATE INDEX toolcall_id IF NOT EXISTS FOR (t:ToolCall) ON (t.id)",
    "CREATE INDEX finding_id IF NOT EXISTS FOR (f:Finding) ON (f.id)",
    "CREATE INDEX proposal_id IF NOT EXISTS FOR (p:Proposal) ON (p.id)",
]
GENERATED_BY = "Forebear investigation agent (machine-generated, not human-reviewed)"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def ensure_schema(g: Graph) -> None:
    for s in SCHEMA:
        g.conn.execute(s)


def create(g: Graph, inv: dict) -> str:
    ensure_schema(g)
    g.conn.execute(
        """CREATE (i:Investigation {id:$id, created_at: datetime(), updated_at: datetime(), status:'queued',
                                   request:$request, target_k:$k, depth:$depth, mode:$mode, models:$models,
                                   steps:0, tool_calls:0, prompt_tokens:0, completion_tokens:0,
                                   generated_by:$gen, agent_version:$ver, resumed_from:$resumed})
        WITH i MATCH (d:Device {k:$k}) MERGE (i)-[:INVESTIGATES]->(d)""",
        {"id": inv["id"], "request": inv["request"], "k": inv["target_k"], "depth": inv["depth"],
         "mode": inv["mode"], "models": json.dumps(inv.get("models") or []), "gen": GENERATED_BY,
         "ver": inv["agent_version"], "resumed": inv.get("resumed_from")})
    if inv.get("resumed_from"):
        g.conn.execute("MATCH (i:Investigation {id:$id}) MATCH (o:Investigation {id:$o}) MERGE (i)-[:RESUMES]->(o)",
                       {"id": inv["id"], "o": inv["resumed_from"]})
    return inv["id"]


UPDATABLE = {"status", "mode", "model_used", "steps", "tool_calls", "prompt_tokens", "completion_tokens", "error",
             "verdict", "evidence", "stance", "report", "report_md", "models", "progress"}


def update(g: Graph, inv_id: str, **fields) -> None:
    bad = set(fields) - UPDATABLE
    if bad:
        raise ValueError(f"not updatable: {bad}")
    sets = ", ".join(f"i.{k} = ${k}" for k in fields)
    g.conn.execute(f"MATCH (i:Investigation {{id:$id}}) SET {sets}, i.updated_at = datetime()",
                   {"id": inv_id, **fields})


# A stored result larger than this is kept as a valid, structurally shortened JSON document with its omissions
# disclosed; result_sha256 and result_chars always describe the complete result, which a replay of the same call on
# the same store reproduces.
STORE_MAX_CHARS = 120_000


def stored_result(full) -> tuple[str, bool, list]:
    """(JSON text to store, complete?, omitted) for a tool's full result. Always valid JSON."""
    body = canonical_json(full)
    if len(body) <= STORE_MAX_CHARS:
        return body, True, []
    shown, omitted = bound_result(full, STORE_MAX_CHARS)
    return canonical_json(shown), False, omitted


def add_tool_call(g: Graph, inv_id: str, c: dict) -> str:
    tid = new_id("T")
    full = c["result"]
    shown = c.get("shown", full)
    body, complete, stored_omitted = stored_result(full)
    full_text = canonical_json(full)
    shown_text = canonical_json(shown)
    g.conn.execute(
        """MATCH (i:Investigation {id:$inv})
        CREATE (t:ToolCall {id:$id, investigation_id:$inv, seq:$seq, step:$step, tool:$tool, args:$args, ok:$ok,
                            summary:$summary, result:$result, result_complete:$complete, result_chars:$chars,
                            result_omitted:$r_omitted, result_sha256:$sha, shown:$shown, shown_sha256:$shown_sha,
                            shown_truncated:$shown_trunc, shown_omitted:$s_omitted, duration_ms:$ms, at: datetime(),
                            rationale:$why, model:$model, origin:$origin})
        CREATE (i)-[:RAN {seq:$seq}]->(t)""",
        {"inv": inv_id, "id": tid, "seq": c["seq"], "step": c["step"], "tool": c["tool"],
         "args": json.dumps(c["args"], default=str), "ok": c["ok"], "summary": c["summary"][:500],
         "result": body, "complete": complete, "chars": len(full_text),
         "r_omitted": canonical_json(stored_omitted), "sha": hashlib.sha256(full_text.encode()).hexdigest(),
         "shown": shown_text, "shown_sha": hashlib.sha256(shown_text.encode()).hexdigest(),
         "shown_trunc": bool(c.get("omitted")), "s_omitted": canonical_json(c.get("omitted") or []),
         "ms": c["duration_ms"], "why": (c.get("rationale") or "")[:600], "model": c.get("model"),
         "origin": c["origin"]})
    return tid


def save_outcome(g: Graph, inv_id: str, findings: list[dict], proposals: list[dict], examined: set[str],
                 origin: str) -> list[dict]:
    """Findings, proposals and EXAMINED links, written once at the end of a run."""
    ks = sorted(x for x in examined if x.startswith("K"))
    rs = sorted(x for x in examined if x.startswith("Z-"))
    g.conn.execute("MATCH (i:Investigation {id:$id}) UNWIND $ks AS k MATCH (d:Device {k:k}) MERGE (i)-[:EXAMINED]->(d)",
                   {"id": inv_id, "ks": ks})
    g.conn.execute("MATCH (i:Investigation {id:$id}) UNWIND $rs AS r MATCH (x:Recall {id:r}) MERGE (i)-[:EXAMINED]->(x)",
                   {"id": inv_id, "rs": rs})
    for n, f in enumerate(findings, 1):
        fid = new_id("F")
        g.conn.execute(
            """MATCH (i:Investigation {id:$inv})
            CREATE (f:Finding {id:$id, investigation_id:$inv, seq:$seq, kind:$kind, claim:$claim, status:$status,
                               reasons:$reasons, evidence:$evidence, certainty:$certainty, origin:$origin,
                               human_approved:false})
            CREATE (i)-[:FOUND]->(f)
            WITH f UNWIND $ks AS k MATCH (d:Device {k:k}) MERGE (f)-[:REFERS_TO]->(d)""",
            {"inv": inv_id, "id": fid, "seq": n, "kind": f.get("kind"), "claim": f["claim"], "status": f["status"],
             "reasons": json.dumps(f.get("reasons") or []), "evidence": json.dumps(f.get("evidence") or []),
             "certainty": f.get("certainty"), "origin": f.get("origin") or origin,
             "ks": sorted({e for e in f.get("refs", []) if e.startswith("K")})})
        g.conn.execute("MATCH (f:Finding {id:$id}) UNWIND $rs AS r MATCH (x:Recall {id:r}) MERGE (f)-[:REFERS_TO]->(x)",
                       {"id": fid, "rs": sorted({e for e in f.get("refs", []) if e.startswith("Z-")})})
        f["id"] = fid
    for p in proposals:
        pid = new_id("P")
        g.conn.execute(
            """MATCH (i:Investigation {id:$inv})
            CREATE (p:Proposal {id:$id, investigation_id:$inv, kind:$kind, k:$k, src:$src, dst:$dst,
                                suggestion:$sugg, reason:$reason, status:'pending_human_decision',
                                created_by:$by, created_at: datetime()})
            CREATE (i)-[:PROPOSED]->(p)
            WITH p UNWIND $ks AS k MATCH (d:Device {k:k}) MERGE (p)-[:ABOUT]->(d)""",
            {"inv": inv_id, "id": pid, "kind": p["kind"], "k": p.get("k"), "src": p.get("src"), "dst": p.get("dst"),
             "sugg": p.get("suggestion"), "reason": p.get("reason"), "by": p["created_by"],
             "ks": [x for x in (p.get("k"), p.get("src"), p.get("dst")) if x]})
        p["id"] = pid
    return findings


# ------------------------------------------------------------------ reads
FIELDS = ("id", "status", "request", "target_k", "depth", "mode", "model_used", "steps", "tool_calls",
          "prompt_tokens", "completion_tokens", "error", "verdict", "evidence", "stance", "generated_by",
          "agent_version", "resumed_from", "progress")


def get(g: Graph, inv_id: str) -> dict | None:
    rows = g.q("MATCH (i:Investigation {id:$id}) RETURN i {.*} AS i", {"id": inv_id})
    if not rows:
        return None
    i = _clean(rows[0]["i"])
    out = {k: i.get(k) for k in FIELDS} | {"created_at": i.get("created_at"), "updated_at": i.get("updated_at"),
                                            "models": json.loads(i.get("models") or "[]")}
    out["has_report"] = bool(i.get("report"))
    return out


def report(g: Graph, inv_id: str) -> tuple[dict | None, str | None]:
    rows = g.q("MATCH (i:Investigation {id:$id}) RETURN i.report AS r, i.report_md AS md", {"id": inv_id})
    if not rows or not rows[0]["r"]:
        return None, None
    return json.loads(rows[0]["r"]), rows[0]["md"]


def trace(g: Graph, inv_id: str, with_results: bool = False) -> list[dict]:
    rows = g.q("""MATCH (i:Investigation {id:$id})-[:RAN]->(t:ToolCall)
        RETURN t {.*} AS t ORDER BY t.seq""", {"id": inv_id})
    out = []
    for r in rows:
        t = _clean(r["t"])
        t["args"] = _parse(t.get("args")) or {}
        res, shown = t.pop("result", None), t.pop("shown", None)
        for key in ("result_omitted", "shown_omitted"):
            t[key] = _parse(t.get(key)) or []
        if t.get("result_complete") is None and res is not None:     # stored before this format: may be cut
            t["result_complete"] = _parse(res) is not None and len(res) < 12000
        if with_results:
            t["result"] = _parse(res, legacy=True)
            t["shown"] = _parse(shown, legacy=True)
        out.append(t)
    return out


def _parse(text: str | None, legacy: bool = False):
    """JSON from a stored property. Records written before results were bounded structurally may hold JSON cut at
    12,000 characters; they are returned as a disclosed, unparsed prefix instead of raising."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        if not legacy:
            return None
        return {"_unparseable_legacy_record": True, "_note": "stored by an earlier version that cut results at "
                "12,000 characters; replay the call to reproduce it (result_sha256 identifies the original)",
                "_prefix": str(text)[:2000]}


def findings(g: Graph, inv_id: str) -> list[dict]:
    rows = g.q("""MATCH (i:Investigation {id:$id})-[:FOUND]->(f:Finding)
        OPTIONAL MATCH (f)-[:REFERS_TO]->(x)
        RETURN f {.*} AS f, collect(coalesce(x.k, x.id)) AS refs ORDER BY f.seq""", {"id": inv_id})
    return [_clean(r["f"]) | {"reasons": json.loads(r["f"].get("reasons") or "[]"),
                              "evidence": json.loads(r["f"].get("evidence") or "[]"), "refs": r["refs"]} for r in rows]


def proposals(g: Graph, inv_id: str | None = None, status: str | None = None) -> list[dict]:
    rows = g.q("""MATCH (i:Investigation)-[:PROPOSED]->(p:Proposal)
        WHERE ($id IS NULL OR i.id = $id) AND ($st IS NULL OR p.status = $st)
        RETURN p {.*} AS p ORDER BY p.created_at DESC""", {"id": inv_id, "st": status})
    return [_clean(r["p"]) for r in rows]


def proposal(g: Graph, pid: str) -> dict | None:
    rows = g.q("MATCH (p:Proposal {id:$id}) RETURN p {.*} AS p", {"id": pid})
    return _clean(rows[0]["p"]) if rows else None


def claim_proposal(g: Graph, pid: str, reviewer: str) -> bool:
    """pending_human_decision -> deciding, in one statement (the caller is the single Relate thread)."""
    rows = g.q("""MATCH (p:Proposal {id:$id}) WHERE p.status = 'pending_human_decision'
                  SET p.status = 'deciding', p.decided_by = $who RETURN p.id AS id""", {"id": pid, "who": reviewer})
    return bool(rows)


def decide_proposal(g: Graph, pid: str, status: str, reviewer: str, note: str | None, result: dict | None) -> dict:
    g.conn.execute("""MATCH (p:Proposal {id:$id}) SET p.status = $st, p.decided_by = $who, p.decided_at = datetime(),
                      p.decision_note = $note, p.result = $res""",
                   {"id": pid, "st": status, "who": reviewer, "note": note,
                    "res": json.dumps(result, default=str) if result is not None else None})
    return proposal(g, pid)


def listing(g: Graph, k: str | None = None, limit: int = 30) -> list[dict]:
    """Investigations, newest first; with k, those that investigated or examined that device. `stale` is true
    when a citation in the target's ancestry was reviewed, AI-labelled or re-ingested after the run finished."""
    rows = g.q("""MATCH (i:Investigation)
        WHERE $k IS NULL OR EXISTS { MATCH (i)-[:INVESTIGATES|EXAMINED]->(:Device {k:$k}) }
        OPTIONAL MATCH (i)-[:INVESTIGATES]->(d:Device)
        OPTIONAL MATCH (d)-[:CITES*0..4]->(y:Device)-[c:CITES]->(:Device)
        WHERE c.reviewed_at > i.updated_at OR c.ai_at > i.updated_at
        WITH i, d, count(c) AS changed
        OPTIONAL MATCH (d)-[:CITES*0..4]->(z:Device) WHERE z.ingested_live_at > i.updated_at
        WITH i, changed, count(z) AS reingested
        OPTIONAL MATCH (i)-[:PROPOSED]->(p:Proposal {status:'pending_human_decision'})
        RETURN i.id AS id, toString(i.created_at) AS created_at, i.status AS status, i.target_k AS target_k,
               i.mode AS mode, i.model_used AS model_used, i.verdict AS verdict, i.evidence AS evidence,
               i.stance AS stance, i.request AS request, count(DISTINCT p) AS pending_proposals,
               (changed + reingested) > 0 AS stale
        ORDER BY created_at DESC LIMIT $n""", {"k": k, "n": limit})
    return rows


def mark_interrupted(g: Graph) -> int:
    """Runs left queued/running by a stopped server can no longer finish; they become resumable."""
    try:
        rows = g.q("""MATCH (i:Investigation) WHERE i.status IN ['queued', 'running']
            SET i.status = 'interrupted', i.updated_at = datetime() RETURN count(i) AS n""")
    except Exception:
        return 0
    return rows[0]["n"] if rows else 0
