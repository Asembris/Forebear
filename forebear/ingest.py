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
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import openfda, summaries
from .dataset import citation_rows, device_row, fetch_recalls_for, mark_no_predicate
from .graph import Graph
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


def fetch_clearance(k: str, use_cache: bool = True) -> Fetched:
    k = normalise_k(k)
    try:
        meta = openfda.clearances_by_k([k], use_cache=use_cache)
    except Exception as e:  # network down, openFDA outage
        raise IngestError(f"openFDA lookup failed: {e}") from e
    meta = [m for m in meta if m.get("k_number") == k]
    if not meta:
        raise IngestError(f"{k} is not a 510(k) clearance in openFDA")
    try:
        summ = summaries.fetch(k)
    except Exception as e:
        raise IngestError(f"Could not download the 510(k) summary: {e}") from e
    if summ["status"] == "error":
        raise IngestError(f"Could not download the 510(k) summary: {summ.get('error')}")
    cited = [h["k"] for h in extract_from_summary(summ, self_k=k)] if summ["status"] == "ok" else []
    return Fetched(k, meta[0], summ, cited)


def present_devices(g: Graph, ks: list[str]) -> dict[str, dict]:
    if not ks:
        return {}
    rows = g.q("MATCH (d:Device) WHERE d.k IN $ks RETURN d.k AS k, toString(d.decision_date) AS decision_date, "
               "d.name AS device_name, d.in_scope AS in_scope, d.lineage_known AS lineage_known", {"ks": ks})
    return {r["k"]: r for r in rows}


def fetch_related(f: Fetched, present: dict[str, dict], use_cache: bool = True) -> Related:
    missing = [c for c in f.cited if c not in present]
    try:
        cited_meta = {m["k_number"]: m for m in openfda.clearances_by_k(missing, use_cache=use_cache)} if missing else {}
        recalls = fetch_recalls_for([f.k] + list(cited_meta), use_cache=use_cache)
    except Exception as e:
        raise IngestError(f"openFDA lookup failed: {e}") from e
    known = {c: {"decision_date": p["decision_date"], "device_name": p["device_name"]}
             for c, p in present.items() if c in f.cited and p.get("decision_date")}
    known.update({c: m for c, m in cited_meta.items()})
    return Related(cited_meta, recalls, known)


def write(g: Graph, f: Fetched, rel: Related, existing: dict | None) -> dict:
    before = g.stats()
    in_scope = bool(existing and existing.get("in_scope"))
    devices = [device_row(f.rec, in_scope)] + [device_row(m, False, read_summary=False)
                                                for m in rel.cited_meta.values()]
    report: dict = {}
    cits = citation_rows(f.k, f.rec.get("date_received"), f.rec.get("decision_date"), rel.known, report)
    mark_no_predicate(devices[:1], cits)
    g.conn.autocommit = False
    try:
        g.upsert_devices(devices)
        g.upsert_citations(cits)
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
        "citations_added": cits, "new_devices": list(rel.cited_meta),
        "recalls_linked": [r["id"] for r in rel.recalls], "extraction": report,
        "graph_before": before["nodes"], "graph_after": after["nodes"],
        "rels_before": before["relationships"], "rels_after": after["relationships"],
    }


def add_clearance(g: Graph, k: str, use_cache: bool = True) -> dict:
    """Synchronous composition of the phases (scripts, tests, MCP-less use)."""
    k = normalise_k(k)
    existing = g.device(k)
    f = fetch_clearance(k, use_cache)
    rel = fetch_related(f, present_devices(g, f.cited), use_cache)
    return write(g, f, rel, existing)
