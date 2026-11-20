"""Versioned extraction-audit decisions (data/audit/link_decisions.json), applied by the build.

Each decision is about one extracted citation edge src -> dst and quotes the evidence it rests on.
Decisions are made by the extraction audit (scripts/audit_links.py plus a documented manual read of
the full summary page). They are NOT human sign-offs: they live in the edge's `audit*` properties,
never in `review`/`reviewer`, and a human review in the app always overrides them.

  error          the cited K-number does not identify the device the text names (typo/OCR in the
                 PDF): the edge leaves the lineage. With `correct_to`, the build adds the edge to the
                 device the text does name, marked audit="corrected", if that K-number is verified to
                 exist in openFDA and to predate the citing device.
  not_predicate  the K-number is in the summary, but not as a predicate (accessory, compatible
                 product, data platform): the edge leaves the lineage.
  variant        the K-number plausibly identifies the product the text names (a naming or OCR
                 difference, the name sits elsewhere on the page, or a cross-panel secondary predicate
                 whose name matches): the edge stays and is no longer treated as doubtful.
  unresolved     the evidence does not settle it: the edge stays, flagged, and is listed in the queue.
  role_corrected the original PDF establishes a different citation role from the extractor.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import evidence, summaries
from .config import AUDIT

DECISIONS = AUDIT / "link_decisions.json"
OUT_OF_LINEAGE = ("error", "not_predicate")
STATUSES = ("error", "not_predicate", "variant", "unresolved", "role_corrected")


def load(path: Path = DECISIONS) -> dict:
    if not path.exists():
        return {"auditor": None, "decisions": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    for d in data["decisions"]:
        if d["decision"] not in STATUSES:
            raise ValueError(f"bad audit decision {d}")
        if d.get("correct_to") and d["decision"] != "error":
            raise ValueError(f"correct_to only allowed on 'error': {d}")
        if d["decision"] == "role_corrected" and (d.get("kind") not in ("predicate", "reference")
                                                     or not d.get("source")):
            raise ValueError(f"role correction requires a kind and a source anchor: {d}")
        if "kind" in d and d["decision"] != "role_corrected":
            raise ValueError(f"kind override only allowed on 'role_corrected': {d}")
    return data


def _apply_source(row: dict, source: dict) -> None:
    """Bind a source-reviewed audit to the checked PDF and its literal page text."""
    rec = summaries.load_text(row["src"])
    pages = rec["pages"] if rec else []
    page = source["page"]
    quote = source["quote"]
    if (not rec or rec["sha256"] != source["sha256"] or row["source_sha256"] != source["sha256"]
            or not 1 <= page <= len(pages) or row["dst"] not in quote
            or quote not in " ".join(pages[page - 1].split())):
        raise ValueError(f"{row['src']}->{row['dst']} audit source changed or quote missing on PDF page {page}")
    row.update(page=page, quote=quote, snippet=quote)


def apply(rows: list[dict], known: dict[str, dict], data: dict, decided: dict[str, str | None],
          report: dict | None = None) -> list[dict]:
    """Annotate citation rows in place with their audit decision and return the extra corrected rows.
    Decisions that no longer match an extracted edge are counted, never silently re-targeted."""
    by_edge = {(r["src"], r["dst"]): r for r in rows}
    extra, stats = [], {"applied": 0, "unmatched": [], "corrections_added": 0, "corrections_refused": []}
    by = data.get("auditor") or "extraction-audit"
    for d in data.get("decisions", []):
        r = by_edge.get((d["src"], d["dst"]))
        if r is None:
            stats["unmatched"].append(f"{d['src']}->{d['dst']}")
            continue
        if d.get("source"):
            _apply_source(r, d["source"])
        if d["decision"] == "role_corrected":
            r.update(kind=d["kind"], explicit_label=True)
        r.update(audit=d["decision"], audit_note=d["note"], audit_by=d.get("auditor") or by,
                 audit_date=d.get("date"))
        stats["applied"] += 1
        tgt = d.get("correct_to")
        if not tgt:
            continue
        meta = known.get(tgt)
        limit = decided.get(d["src"])
        if meta is None or (limit and meta.get("decision_date") and meta["decision_date"] > limit):
            stats["corrections_refused"].append(f"{d['src']}->{tgt}")
            continue
        if (d["src"], tgt) in by_edge:          # the right K-number is already cited elsewhere in the PDF
            continue
        extra.append({**r, "dst": tgt, "kind": "predicate", "confidence": 0.7,
                      "method": r["method"] + "+audit-correction",
                      "name_check": evidence.name_check(r["quote"], meta.get("device_name")),
                      "panel_check": evidence.panel_check(r.get("src_panel"), meta.get("advisory_committee")),
                      "explicit_label": False,
                      "audit": "corrected", "audit_note": d["note"], "audit_by": by,
                      "audit_date": d.get("date"), "corrected_from": d["dst"]})
        stats["corrections_added"] += 1
    if report is not None:
        report.update(stats)
    return extra
