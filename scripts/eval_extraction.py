"""Before/after evaluation of predicate extraction on a seeded, stratified sample.

    python scripts/eval_extraction.py sample   # writes eval/extraction_eval_sample.json (contexts to label)
    python scripts/eval_extraction.py score    # reads eval/extraction_eval_labels.json, writes eval/extraction_eval.json

"Before" is the pre-Phase-1 extractor, kept verbatim in eval/legacy/predicates_v2.py and run on the PDF text
layer only (it had no OCR). "After" is forebear/predicates.py on the text layer plus verified OCR text.
Edges are (citing K, cited K) pairs the extractor labels 'predicate' and that resolve in openFDA and predate
the citing device - the same validation the build applies.

Strata (every edge belongs to exactly one):
  both      predicate before and after         -> random sample (seed 17)
  old_only  predicate before, not after        -> all
  new_only  predicate after, not before        -> all (text layer)
  ocr       predicate after, from OCR text     -> random sample (seed 17)
Labels are the extraction auditor's reading of the full page text (an agent, not a human), recorded with a
note per edge in eval/extraction_eval_labels.json; they are evidence for the measurement, not ground truth.
"""
from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forebear import summaries  # noqa: E402
from scripts.audit_links import collect  # noqa: E402

EVAL = ROOT / "eval"
SEED = 17
N_BOTH, N_OCR = 40, 20


def _legacy():
    spec = importlib.util.spec_from_file_location("legacy_predicates_v2", EVAL / "legacy" / "predicates_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def edge_sets():
    in_family, known, rows, _ = collect()
    legacy = _legacy()
    after = {(r["src"], r["dst"]): r for r in rows if r["kind"] == "predicate"}
    before = {}
    for k, meta in in_family.items():
        rec = summaries.load(k)
        if not rec or rec["status"] != "ok":
            continue
        limit = meta.get("decision_date") or meta.get("date_received")
        for h in legacy.extract_from_summary(rec, self_k=k):
            t = known.get(h["k"])
            if h["kind"] != "predicate" or t is None:
                continue
            if limit and t.get("decision_date") and t["decision_date"] > limit:
                continue
            before[(k, h["k"])] = h
    return in_family, known, before, after


def strata():
    in_family, known, before, after = edge_sets()
    ocr_edges = {e for e, r in after.items() if r["text_source"] == "ocr"}
    s = {"both": sorted(set(before) & set(after) - ocr_edges),
         "old_only": sorted(set(before) - set(after)),
         "new_only": sorted(set(after) - set(before) - ocr_edges),
         "ocr": sorted(ocr_edges)}
    return in_family, known, before, after, s


def _context(src: str, dst: str, page: int) -> str:
    rec = summaries.load_text(src)
    text = rec["pages"][page - 1]
    d = dst[1:]
    for probe in (dst, "K" + d[:2] + " " + d[2:], "K" + d[:1] + " " + d[1:]):
        i = text.find(probe)
        if i >= 0:
            return " ".join(text[max(0, i - 500):i + 300].split())
    return " ".join(text[:800].split())


def cmd_sample() -> None:
    in_family, known, before, after, s = strata()
    rng = random.Random(SEED)
    pick = {"both": rng.sample(s["both"], min(N_BOTH, len(s["both"]))), "old_only": s["old_only"],
            "new_only": s["new_only"], "ocr": rng.sample(s["ocr"], min(N_OCR, len(s["ocr"])))}
    items = []
    for stratum, edges in pick.items():
        for src, dst in edges:
            page = (after.get((src, dst)) or before.get((src, dst)))["page"]
            items.append({"stratum": stratum, "src": src, "dst": dst, "dst_name": known[dst].get("device_name"),
                          "page": page, "context": _context(src, dst, page)})
    (EVAL / "extraction_eval_sample.json").write_text(json.dumps(
        {"seed": SEED, "population": {k: len(v) for k, v in s.items()}, "items": items},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print({k: len(v) for k, v in s.items()}, "sampled", len(items))


def cmd_score() -> dict:
    sample = json.loads((EVAL / "extraction_eval_sample.json").read_text(encoding="utf-8"))
    labels = {(x["src"], x["dst"]): x for x in json.loads(
        (EVAL / "extraction_eval_labels.json").read_text(encoding="utf-8"))["labels"]}
    pop = sample["population"]
    res = {}
    for st in ("both", "old_only", "new_only", "ocr"):
        its = [i for i in sample["items"] if i["stratum"] == st]
        lab = [labels[(i["src"], i["dst"])]["label"] for i in its if (i["src"], i["dst"]) in labels]
        res[st] = {"population": pop[st], "sampled": len(its), "labelled": len(lab),
                   "predicate": lab.count("predicate"), "not_predicate": lab.count("not_predicate"),
                   "unclear": lab.count("unclear")}
    def rate(st, unclear_as):
        r = res[st]
        n = r["labelled"]
        if not n:
            return None
        good = r["predicate"] + (r["unclear"] if unclear_as else 0)
        return good / n
    out = {}
    for name, unclear_as in (("strict", False), ("lenient", True)):
        pb = rate("both", unclear_as)
        good_before = pb * pop["both"] + (rate("old_only", unclear_as) or 0) * pop["old_only"]
        good_after = pb * pop["both"] + (rate("new_only", unclear_as) or 0) * pop["new_only"] + \
            (rate("ocr", unclear_as) or 0) * pop["ocr"]
        n_before = pop["both"] + pop["old_only"]
        n_after = pop["both"] + pop["new_only"] + pop["ocr"]
        out[name] = {"precision_before": round(good_before / n_before, 3),
                     "precision_after": round(good_after / n_after, 3),
                     "estimated_true_predicates_before": round(good_before),
                     "estimated_true_predicates_after": round(good_after),
                     "predicate_edges_before": n_before, "predicate_edges_after": n_after}
    # exact (Clopper-Pearson) 95% lower bound for the sampled 'both' stratum
    rb = res["both"]
    out["both_stratum_precision_95pct_lower_bound"] = round(_cp_lower(rb["predicate"], rb["labelled"]), 3)
    # census: every flagged predicate edge was read in full by the link audit (data/audit/link_decisions.json)
    from forebear import audit as audit_mod
    dec = audit_mod.load()["decisions"]
    out["link_audit_census"] = {
        "not_predicate_found": sum(1 for d in dec if d["decision"] == "not_predicate"),
        "k_number_errors_found": sum(1 for d in dec if d["decision"] == "error"),
        "note": "Found by reading every flagged edge, mostly in the unchanged ('both') population: the sample's "
                "point estimate overstates precision; the census shows at least this many wrong edges remain "
                "in the extraction and are removed from lineage by the audit."}
    report = {"about": "Stratified before/after estimate; labels are agent labels from full page text, not ground "
                       "truth. 'strict' counts unclear as wrong, 'lenient' as right. The 'both' stratum is "
                       "sampled, so its precision carries sampling error (see docs/EVIDENCE_QUALITY.md).",
              "seed": sample["seed"], "strata": res, "estimates": out}
    (EVAL / "extraction_eval.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def _cp_lower(x: int, n: int, alpha: float = 0.05) -> float:
    """Exact binomial lower confidence bound (Clopper-Pearson) by bisection; no SciPy needed."""
    from math import comb
    if n == 0:
        return 0.0
    if x == 0:
        return 0.0

    def tail(p):                     # P(X >= x | p)
        return sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(x, n + 1))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if tail(mid) < alpha / 2:
            lo = mid
        else:
            hi = mid
    return lo


if __name__ == "__main__":
    if sys.argv[1:] == ["sample"]:
        cmd_sample()
    else:
        print(json.dumps(cmd_score(), indent=1))
