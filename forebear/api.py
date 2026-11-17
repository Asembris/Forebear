"""FastAPI backend. Every graph call runs on ONE dedicated worker thread that owns the
Relate connection (Relate connections are thread-affine; one writer per store).

    uvicorn forebear.api:app --port 8765
"""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent
from .config import DB_PATH, ROOT, use_live_cache
from .graph import Graph, open_graph
from . import ingest as ingest_mod
from .ingest import IngestError
from .lineage import assess, compare

agent.load_env()
use_live_cache()          # live ingests never touch the committed data/raw cache
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="relate")
_graph: Graph | None = None


def _db_path() -> Path:
    return Path(os.environ.get("FOREBEAR_DB", DB_PATH))


def _open() -> None:
    global _graph
    p = _db_path()
    if not p.exists():
        raise RuntimeError(f"Relate store not found at {p}. Run: python scripts/build_graph.py")
    _graph = open_graph(p)


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
    return await run(lambda g: g.recall_event_reach(event, depth))


@app.get("/api/watchlist")
async def watchlist(design_only: bool = True):
    rows = await run(lambda g: g.cited_after_recall(design_only, limit=5000))
    by: dict[str, dict] = {}
    for r in rows:
        d = by.setdefault(r["k"], {"k": r["k"], "name": r["name"], "applicant": r["applicant"],
                                   "decision_date": r["decision_date"], "received_date": r["received_date"],
                                   "min_gen": r["gen"],
                                   "ancestors": set(), "events": set(), "recalls": []})
        d["min_gen"] = min(d["min_gen"], r["gen"])
        d["ancestors"].add(r["ancestor"])
        d["events"].add(r["event"])
        if len(d["recalls"]) < 6:
            d["recalls"].append({k: r[k] for k in ("recall_id", "ancestor", "gen", "classification",
                                                   "root_cause", "initiated", "firm", "url")})
    out = sorted(by.values(), key=lambda d: d["decision_date"] or "", reverse=True)
    for d in out:
        d["ancestors"] = sorted(d["ancestors"])
        d["events"] = sorted(e for e in d["events"] if e)
    return {"count": len(out), "direct": sum(1 for d in out if d["min_gen"] == 1), "rows": out}


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
