"""Extraction audit of predicate links: signals, decisions and the unresolved queue.

    python scripts/audit_links.py            # offline; reads data/raw + data/audit, writes eval/

Population: every extracted predicate edge that the legacy name check (v1, which produced the original
124 "name != FDA record" flags), the current name check (v2) or the FDA-panel check flags.

For each edge it records deterministic signals - none of which is a decision on its own:
  name_v1 / name_v2   does a distinctive word of the cited device's FDA name appear near the citation
  panel               same FDA advisory committee as the citing device (all in-family devices are AN)
  applicant_in_text   the cited device's applicant is named near the citation
  own_summary         distinctive words of the citing text also appear in the cited device's own
                      summary (when that summary is in the cache): the strongest variant evidence
  candidates          known K-numbers one digit / one adjacent transposition away whose FDA name does
                      match the citing text and that predate the citing device (typo corrections)
  suggestion          what the signals point to; a person or the documented audit decides

Decisions come from data/audit/link_decisions.json (see forebear/audit.py). Outputs:
  eval/link_audit.json        every flagged edge with signals + decision, and summary counts
  eval/link_audit_queue.json  edges still unresolved or undecided, for human review
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forebear import audit, evidence, openfda, summaries  # noqa: E402
from forebear.config import DEFAULT_PRODUCT_CODES, use_raw_cache  # noqa: E402
from forebear.dataset import citation_rows, company_key  # noqa: E402
from scripts.build_graph import cited_from_in_family  # noqa: E402

EVAL = ROOT / "eval"

# The name check that produced the original 124 flags (regex-context-v2 build), kept verbatim so the
# before/after comparison is measured, not remembered.
_GENERIC_V1 = set("""system systems device devices ventilator ventilators mask masks cpap bipap series model unit
with and the for positive airway pressure nasal full face heated humidifier humidifiers therapy respiratory
breathing circuit circuits kit accessory accessories oral interface auto plus portable home non continuous
vented sleep apnea medical inc corp ltd llc company""".split())


def name_check_v1(snippet: str, cited_name: str | None) -> str:
    toks = {w for w in re.findall(r"[a-z0-9]{3,}", (cited_name or "").lower())
            if w not in _GENERIC_V1 and not w.isdigit()}
    if not toks:
        return "n/a"
    low = (snippet or "").lower()
    return "match" if any(t in low for t in toks) else "mismatch"


def collect():
    use_raw_cache(offline=True)
    in_family = {r["k_number"]: r for c in DEFAULT_PRODUCT_CODES for r in openfda.clearances_for_product_code(c)}
    cited = cited_from_in_family(in_family)
    outside = {r["k_number"]: r for r in openfda.clearances_by_k(sorted(cited - set(in_family)))}
    known = {**outside, **in_family}
    rows, unresolved = [], []
    for k, r in in_family.items():
        rows += citation_rows(k, r.get("date_received"), r.get("decision_date"), known, None, unresolved, src_meta=r)
    return in_family, known, rows, unresolved


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9]{3,}", (text or "").lower()))


_DF: dict[str, int] = {}
_N_DOCS = [0]
RARE_DF = 0.02          # a word in fewer than 2% of summaries (first two pages) is distinctive


def _doc_freq() -> dict[str, int]:
    """Document frequency of words over the first two pages of every readable summary, so that only
    rare words (product names, not "small", "device" or "respironics") count as shared evidence."""
    if not _DF:
        for p in sorted(summaries.SUMMARY_CACHE.glob("K*.json")):
            rec = summaries.load_text(p.stem)
            if rec:
                _N_DOCS[0] += 1
                for w in _words(" ".join(rec["pages"][:2])):
                    _DF[w] = _DF.get(w, 0) + 1
    return _DF


def own_summary_overlap(span: str, dst: str, applicant: str | None = None) -> str:
    """'yes' if a rare word of the citing text (other than the cited device's applicant name) also
    appears on the first two pages of the cited device's own summary, 'no' if none does, 'n/a' if that
    summary is not readable. Rare = in fewer than RARE_DF of all summaries."""
    rec = summaries.load_text(dst)
    if not rec:
        return "n/a"
    df, n = _doc_freq(), max(_N_DOCS[0], 1)
    head = _words(" ".join(rec["pages"][:2]))
    skip = set(company_key(applicant).lower().split())
    near = {w for w in _words(span) if df.get(w, 0) / n < RARE_DF and w not in skip
            and not re.fullmatch(r"k?\d+[a-z]?", w)
            and w not in evidence.GENERIC}
    return "yes" if near & head else "no"


def signals(row: dict, in_family: dict, known: dict) -> dict:
    dst = known[row["dst"]]
    src = in_family[row["src"]]
    span = row["quote"]
    app = [w for w in company_key(dst.get("applicant")).lower().split() if len(w) >= 4]
    limit = src.get("decision_date")
    cands = [n for n in evidence.neighbour_ks(row["dst"], known)
             if evidence.name_check(span, known[n].get("device_name")) == "match"
             and (not limit or (known[n].get("decision_date") or "") <= limit)]
    s = {
        "name_v1": name_check_v1(row["snippet"], dst.get("device_name")),
        "name_v2": row["name_check"],
        "panel": row["panel_check"],
        "applicant_in_text": any(w in span.lower() for w in app),
        "same_applicant": company_key(dst.get("applicant")) == company_key(src.get("applicant")),
        "own_summary": own_summary_overlap(span, row["dst"], dst.get("applicant")),
        "candidates": [{"k": n, "name": known[n].get("device_name"), "decision_date": known[n].get("decision_date")}
                       for n in cands],
    }
    if s["name_v2"] == "match" and s["panel"] != "different":
        sug = "variant (name check v2 matches)"
    elif s["panel"] == "different":
        sug = "error (cited device is from another FDA panel)"
    elif s["candidates"]:
        sug = "error, correctable (a one-digit neighbour matches the text)"
    elif s["own_summary"] == "yes":
        sug = "variant (the cited device's own summary uses the text's name)"
    else:
        sug = "needs review"
    s["suggestion"] = sug
    return s


def _needs_decision(f: dict) -> bool:
    """Flagged only by the legacy check (v1) and matched by name check v2 on the same panel: resolved
    deterministically. Anything v2 or the panel check still flags needs a decision."""
    return f["signals"]["name_v2"] == "mismatch" or f["signals"]["panel"] == "different"


def main() -> dict:
    in_family, known, rows, unresolved = collect()
    decisions = {(d["src"], d["dst"]): d for d in audit.load()["decisions"]}
    flagged = []
    for r in rows:
        if r["kind"] != "predicate":
            continue
        s = signals(r, in_family, known)
        if s["name_v1"] != "mismatch" and s["name_v2"] != "mismatch" and s["panel"] != "different" \
                and (r["src"], r["dst"]) not in decisions:
            continue
        d = decisions.get((r["src"], r["dst"]))
        flagged.append({
            "src": r["src"], "src_name": in_family[r["src"]].get("device_name"),
            "dst": r["dst"], "dst_name": known[r["dst"]].get("device_name"),
            "dst_applicant": known[r["dst"]].get("applicant"),
            "dst_panel": known[r["dst"]].get("advisory_committee"),
            "page": r["page"], "source_url": r["source_url"], "text_source": r["text_source"],
            "quote": r["quote"], "signals": s,
            "decision": d["decision"] if d else None, "correct_to": (d or {}).get("correct_to"),
            "note": (d or {}).get("note"),
        })
    flagged.sort(key=lambda x: (x["decision"] or "~", x["src"], x["dst"]))
    pred = [r for r in rows if r["kind"] == "predicate"]
    summary = {
        "predicate_edges": len(pred),
        "flagged_name_v1": sum(1 for f in flagged if f["signals"]["name_v1"] == "mismatch"),
        "flagged_name_v2": sum(1 for f in flagged if f["signals"]["name_v2"] == "mismatch"),
        "flagged_panel": sum(1 for f in flagged if f["signals"]["panel"] == "different"),
        "flagged_total": len(flagged),
        "decisions": dict(Counter(f["decision"] or ("resolved_by_name_check_v2" if not _needs_decision(f) else "undecided")
                                  for f in flagged)),
        "corrections": sum(1 for f in flagged if f["correct_to"]),
        "suggestions": dict(Counter(f["signals"]["suggestion"] for f in flagged)),
        "unresolved_citations": {"total": len(unresolved),
                                 "predicate": sum(1 for u in unresolved if u["kind"] == "predicate"),
                                 "by_reason": dict(Counter(u["reason"] for u in unresolved))},
        "decisions_not_matching_an_edge": sorted(f"{s}->{d}" for (s, d) in decisions
                                                 if not any(r["src"] == s and r["dst"] == d for r in rows)),
    }
    queue = [f for f in flagged if f["decision"] == "unresolved" or (f["decision"] is None and _needs_decision(f))]
    EVAL.mkdir(exist_ok=True)
    (EVAL / "link_audit.json").write_text(json.dumps({
        "about": "Extraction audit of predicate links. Signals are deterministic; decisions come from "
                 "data/audit/link_decisions.json and are audit decisions, not human sign-offs. "
                 "Regenerate with: python scripts/audit_links.py",
        "summary": summary, "edges": flagged,
        "unresolved_citations": unresolved}, indent=1, ensure_ascii=False), encoding="utf-8")
    (EVAL / "link_audit_queue.json").write_text(json.dumps({
        "about": "Predicate links still needing a human decision (audit 'unresolved' or undecided). "
                 "Confirm or reject each in the app (What K... cites) or via the review_citation MCP tool; "
                 "a human review overrides the audit.",
        "count": len(queue),
        "items": [{k: f[k] for k in ("src", "src_name", "dst", "dst_name", "page", "source_url", "quote",
                                     "decision", "note")} | {"suggestion": f["signals"]["suggestion"]}
                  for f in queue]}, indent=1, ensure_ascii=False), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
