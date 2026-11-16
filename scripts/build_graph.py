"""Step 2 of the dataset build: assemble the Relate store data/forebear.rl from data/raw/.

    python scripts/build_graph.py [--out data/forebear.rl]

Deterministic: same cached inputs -> same graph. Writes data/build_report.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forebear import openfda  # noqa: E402
from forebear.config import DATA, DB_PATH, DEFAULT_PRODUCT_CODES, use_raw_cache  # noqa: E402
from forebear.dataset import citation_rows, device_row, fetch_recalls_for, mark_no_predicate  # noqa: E402
from forebear.graph import open_graph  # noqa: E402
from forebear.predicates import extract_from_summary  # noqa: E402
from forebear import summaries  # noqa: E402


REVIEWS = DATA / "reviews.json"


def build(out: Path, codes: list[str]) -> dict:
    use_raw_cache()              # the shipped store is built from data/raw only, never data/live
    t0 = time.time()
    report: dict = {"product_codes": codes}
    in_family = {}
    for code in codes:
        for r in openfda.clearances_for_product_code(code):
            in_family[r["k_number"]] = r
    # predicates cited from in-family summaries, possibly in other product codes
    cited = set()
    for k in in_family:
        rec = summaries.load(k)
        if rec and rec["status"] == "ok":
            cited |= {h["k"] for h in extract_from_summary(rec, self_k=k)}
    outside = {r["k_number"]: r for r in openfda.clearances_by_k(sorted(cited - set(in_family)))}
    known = {**outside, **in_family}

    devices = [device_row(r, True) for r in in_family.values()] + \
              [device_row(r, False, read_summary=False) for k, r in outside.items() if k not in in_family]
    cit_report: dict = {}
    citations = []
    for k, r in in_family.items():
        citations += citation_rows(k, r.get("date_received"), r.get("decision_date"), known, cit_report)
    no_pred = mark_no_predicate(devices, citations)
    recalls = fetch_recalls_for(sorted(known))
    reviews = json.loads(REVIEWS.read_text(encoding="utf-8"))["reviews"] if REVIEWS.exists() else []
    codes_meta = []
    for code in sorted({d["product_code"] for d in devices if d["product_code"]}):
        c = openfda.classification(code) if code in codes else None
        codes_meta.append({"code": code, "name": (c or {}).get("device_name"),
                           "device_class": (c or {}).get("device_class"),
                           "regulation": (c or {}).get("regulation_number")})

    if out.exists():
        out.unlink()
    g = open_graph(out)
    try:
        g.conn.autocommit = False
        g.upsert_product_codes(codes_meta)
        g.upsert_devices(devices)
        g.upsert_citations(citations)
        g.upsert_recalls(recalls)
        g.conn.commit()
        applied = 0
        for rv in reviews:      # curated human decisions, versioned in data/reviews.json
            if g.review_citation(rv["src"], rv["dst"], rv["status"], rv["note"], reviewer=rv["reviewer"]):
                applied += 1
        g.conn.commit()
        g.conn.autocommit = True
        stats = g.stats()
    finally:
        g.close()

    status_counts: dict[str, int] = {}
    for d in devices:
        if d["in_scope"]:
            status_counts[d["summary_status"]] = status_counts.get(d["summary_status"], 0) + 1
    report.update({
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - t0, 1),
        "in_family_devices": len(in_family),
        "out_of_family_predicates": len(outside),
        "in_family_summary_status": status_counts,
        "citation_extraction": cit_report,
        "in_family_summary_read_but_no_predicate_found": no_pred,
        "curated_reviews_applied": f"{applied}/{len(reviews)}",
        "recall_records_linked": len(recalls),
        "design_related_recalls": sum(r["design_related"] for r in recalls),
        "graph": stats,
    })
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DB_PATH)
    ap.add_argument("--codes", nargs="*", default=DEFAULT_PRODUCT_CODES)
    a = ap.parse_args()
    rep = build(a.out, a.codes)
    (DATA / "build_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
