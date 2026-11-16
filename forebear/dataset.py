"""Turn cached openFDA records + summary text into graph rows (devices, citations, recalls).

Shared by the bulk build (scripts/build_graph.py) and incremental ingestion (ingest.py),
so a clearance added live is processed exactly like one in the shipped dataset.
"""
from __future__ import annotations

import re

from . import openfda, summaries
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
    if summ:
        status = summ["status"]
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
        "decision": rec.get("decision_description"),
        "clearance_type": rec.get("clearance_type"),
        "summary_status": status,
        "summary_url": (summ or {}).get("url"),
        "summary_sha256": (summ or {}).get("sha256"),
        "in_scope": in_scope,
        # lineage_known: we read this device's own predicates from its summary
        "lineage_known": bool(summ and summ["status"] == "ok"),
        "pmn_url": PMN_URL.format(k=k),
    }


# Generic words that do not identify a product (used by the name-consistency check).
_GENERIC = set("""system systems device devices ventilator ventilators mask masks cpap bipap series model unit
with and the for positive airway pressure nasal full face heated humidifier humidifiers therapy respiratory
breathing circuit circuits kit accessory accessories oral interface auto plus portable home non continuous
vented sleep apnea medical inc corp ltd llc company""".split())


def name_check(snippet: str, cited_name: str | None) -> str:
    """'match' if a distinctive word of the cited device's openFDA name appears near the citation,
    'mismatch' if none does (possible K-number typo in the PDF, or a name variant / OCR noise),
    'n/a' if the openFDA name has no distinctive word. Shown to the user; never used to drop edges."""
    toks = {w for w in re.findall(r"[a-z0-9]{3,}", (cited_name or "").lower())
            if w not in _GENERIC and not w.isdigit()}
    if not toks:
        return "n/a"
    low = (snippet or "").lower()
    return "match" if any(t in low for t in toks) else "mismatch"


def citation_rows(k: str, received: str | None, decision: str | None,
                  known: dict[str, dict], report: dict | None = None) -> list[dict]:
    """Predicate/reference edges from k's summary, validated against openFDA:
    the cited K must exist and must have been decided on/before the citing clearance."""
    rec = summaries.load(k)
    if not rec or rec["status"] != "ok":
        return []
    rows = []
    limit = received or decision
    for h in extract_from_summary(rec, self_k=k):
        tgt = known.get(h["k"])
        if tgt is None:
            _bump(report, "dropped_unresolved")
            continue
        if limit and tgt.get("decision_date") and tgt["decision_date"] > (decision or limit):
            _bump(report, "dropped_future")
            continue
        _bump(report, f"kept_{h['kind']}")
        nc = name_check(h["snippet"], tgt.get("device_name"))
        if h["kind"] == "predicate" and nc == "mismatch":
            _bump(report, "predicate_name_mismatch")
        rows.append({"src": k, "dst": h["k"], "kind": h["kind"], "confidence": h["confidence"],
                     "page": h["page"], "snippet": h["snippet"][:400], "method": "regex-context-v2",
                     "source_url": rec.get("url"), "name_check": nc})
    return rows


def mark_no_predicate(devices: list[dict], citations: list[dict]) -> int:
    """A summary we could read but that yielded no predicate citation is NOT known lineage."""
    with_pred = {c["src"] for c in citations if c["kind"] == "predicate"}
    n = 0
    for d in devices:
        if d.get("lineage_known") and d["k"] not in with_pred:
            d["lineage_known"] = False
            d["summary_status"] = "ok_no_predicate_found"
            n += 1
    return n


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


def _bump(report: dict | None, key: str) -> None:
    if report is not None:
        report[key] = report.get(key, 0) + 1


def fetch_recalls_for(k_numbers: list[str], use_cache: bool = True) -> list[dict]:
    recs = openfda.recalls_by_k(k_numbers, use_cache=use_cache)
    enf = openfda.enforcement_by_event({r.get("res_event_number") for r in recs}, use_cache=use_cache)
    return recall_rows(recs, enf)
