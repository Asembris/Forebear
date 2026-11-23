"""Incremental ingestion: add (or deepen) one 510(k) clearance in the live Relate graph.

Same code path as the bulk build: fetch openFDA metadata -> fetch the summary PDF ->
extract predicates -> validate against openFDA -> MERGE devices, citations and recalls.
Running it on an out-of-family ancestor whose summary was never read *extends* the
lineage by one generation, which is how a user grows the graph where it matters.

The work is split into phases so the API can run the slow network phases OFF the single
Relate thread (other requests keep working during a PDF download) and only the short graph
reads and the one write transaction on it:

    fetch_clearance(k)            network   -> Fetched
    present_devices(g, ks)        graph     -> which cited K-numbers already exist
    fetch_related(fetched, present) network -> metadata for new predicates + recall rows
    write(g, fetched, related)    graph     -> one transaction, rollback on error

Re-ingesting a clearance reconciles its citations inside that same transaction: citation edges the refreshed
summary no longer supports are retired (graph.retire_citations), not deleted, so human reviews, LLM labels, audit
decisions and source provenance survive and an edge comes back if a later summary cites the device again.
Reconciliation only runs when the refreshed summary text was actually read: an unreadable download never wipes
existing lineage.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import audit, openfda, summaries
from .dataset import (citation_rows, device_row, fetch_recalls_for, link_recalls, mark_no_predicate,
                      mark_unresolved)
from .graph import MACHINE_REVIEWER, Graph
from .predicates import extract_from_summary


class IngestError(Exception):
    pass


@dataclass
class Fetched:
    k: str
    rec: dict
    summ: dict
    cited: list[str]


@dataclass
class Related:
    cited_meta: dict[str, dict]
    recalls: list[dict]
    known: dict[str, dict] = field(default_factory=dict)


def normalise_k(k: str) -> str:
    k = (k or "").strip().upper()
    if not (len(k) == 7 and k[0] == "K" and k[1:].isdigit()):
        raise IngestError("Expected a 510(k) number like K252078")
    return k


def fetch_clearance(k: str, use_cache: bool = True, refresh: bool = False) -> Fetched:
    """refresh=True re-downloads the summary PDF (summaries.refresh) instead of reusing the cached text, so a changed
    FDA document is detected; it raises IngestError, writing nothing, unless the new PDF is readable."""
    k = normalise_k(k)
    try:
        meta = openfda.clearances_by_k([k], use_cache=use_cache)
    except Exception as e:  # network down, openFDA outage
        raise IngestError(f"openFDA lookup failed: {e}") from e
    meta = [m for m in meta if m.get("k_number") == k]
    if not meta:
        raise IngestError(f"{k} is not a 510(k) clearance in openFDA")
    try:
        summ = summaries.refresh(k) if refresh else summaries.fetch(k)
    except summaries.RefreshError as e:
        raise IngestError(f"Summary refresh for {k} did not change the graph: {e}") from e
    except Exception as e:
        raise IngestError(f"Could not download the 510(k) summary: {e}") from e
    if summ["status"] == "error":
        raise IngestError(f"Could not download the 510(k) summary: {summ.get('error')}")
    text = summaries.load_text(k)
    cited = [h["k"] for h in extract_from_summary(text, self_k=k)] if text else []
    return Fetched(k, meta[0], summ, cited)


def present_devices(g: Graph, ks: list[str]) -> dict[str, dict]:
    if not ks:
        return {}
    rows = g.q("MATCH (d:Device) WHERE d.k IN $ks RETURN d.k AS k, toString(d.decision_date) AS decision_date, "
               "d.name AS device_name, d.in_scope AS in_scope, d.lineage_known AS lineage_known, "
               "d.panel AS advisory_committee", {"ks": ks})
    return {r["k"]: r for r in rows}


def fetch_related(f: Fetched, present: dict[str, dict], use_cache: bool = True) -> Related:
    missing = [c for c in f.cited if c not in present]
    try:
        cited_meta = {m["k_number"]: m for m in openfda.clearances_by_k(missing, use_cache=use_cache)} if missing else {}
        recalls = fetch_recalls_for([f.k] + list(cited_meta), use_cache=use_cache)
    except Exception as e:
        raise IngestError(f"openFDA lookup failed: {e}") from e
    known = {c: {"decision_date": p["decision_date"], "device_name": p["device_name"],
                 "advisory_committee": p.get("advisory_committee")}
             for c, p in present.items() if c in f.cited and p.get("decision_date")}
    known.update({c: m for c, m in cited_meta.items()})
    return Related(cited_meta, recalls, known)


def write(g: Graph, f: Fetched, rel: Related, existing: dict | None) -> dict:
    before = g.stats()
    in_scope = bool(existing and existing.get("in_scope"))
    devices = [device_row(f.rec, in_scope)] + [device_row(m, False, read_summary=False)
                                                for m in rel.cited_meta.values()]
    report: dict = {}
    unresolved: list[dict] = []
    cits = citation_rows(f.k, f.rec.get("date_received"), f.rec.get("decision_date"), rel.known, report,
                         unresolved, src_meta=f.rec)
    # same audit decisions as the shipped build, so re-ingesting an audited clearance keeps them
    cits += audit.apply(cits, rel.known, audit.load(), {f.k: f.rec.get("decision_date") or f.rec.get("date_received")})
    mark_no_predicate(devices[:1], cits)
    mark_unresolved(devices[:1], unresolved)
    link_recalls(rel.recalls, {**rel.known, **{d["k"]: d for d in devices}})
    text = summaries.load_text(f.k)
    reconcile = bool(text and text.get("pages"))
    keep = sorted({c["dst"] for c in cits})
    prior = {r["dst"]: r["retired"] for r in g.q(
        "MATCH (:Device {k:$k})-[c:CITES]->(b:Device) RETURN b.k AS dst, c.retired_at IS NOT NULL AS retired",
        {"k": f.k})}
    g.conn.autocommit = False
    try:
        g.upsert_devices(devices)
        g.upsert_citations(cits)
        retired = g.retire_citations(f.k, keep, (text or {}).get("sha256")) if reconcile else []
        g.upsert_recalls(rel.recalls)
        g.conn.execute("MATCH (d:Device {k:$k}) SET d.ingested_live_at = datetime()", {"k": f.k})
        g.conn.commit()
    except Exception:
        g.conn.rollback()
        raise
    finally:
        g.conn.autocommit = True
    after = g.stats()
    return {
        "k": f.k, "was_present": existing is not None,
        "lineage_was_known": bool(existing and existing.get("lineage_known")),
        "summary_status": devices[0]["summary_status"], "summary_url": f.summ.get("url"),
        "summary_sha256": f.summ.get("sha256"), "refresh": f.summ.get("refresh"),
        "citations_added": cits, "citations_unresolved": unresolved, "new_devices": list(rel.cited_meta),
        "reconciliation": {
            "ran": reconcile,
            "skipped_reason": None if reconcile else "refreshed summary text not readable; existing citations kept",
            "new": [d for d in keep if d not in prior],
            "restored": [d for d in keep if prior.get(d)],
            "retired": retired,
            "retired_with_human_review": [r["dst"] for r in retired
                                          if r.get("review") and r.get("reviewer") != MACHINE_REVIEWER]},
        "recalls_linked": [r["id"] for r in rel.recalls], "extraction": report,
        "graph_before": before["nodes"], "graph_after": after["nodes"],
        "rels_before": before["relationships"], "rels_after": after["relationships"],
    }


def add_clearance(g: Graph, k: str, use_cache: bool = True, refresh: bool = False) -> dict:
    """Synchronous composition of the phases (scripts, tests, MCP-less use)."""
    k = normalise_k(k)
    existing = g.device(k)
    f = fetch_clearance(k, use_cache, refresh)
    rel = fetch_related(f, present_devices(g, f.cited), use_cache)
    return write(g, f, rel, existing)
