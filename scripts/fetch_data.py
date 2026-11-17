"""Step 1 of the dataset build: fetch public FDA records into data/raw/.

    python scripts/fetch_data.py metadata            # 510(k) records + recalls for the product codes
    python scripts/fetch_data.py summaries [--max N] # 510(k) summary PDFs -> text (slow, polite)
    python scripts/fetch_data.py expand              # metadata + recalls for out-of-family predicates
    python scripts/fetch_data.py ocr [--max N]       # local OCR of image-only summaries (requirements-ocr.txt)

Everything is cached; re-running only fetches what is missing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forebear import openfda, summaries  # noqa: E402
from forebear.config import DEFAULT_PRODUCT_CODES, SUMMARY_MIN_YEAR, USER_AGENT, DATA  # noqa: E402

MANIFEST = DATA / "raw" / "manifest.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, indent=1))


def cmd_metadata(codes: list[str]) -> None:
    m = load_manifest()
    m["product_codes"] = codes
    for code in codes:
        cl = openfda.clearances_for_product_code(code)
        rc = openfda.recalls_for_product_code(code)
        cls = openfda.classification(code)
        print(f"{code}: {len(cl)} clearances, {len(rc)} recall records, class={cls and cls.get('device_class')}")
    save_manifest(m)


def in_family_needing_summary(codes: list[str]) -> list[str]:
    ks = []
    for code in codes:
        for r in openfda.clearances_for_product_code(code):
            year = int((r.get("decision_date") or "0000")[:4])
            if year >= SUMMARY_MIN_YEAR and (r.get("statement_or_summary") or "").lower() == "summary":
                ks.append(r["k_number"])
    return sorted(set(ks))


def cmd_summaries(codes: list[str], max_n: int | None, extra: list[str] | None = None) -> None:
    ks = extra if extra else in_family_needing_summary(codes)
    todo = [k for k in ks if summaries.load(k) is None]
    if max_n:
        todo = todo[:max_n]
    print(f"{len(ks)} summaries wanted, {len(todo)} to fetch", flush=True)
    t0 = time.time()
    stats: dict[str, int] = {}
    with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        def one(k):
            rec = summaries.fetch(k, client)
            time.sleep(0.5)
            return rec["status"]
        with ThreadPoolExecutor(max_workers=2) as ex:
            for i, st in enumerate(ex.map(one, todo), 1):
                stats[st] = stats.get(st, 0) + 1
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)} {stats} {time.time()-t0:.0f}s", flush=True)
    print("done", stats, flush=True)


def cmd_expand(codes: list[str]) -> None:
    """Fetch metadata + recalls for predicates referenced from in-family summaries.

    Mirrors build_graph.build() query for query (same K-number sets, same chunking), so the offline
    build finds every response it needs in the cache. Re-run after extraction rules or OCR change."""
    from scripts.build_graph import cited_from_in_family
    in_family = {r["k_number"] for c in codes for r in openfda.clearances_for_product_code(c)}
    cited = cited_from_in_family(in_family)
    outside_wanted = sorted(cited - in_family)
    print(f"{len(cited)} cited K-numbers, {len(outside_wanted)} outside the families")
    meta = openfda.clearances_by_k(outside_wanted)
    found = {r["k_number"] for r in meta}
    print(f"  metadata found for {len(found)}; not in openFDA: {sorted(set(outside_wanted) - found)}")
    known = sorted(in_family | found)
    rc = openfda.recalls_by_k(known)
    enf = openfda.enforcement_by_event({r.get("res_event_number") for r in rc})
    print(f"  recall records referencing graph devices: {len(rc)}; enforcement rows: {len(enf)}")
    m = load_manifest()
    m["expanded_predicates"] = sorted(found)
    save_manifest(m)


def cmd_ocr(codes: list[str], max_n: int | None) -> None:
    """OCR every in-family summary whose PDF has no text layer (see forebear/ocr.py)."""
    from forebear import ocr
    in_family = sorted({r["k_number"] for c in codes for r in openfda.clearances_for_product_code(c)})
    todo = [k for k in in_family
            if (summaries.load(k) or {}).get("status") == "no_text" and ocr.load(k) is None]
    if max_n:
        todo = todo[:max_n]
    print(f"{len(todo)} image-only summaries to OCR", flush=True)
    engine, meta = ocr._engine()
    stats: dict[str, int] = {}
    t0 = time.time()
    with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for i, k in enumerate(todo, 1):
            rec = ocr.run(summaries.load(k), client, engine, meta)
            if rec["status"] != "download_failed":          # transient network errors are not cached
                ocr.save(rec)
            stats[rec["status"]] = stats.get(rec["status"], 0) + 1
            print(f"  {i}/{len(todo)} {k} {rec['status']} pages={len(rec['pages'])} "
                  f"low_conf={rec.get('low_confidence_pages')} {time.time()-t0:.0f}s", flush=True)
            time.sleep(0.5)
    print("done", stats, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["metadata", "summaries", "expand", "ocr"])
    ap.add_argument("--codes", nargs="*", default=DEFAULT_PRODUCT_CODES)
    ap.add_argument("--max", type=int, default=None)
    a = ap.parse_args()
    if a.cmd == "metadata":
        cmd_metadata(a.codes)
    elif a.cmd == "summaries":
        cmd_summaries(a.codes, a.max)
    elif a.cmd == "ocr":
        cmd_ocr(a.codes, a.max)
    else:
        cmd_expand(a.codes)
