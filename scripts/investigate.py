"""Run a Forebear investigation from the command line, in-process on a Relate store.

    .venv\\Scripts\\python.exe scripts\\investigate.py --k K252078 --copy "Investigate K252078, trace recalled predicates, verify the original FDA evidence, identify unresolved lineage, and prepare a documented due-diligence report."

The API is the single writer of a store, so stop the app first or use --copy (works on a copy under data\\live,
which is gitignored). Prints each model turn and tool call as it happens and writes the report (JSON and
Markdown) to --out. --mode deterministic runs the labelled fallback checklist without the LLM.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forebear.agent import load_env  # noqa: E402
from forebear.config import DB_PATH, LIVE, use_live_cache  # noqa: E402
from forebear.graph import open_graph  # noqa: E402
from forebear.investigation import runner, store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("request", nargs="?", default=None, help="what to investigate (free text)")
    ap.add_argument("--k", help="target 510(k) number (default: the first K-number in the request)")
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--mode", choices=["auto", "llm", "deterministic"], default="auto")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--copy", action="store_true", help="work on a copy of --db under data/live")
    ap.add_argument("--resume", help="investigation id to resume (same store)")
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--models", help="comma-separated NVIDIA model ids (default: FOREBEAR_AGENT_MODELS or built-in)")
    ap.add_argument("--out", default=str(LIVE / "investigations"))
    a = ap.parse_args(argv)

    load_env()
    use_live_cache()
    db = Path(a.db)
    if a.copy:
        LIVE.mkdir(parents=True, exist_ok=True)
        dst = LIVE / f"investigation_{time.strftime('%Y%m%d_%H%M%S')}.rl"
        shutil.copy(db, dst)
        db = dst
        print(f"working on a copy: {db}")
    g = open_graph(db)
    try:
        prior = None
        if a.resume:
            old = store.get(g, a.resume)
            if old is None:
                print(f"no investigation {a.resume} in {db}")
                return 2
            k, request, depth = old["target_k"], a.request or old["request"], old["depth"]
            prior = store.trace(g, a.resume, with_results=False)
        else:
            request = a.request or "Investigate this device's predicate lineage and recall history."
            m = re.search(r"\bK\d{6}\b", (a.k or "") + " " + request.upper())
            if not m:
                print("give --k or a K-number in the request")
                return 2
            k, depth = m.group(0), max(1, min(a.depth, 6))
        if g.device(k) is None:
            print(f"{k} is not in the graph")
            return 2
        models = [x.strip() for x in a.models.split(",")] if a.models else None
        inv = {"id": store.new_id("I"), "request": request, "target_k": k, "depth": depth, "mode": a.mode,
               "models": models, "agent_version": runner.AGENT_VERSION, "resumed_from": a.resume}
        store.create(g, inv)
        budget = runner.Budget()
        if a.max_steps:
            budget.max_steps = a.max_steps

        def show(kind: str, d: dict) -> None:
            if kind == "turn":
                plan = " ".join((d["content"] or "").split())[:220]
                print(f"\n[turn {d['step']}] {d['model']} {d['seconds']}s -> {d['calls'] or 'no tool call'}"
                      + (f"\n  plan: {plan}" if plan else ""))
            elif kind == "tool":
                print(f"  #{d['seq']} {d['origin']}: {d['tool']}({json.dumps(d['args'])[:120]}) -> {d['summary'][:200]}")
            elif kind in ("done", "failed"):
                print(f"\n{kind}: {d}")

        rep = runner.run(lambda fn: fn(g), inv, budget=budget, on_event=show, prior=prior)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{inv['id']}.json").write_text(json.dumps(rep, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        (out / f"{inv['id']}.md").write_text(store.report(g, inv["id"])[1] or "", encoding="utf-8")
        c = rep["conclusion"]
        print(f"\n{inv['id']}: {rep['status']} / {rep['mode']}\nconclusion: {c['stance']} ({c['verdict']}, evidence "
              f"{c['evidence']})\nfindings: {len(rep['agent']['findings_verified'])} verified, "
              f"{len(rep['agent']['findings_rejected'])} rejected; proposals: {len(rep['proposals'])}\n"
              f"report: {out / (inv['id'] + '.md')}\nstore: {db}")
        return 0
    finally:
        g.close()


if __name__ == "__main__":
    sys.exit(main())
