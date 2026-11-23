"""FastAPI backend. Every graph call runs on ONE dedicated worker thread that owns the
Relate connection (Relate connections are thread-affine; one writer per store).

    uvicorn forebear.api:app --port 8765
"""
from __future__ import annotations

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent
from .config import DB_PATH, NOT_A_PERSON, ROOT, use_live_cache
from .graph import Graph, open_graph
from . import ingest as ingest_mod
from .ingest import IngestError
from .investigation import runner as inv_runner
from .investigation import store as inv_store
from .lineage import assess, compare, recall_reach

agent.load_env()
use_live_cache()          # live ingests never touch the committed data/raw cache
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="relate")
_graph: Graph | None = None
# Investigations run on their own small pool; their graph work is sent to the Relate thread like everything else.
MAX_CONCURRENT_INVESTIGATIONS = 2
_inv_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_INVESTIGATIONS, thread_name_prefix="investigation")
_running: set[str] = set()


def _db_path() -> Path:
    return Path(os.environ.get("FOREBEAR_DB", DB_PATH))


def _open() -> None:
    global _graph
    p = _db_path()
    if not p.exists():
        raise RuntimeError(f"Relate store not found at {p}. Run: python scripts/build_graph.py")
    _graph = open_graph(p)
    inv_store.mark_interrupted(_graph)       # runs a previous server process left unfinished


def _graph_sync(fn):
    """fn(graph) on the Relate thread, called from a worker thread (the investigation pool)."""
    def call():
        if _closing:
            raise RuntimeError("server is shutting down")
        if _graph is None:
            _open()
        return fn(_graph)
    return _executor.submit(call).result()


_closing = False


async def run(fn, *args, **kw):
    """Execute fn(graph, ...) on the Relate thread."""
    loop = asyncio.get_running_loop()

    def call():
        if _graph is None:
            _open()
        return fn(_graph, *args, **kw)
    return await loop.run_in_executor(_executor, call)


app = FastAPI(title="Forebear", version="0.1.0")


@app.on_event("shutdown")
def _shutdown() -> None:
    global _closing
    _closing = True
    _inv_pool.shutdown(wait=False, cancel_futures=True)

    def close():
        global _graph
        if _graph is not None:
            _graph.close()
            _graph = None
    _executor.submit(close).result()


@app.exception_handler(RuntimeError)
async def _runtime(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


def _norm_k(k: str) -> str:
    k = k.strip().upper()
    if not (len(k) == 7 and k[0] == "K" and k[1:].isdigit()):
        raise HTTPException(400, "Expected a 510(k) number like K252078")
    return k


# ---------------------------------------------------------------- reads
@app.get("/api/health")
async def health():
    s = await run(lambda g: g.stats())
    return {"ok": True, "db": str(_db_path()), "stats": s}


@app.get("/api/stats")
async def stats():
    return await run(lambda g: g.stats())


@app.get("/api/search")
async def search(q: str, limit: int = Query(12, ge=1, le=50)):
    return await run(lambda g: g.search(q, min(limit, 50)))


@app.get("/api/device/{k}")
async def device(k: str):
    k = _norm_k(k)
    d = await run(lambda g: g.device(k))
    if d is None:
        raise HTTPException(404, f"{k} is not in the graph. Use 'Add a clearance' to ingest it.")
    cits = await run(lambda g: g.direct_citations(k))
    return {**d, "citations": cits}


@app.get("/api/assess/{k}")
async def assess_ep(k: str, depth: int = 4):
    k = _norm_k(k)
    a = await run(lambda g: assess(g, k, max(1, min(depth, 6))))
    if a is None:
        raise HTTPException(404, f"{k} is not in the graph. Use 'Add a clearance' to ingest it.")
    a["memo"] = agent.template_memo(a)
    a["citations"] = await run(lambda g: g.direct_citations(k))
    return a


class CompareIn(BaseModel):
    ks: list[str] = Field(min_length=1, max_length=8)
    depth: int = 4


@app.post("/api/compare")
async def compare_ep(body: CompareIn):
    ks = [_norm_k(k) for k in body.ks]
    return await run(lambda g: compare(g, ks, max(1, min(body.depth, 6))))


@app.get("/api/recall-event/{event}")
async def recall_event(event: str, depth: int = 3):
    if not all(e.strip().isdigit() for e in event.split(",")) or event.count(",") > 9:
        raise HTTPException(400, "Recall event numbers are numeric, e.g. 88058 or 88058,88071")
    return await run(lambda g: recall_reach(g, event, depth))


@app.get("/api/watchlist")
async def watchlist(design_only: bool = True):
    rows = await run(lambda g: g.cited_after_recall(design_only, limit=5000))
    by: dict[str, dict] = {}
    for r in rows:
        d = by.setdefault(r["k"], {"k": r["k"], "name": r["name"], "applicant": r["applicant"],
                                   "decision_date": r["decision_date"], "received_date": r["received_date"],
                                   "min_gen": r["gen"], "supported_min_gen": None, "recall_count": 0,
                                   "ancestors": set(), "events": set(), "recalls": []})
        d["min_gen"] = min(d["min_gen"], r["gen"])
        d["recall_count"] += 1
        if not r["conditional"]:        # a route that does not rest on an unresolved citation
            sg = d["supported_min_gen"]
            d["supported_min_gen"] = r["gen"] if sg is None else min(sg, r["gen"])
        d["ancestors"].add(r["ancestor"])
        d["events"].add(r["event"])
        if len(d["recalls"]) < 6:
            d["recalls"].append({k: r[k] for k in ("recall_id", "ancestor", "gen", "conditional", "classification",
                                                   "root_cause", "initiated", "firm", "url")})
    out = sorted(by.values(), key=lambda d: d["decision_date"] or "", reverse=True)
    for d in out:
        d["ancestors"] = sorted(d["ancestors"])
        d["events"] = sorted(e for e in d["events"] if e)
        # computed over every recall route, not the first six listed: conditional only if none is supported
        d["conditional"] = d["supported_min_gen"] is None
    return {"count": len(out), "direct": sum(1 for d in out if d["min_gen"] == 1),
            "direct_supported": sum(1 for d in out if d["supported_min_gen"] == 1),
            "conditional": sum(1 for d in out if d["conditional"]), "rows": out}


@app.get("/api/assessments")
async def list_assessments(k: str | None = None):
    kk = _norm_k(k) if k else None

    def do(g: Graph):
        rows = g.assessments(kk)
        verdicts: dict[str, str | None] = {}
        for r in rows:              # does the graph still give the saved verdict?
            if r["k"] not in verdicts:
                cur = assess(g, r["k"])
                verdicts[r["k"]] = cur["verdict"] if cur else None
            r["verdict_now"] = verdicts[r["k"]]
            r["stale"] = bool(r["stale"] or r["verdict_now"] != r["verdict"])
        return rows
    return await run(do)


# ---------------------------------------------------------------- writes
class IngestIn(BaseModel):
    k: str


@app.post("/api/ingest")
async def ingest(body: IngestIn):
    k = _norm_k(body.k)
    loop = asyncio.get_running_loop()
    try:
        # network phases run off the Relate thread, so the UI stays responsive during a PDF download
        existing = await run(lambda g: g.device(k))
        fetched = await loop.run_in_executor(None, ingest_mod.fetch_clearance, k)
        present = await run(lambda g: ingest_mod.present_devices(g, fetched.cited))
        related = await loop.run_in_executor(None, ingest_mod.fetch_related, fetched, present)
        return await run(lambda g: ingest_mod.write(g, fetched, related, existing))
    except IngestError as e:
        raise HTTPException(422, str(e))


class ReviewIn(BaseModel):
    src: str
    dst: str
    status: str = Field(pattern="^(confirmed|rejected|)$")
    note: str | None = None
    # Who recorded it: "user" (the app) or "mcp-client" (the MCP tool, possibly an AI agent). Optional.
    via: str = Field("user", pattern="^(user|mcp-client)$")


@app.post("/api/citation/review")
async def review(body: ReviewIn):
    src, dst = _norm_k(body.src), _norm_k(body.dst)
    r = await run(lambda g: g.review_citation(src, dst, body.status, body.note, reviewer=body.via))
    if r is None:
        raise HTTPException(404, f"No citation {src} -> {dst}")
    return r


class TriageIn(BaseModel):
    src: str
    dst: str


@app.post("/api/citation/triage")
async def triage(body: TriageIn):
    src, dst = _norm_k(body.src), _norm_k(body.dst)
    c = await run(lambda g: g.citation(src, dst))
    if c is None:
        raise HTTPException(404, f"No citation {src} -> {dst}")
    loop = asyncio.get_running_loop()
    res = await loop.run_in_executor(None, agent.triage_citation, src, dst, c["snippet"] or "")
    if not res["ok"]:
        raise HTTPException(502, f"LLM triage unavailable: {res['error']}. The citation is unchanged.")
    saved = await run(lambda g: g.set_triage(src, dst, res["label"], res["quote"], res["model"]))
    return {**saved, "quote": res["quote"], "model": res["model"], "seconds": res["seconds"]}


class SaveIn(BaseModel):
    k: str
    depth: int = 4
    note: str | None = None


@app.post("/api/assessments")
async def save(body: SaveIn):
    k = _norm_k(body.k)

    def do(g: Graph):
        a = assess(g, k, max(1, min(body.depth, 6)))
        if a is None:
            return None
        memo = agent.template_memo(a)
        text = memo["headline"] + "\n" + "\n".join(p["text"] for p in memo["paragraphs"])
        if body.note:
            text += "\nAnalyst note: " + body.note.strip()[:1000]
        flagged = sorted({e["id"] for s in a["signals"] if s["severity"] in ("high", "medium")
                          for e in s["evidence"] if e.get("type") == "recall"})
        payload = {"verdict": a["verdict"], "signals": [{k2: s[k2] for k2 in ("code", "severity", "title", "chain")}
                                                        for s in a["signals"]],
                   "coverage": a["coverage"], "rules_version": a["rules_version"], "depth": a["depth"]}
        aid = g.save_assessment(k, a["verdict"], payload, text, "template", flagged)
        return {"id": aid, "verdict": a["verdict"], "flagged_recalls": flagged}
    r = await run(do)
    if r is None:
        raise HTTPException(404, f"{k} is not in the graph")
    return r


# ---------------------------------------------------------------- investigations (Phase 2 agent)
INV_ID = r"^I-[0-9a-f]{12}$"
PROP_ID = r"^P-[0-9a-f]{12}$"


class InvestigateIn(BaseModel):
    request: str = Field(min_length=3, max_length=2000)
    k: str | None = None
    depth: int = Field(4, ge=1, le=6)
    mode: str = Field("auto", pattern="^(auto|llm|deterministic)$")
    max_steps: int | None = Field(None, ge=1, le=20)


def _inv_id(i: str) -> str:
    if not re.match(INV_ID, i):
        raise HTTPException(400, "Expected an investigation id like I-0123456789ab")
    return i


def _reserve(inv_id: str) -> None:
    """Take a run slot before the Investigation node is created, so a refusal leaves nothing behind. Runs on the
    event loop thread (no await in between), so check-and-add is atomic."""
    if len(_running) >= MAX_CONCURRENT_INVESTIGATIONS:
        raise HTTPException(429, f"{MAX_CONCURRENT_INVESTIGATIONS} investigations are already running; try again later")
    _running.add(inv_id)


async def _create_and_launch(inv: dict, budget: inv_runner.Budget, prior: list[dict] | None) -> None:
    _reserve(inv["id"])
    try:
        await run(lambda g: inv_store.create(g, inv))
    except Exception:
        _running.discard(inv["id"])
        raise
    _launch(inv, budget, prior)


def _launch(inv: dict, budget: inv_runner.Budget, prior: list[dict] | None) -> None:
    def work():
        try:
            inv_runner.run(_graph_sync, inv, budget=budget, prior=prior)
        except Exception:
            pass                      # the runner recorded status "failed" and the error on the node
        finally:
            _running.discard(inv["id"])
    _inv_pool.submit(work)


def _links(i: str) -> dict:
    return {"status": f"/api/investigations/{i}", "trace": f"/api/investigations/{i}/trace",
            "report": f"/api/investigations/{i}/report", "report_markdown": f"/api/investigations/{i}/report?format=markdown"}


@app.post("/api/investigations", status_code=202)
async def start_investigation(body: InvestigateIn):
    m = re.search(r"\bK\d{6}\b", ((body.k or "") + " " + body.request).upper())
    if not m:
        raise HTTPException(400, "Name the target device: give 'k' or a K-number in the request")
    k = _norm_k(m.group(0))
    if await run(lambda g: g.device(k)) is None:
        raise HTTPException(404, f"{k} is not in the graph. Ingest it first.")
    inv = {"id": inv_store.new_id("I"), "request": body.request.strip(), "target_k": k, "depth": body.depth,
           "mode": body.mode, "models": None, "agent_version": inv_runner.AGENT_VERSION, "resumed_from": None}
    budget = inv_runner.Budget()
    if body.max_steps:
        budget.max_steps = body.max_steps
    await _create_and_launch(inv, budget, None)
    return {"id": inv["id"], "status": "queued", "target_k": k, "mode": body.mode, "links": _links(inv["id"])}


@app.get("/api/investigations")
async def list_investigations(k: str | None = None, limit: int = Query(30, ge=1, le=200)):
    kk = _norm_k(k) if k else None
    return await run(lambda g: inv_store.listing(g, kk, limit))


@app.get("/api/investigations/{inv_id}")
async def get_investigation(inv_id: str):
    _inv_id(inv_id)
    i = await run(lambda g: inv_store.get(g, inv_id))
    if i is None:
        raise HTTPException(404, f"No investigation {inv_id}")
    return i | {"running_now": inv_id in _running, "links": _links(inv_id)}


@app.get("/api/investigations/{inv_id}/trace")
async def investigation_trace(inv_id: str, results: bool = False):
    _inv_id(inv_id)
    if await run(lambda g: inv_store.get(g, inv_id)) is None:
        raise HTTPException(404, f"No investigation {inv_id}")
    return await run(lambda g: inv_store.trace(g, inv_id, with_results=results))


@app.get("/api/investigations/{inv_id}/report")
async def investigation_report(inv_id: str, format: str = Query("json", pattern="^(json|markdown)$")):
    _inv_id(inv_id)
    rep, md = await run(lambda g: inv_store.report(g, inv_id))
    if rep is None:
        i = await run(lambda g: inv_store.get(g, inv_id))
        if i is None:
            raise HTTPException(404, f"No investigation {inv_id}")
        raise HTTPException(409, f"Investigation {inv_id} has no report yet (status: {i['status']})")
    return PlainTextResponse(md, media_type="text/markdown") if format == "markdown" else rep


@app.get("/api/investigations/{inv_id}/findings")
async def investigation_findings(inv_id: str):
    _inv_id(inv_id)
    return await run(lambda g: inv_store.findings(g, inv_id))


class ResumeIn(BaseModel):
    max_steps: int | None = Field(None, ge=1, le=20)
    mode: str = Field("auto", pattern="^(auto|llm|deterministic)$")


@app.post("/api/investigations/{inv_id}/resume", status_code=202)
async def resume_investigation(inv_id: str, body: ResumeIn | None = None):
    _inv_id(inv_id)
    body = body or ResumeIn()
    old = await run(lambda g: inv_store.get(g, inv_id))
    if old is None:
        raise HTTPException(404, f"No investigation {inv_id}")
    if old["status"] in ("queued", "running") or inv_id in _running:
        raise HTTPException(409, f"{inv_id} is still {old['status']}")
    prior = await run(lambda g: inv_store.trace(g, inv_id))
    inv = {"id": inv_store.new_id("I"), "request": old["request"], "target_k": old["target_k"],
           "depth": old["depth"], "mode": body.mode, "models": None, "agent_version": inv_runner.AGENT_VERSION,
           "resumed_from": inv_id}
    budget = inv_runner.Budget()
    if body.max_steps:
        budget.max_steps = body.max_steps
    await _create_and_launch(inv, budget, prior)
    return {"id": inv["id"], "status": "queued", "resumed_from": inv_id, "links": _links(inv["id"])}


@app.get("/api/proposals")
async def list_proposals(status: str | None = Query(None, pattern="^(pending_human_decision|dismissed|executed|"
                                                                   "acknowledged|failed)$"),
                         investigation: str | None = None):
    if investigation:
        _inv_id(investigation)
    return await run(lambda g: inv_store.proposals(g, investigation, status))


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|dismiss)$")
    reviewer: str = Field(min_length=2, max_length=120)
    human: bool = False
    note: str | None = Field(None, max_length=1000)


@app.post("/api/proposals/{pid}/decision")
async def decide_proposal(pid: str, body: DecisionIn):
    """A person's decision on an agent proposal. The only path by which an agent proposal leads to a graph change:
    approving an ingest proposal runs the same bounded, verified single-clearance ingest as /api/ingest.
    Approving a link-review proposal changes nothing: the person records the review itself in the app."""
    if not re.match(PROP_ID, pid):
        raise HTTPException(400, "Expected a proposal id like P-0123456789ab")
    who = body.reviewer.strip()
    if body.human is not True or NOT_A_PERSON.search(who):
        raise HTTPException(403, "Only a person can decide an agent proposal: attest \"human\": true and give your "
                                 "name (not a role, tool, agent or model)")
    p = await run(lambda g: inv_store.proposal(g, pid))
    if p is None:
        raise HTTPException(404, f"No proposal {pid}")
    # claim it atomically on the single Relate thread, so two concurrent approvals cannot both run an ingest
    if not await run(lambda g: inv_store.claim_proposal(g, pid, who)):
        raise HTTPException(409, f"{pid} was already decided ({p['status']})")
    if body.decision == "dismiss":
        return await run(lambda g: inv_store.decide_proposal(g, pid, "dismissed", who, body.note, None))
    if p["kind"] == "link_review":
        res = {"note": "Approval recorded. The citation is unchanged: record your review of "
                       f"{p['src']} -> {p['dst']} in the app (What it cites) or POST /api/citation/review."}
        return await run(lambda g: inv_store.decide_proposal(g, pid, "acknowledged", who, body.note, res))
    k = _norm_k(p["k"])
    loop = asyncio.get_running_loop()
    try:
        existing = await run(lambda g: g.device(k))
        fetched = await loop.run_in_executor(None, ingest_mod.fetch_clearance, k)
        present = await run(lambda g: ingest_mod.present_devices(g, fetched.cited))
        related = await loop.run_in_executor(None, ingest_mod.fetch_related, fetched, present)
        r = await run(lambda g: ingest_mod.write(g, fetched, related, existing))
    except Exception as e:            # IngestError or anything else: never leave the proposal 'deciding'
        error = f"{type(e).__name__}: {str(e)[:300]}"
        return await run(lambda g: inv_store.decide_proposal(g, pid, "failed", who, body.note, {"error": error}))
    res = {k2: r[k2] for k2 in ("k", "summary_status", "summary_url", "new_devices", "recalls_linked")} | {
        "citations_added": [{k2: c[k2] for k2 in ("dst", "kind", "page")} for c in r["citations_added"]]}
    return await run(lambda g: inv_store.decide_proposal(g, pid, "executed", who, body.note, res))


# ---------------------------------------------------------------- frontend
DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    _DIST_ROOT = DIST.resolve()

    @app.get("/{path:path}")
    async def spa(path: str):
        # Serve only files that resolve INSIDE web/dist (blocks ../, %2f.. and absolute paths).
        try:
            f = (_DIST_ROOT / path).resolve()
        except (OSError, ValueError):
            raise HTTPException(404)
        if path and f.is_file() and f.is_relative_to(_DIST_ROOT):
            return FileResponse(f)
        if path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(_DIST_ROOT / "index.html")
