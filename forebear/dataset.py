"""Turn cached openFDA records + summary text into graph rows (devices, citations, recalls).

Shared by the bulk build (scripts/build_graph.py) and incremental ingestion (ingest.py),
so a clearance added live is processed exactly like one in the shipped dataset.
"""
from __future__ import annotations

import json
import re

from . import evidence, openfda, summaries
from .config import SUMMARY_MIN_YEAR, is_design_related
from .predicates import extract_from_summary

PMN_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k}"
RES_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id={id}"


def company_key(applicant: str | None) -> str:
    """Light normalisation so 'Respironics, Inc.' and 'RESPIRONICS INC' share a node."""
    s = (applicant or "UNKNOWN").upper()
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"\b(INC|INCORPORATED|LLC|LTD|LIMITED|CORP|CORPORATION|CO|GMBH|AG|SA|BV|AB|PLC)\b", " ", s)
    return " ".join(s.split()) or "UNKNOWN"


def device_row(rec: dict, in_scope: bool, read_summary: bool = True) -> dict:
    """read_summary=False for devices whose citations we do not extract (out-of-family
    predicates in the bulk build), so they are never marked lineage_known by accident."""
    k = rec["k_number"]
    summ = summaries.load(k) if read_summary else None
    text = summaries.load_text(k) if read_summary else None
    if summ:
        # "ocr" / "attachment_text": the PDF has no text layer, but text recovered from the same verified
        # bytes (local OCR, or the summary PDF embedded in a PDF Portfolio) is readable
        status = _recovered_status(text) if summ["status"] == "no_text" and text else summ["status"]
    elif not in_scope:
        status = "not_expanded"          # out-of-family predicate: metadata only
    elif (rec.get("statement_or_summary") or "").lower() != "summary":
        status = "statement_only"        # firm filed a 510(k) Statement; no public summary
    elif int((rec.get("decision_date") or "0")[:4]) < SUMMARY_MIN_YEAR:
        status = "pre_1996"
    else:
        status = "not_fetched"
    return {
        "k": k,
        "name": (rec.get("device_name") or "").strip(),
        "applicant": (rec.get("applicant") or "").strip(),
        "company": company_key(rec.get("applicant")),
        "decision_date": rec.get("decision_date") or None,
        "received_date": rec.get("date_received") or None,
        "product_code": rec.get("product_code") or None,
        "panel": rec.get("advisory_committee") or None,
        "decision": rec.get("decision_description"),
        "clearance_type": rec.get("clearance_type"),
        "summary_status": status,
        "summary_url": (summ or {}).get("url"),
        "summary_sha256": (summ or {}).get("sha256"),
        "in_scope": in_scope,
        "text_source": _text_source(text) if text else None,
        # lineage_known: we read this device's own predicates from its summary
        "lineage_known": bool(text),
        "unresolved_predicates": 0,       # filled by mark_unresolved()
        "unresolved_citations": None,
        "pmn_url": PMN_URL.format(k=k),
    }


def name_check(snippet: str, cited_name: str | None) -> str:
    """Kept for callers of the old API; see evidence.name_check (the version the build uses)."""
    return evidence.name_check(snippet, cited_name)


EXTRACTION_METHOD = "regex-context-v3"


def _text_source(rec: dict) -> str:
    """'pdf_text_layer', 'ocr' or 'embedded_pdf_attachment' for a summaries.load_text() record."""
    return (rec.get("ocr") or {}).get("method", "ocr") if rec.get("ocr") else "pdf_text_layer"


def _recovered_status(rec: dict) -> str:
    return "attachment_text" if _text_source(rec) == "embedded_pdf_attachment" else "ocr"


def citation_rows(k: str, received: str | None, decision: str | None,
                  known: dict[str, dict], report: dict | None = None,
                  unresolved: list[dict] | None = None, src_meta: dict | None = None) -> list[dict]:
    """Predicate/reference edges from k's summary, validated against openFDA:
    the cited K must exist and must have been decided on/before the citing clearance.

    Citations that fail validation are not edges, but they are not silently forgotten either:
    each one is appended to `unresolved` (if given) so the citing device can say its lineage is
    incomplete. `src_meta` is the citing device's openFDA record (for the panel cross-check)."""
    rec = summaries.load_text(k)
    if not rec:
        return []
    rows = []
    limit = received or decision
    src_panel = (src_meta or known.get(k) or {}).get("advisory_committee")
    for h in extract_from_summary(rec, self_k=k):
        tgt = known.get(h["k"])
        why = None
        if tgt is None:
            why = "not_in_openfda"
            _bump(report, "dropped_unresolved")
        elif limit and tgt.get("decision_date") and tgt["decision_date"] > (decision or limit):
            why = "cleared_after_citing_device"
            _bump(report, "dropped_future")
        if why:
            if unresolved is not None:
                unresolved.append({"src": k, "cited": h["k"], "kind": h["kind"], "reason": why,
                                   "page": h["page"], "quote": h["span"][:300]})
            continue
        _bump(report, f"kept_{h['kind']}")
        nc = evidence.name_check(h["span"], tgt.get("device_name"))
        pc = evidence.panel_check(src_panel, tgt.get("advisory_committee"))
        if h["kind"] == "predicate" and nc == "mismatch":
            _bump(report, "predicate_name_mismatch")
        if h["kind"] == "predicate" and pc == "different":
            _bump(report, "predicate_panel_mismatch")
        rows.append({"src": k, "dst": h["k"], "kind": h["kind"], "confidence": h["confidence"],
                     "page": h["page"], "snippet": h["snippet"][:400], "quote": h["span"][:400],
                     "method": EXTRACTION_METHOD + {"ocr": "+ocr", "embedded_pdf_attachment": "+attachment"}.get(
                         _text_source(rec), ""),
                     "text_source": _text_source(rec),
                     "source_url": rec.get("url"), "source_sha256": rec.get("sha256"),
                     "name_check": nc, "name_check_method": evidence.NAME_CHECK_METHOD,
                     "panel_check": pc, "src_panel": src_panel, "explicit_label": h["explicit"]})
    return rows


def mark_no_predicate(devices: list[dict], citations: list[dict]) -> int:
    """A summary we could read but that yielded no predicate citation is NOT known lineage."""
    with_pred = {c["src"] for c in citations if c["kind"] == "predicate"}
    n = 0
    for d in devices:
        if d.get("lineage_known") and d["k"] not in with_pred:
            d["lineage_known"] = False
            st = d["summary_status"]
            d["summary_status"] = (st if st in ("ocr", "attachment_text") else "ok") + "_no_predicate_found"
            n += 1
    return n


def mark_unresolved(devices: list[dict], unresolved: list[dict]) -> int:
    """Record, on each citing device, the citations in its summary that could not become edges
    (cited K-number missing from openFDA, or cleared after the citing device). A device whose own
    summary names a predicate we could not resolve has an incomplete lineage, and must say so."""
    by: dict[str, list[dict]] = {}
    for u in unresolved:
        by.setdefault(u["src"], []).append(u)
    for d in devices:
        us = by.get(d["k"])
        if us:
            d["unresolved_predicates"] = sum(1 for u in us if u["kind"] == "predicate")
            d["unresolved_citations"] = json.dumps(us)
    return sum(len(v) for v in by.values())


def recall_rows(recs: list[dict], enforcement: list[dict]) -> list[dict]:
    cls = {e.get("recall_number"): e.get("classification") for e in enforcement}
    out, seen = [], set()
    for r in recs:
        rid = r.get("product_res_number") or f"cfres-{r.get('cfres_id')}"
        if rid in seen:
            continue
        seen.add(rid)
        rc = r.get("root_cause_description")
        out.append({
            "id": rid, "recall_number": r.get("product_res_number"), "event": r.get("res_event_number"),
            "classification": cls.get(r.get("product_res_number")),
            "root_cause": rc, "design_related": is_design_related(rc),
            "initiated": r.get("event_date_initiated") or None, "status": r.get("recall_status"),
            "firm": r.get("recalling_firm"), "reason": (r.get("reason_for_recall") or "")[:600],
            "product": (r.get("product_description") or "")[:300],
            "url": RES_URL.format(id=r.get("cfres_id")) if r.get("cfres_id") else None,
            "product_code": r.get("product_code"),
            "k_numbers": sorted(set(r.get("k_numbers") or [])),
        })
    return out


def link_recalls(recalls: list[dict], devices: dict[str, dict]) -> dict:
    """Attach per-device link evidence to each recall row (stored on the SUBJECT_OF edge).

    The join itself is FDA's: openFDA lists the 510(k) numbers of the recalled product. These checks
    only say how well the rest of the record agrees with that join:
      name_check        does the recall's product/reason text name the linked device?
      before_clearance  the recall started before the linked device was cleared (FDA lists later
                        clearances of the same product family on older recalls; the timing of such a
                        recall relative to that device is not meaningful)"""
    stats = {"links": 0, "name_mismatch": 0, "before_clearance": 0}
    for r in recalls:
        text = f"{r.get('product') or ''} {r.get('reason') or ''}"
        links = []
        for k in r["k_numbers"]:
            d = devices.get(k)
            if d is None:
                continue
            nc = evidence.name_check(text, d.get("name") or d.get("device_name"))
            dd = d.get("decision_date")
            before = bool(r.get("initiated") and dd and r["initiated"] < dd)
            links.append({"k": k, "name_check": nc, "before_clearance": before})
            stats["links"] += 1
            stats["name_mismatch"] += nc == "mismatch"
            stats["before_clearance"] += before
        r["links"] = links
    return stats


def unattributed_recalls(recs: list[dict], known: set[str]) -> list[dict]:
    """Recall records filed under a product code that name no 510(k) in the graph: they exist, but no
    lineage query can see them. Kept on the ProductCode node so assessments can say so."""
    out = []
    for r in recall_rows(recs, []):
        if not set(r["k_numbers"]) & known:
            out.append({key: r[key] for key in ("id", "event", "root_cause", "design_related", "initiated",
                                                "firm", "product", "url", "k_numbers")})
    return sorted(out, key=lambda r: r["id"])


def _bump(report: dict | None, key: str) -> None:
    if report is not None:
        report[key] = report.get(key, 0) + 1


def fetch_recalls_for(k_numbers: list[str], use_cache: bool = True) -> list[dict]:
    recs = openfda.recalls_by_k(k_numbers, use_cache=use_cache)
    enf = openfda.enforcement_by_event({r.get("res_event_number") for r in recs}, use_cache=use_cache)
    return recall_rows(recs, enf)
