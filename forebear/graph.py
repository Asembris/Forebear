"""Relate graph layer: schema, idempotent upserts and the lineage queries.

Schema (labels / relationship types):

  (:Device {k, name, applicant, decision_date, received_date, product_code, decision,
            clearance_type, summary_status, summary_url, summary_sha256, in_scope,
            lineage_known})
  (:ProductCode {code, name, device_class, regulation})
  (:Company {name})
  (:Recall {id, recall_number, event, classification, root_cause, design_related,
            initiated, status, firm, reason, product, url})
  (:Assessment {id, created_at, target_k, verdict, payload, memo, memo_source})

  (Device)-[:CITES {kind: predicate|reference|mention, confidence, page, snippet, quote,
                    method, text_source, source_url, source_sha256, name_check, panel_check,
                    audit, audit_note, audit_by, corrected_from,       <- extraction audit (not human)
                    review, review_note, reviewer, reviewed_at,        <- human review in the app
                    ai_label, ai_quote, ai_model, ai_at}]->(Device)    <- optional LLM triage
  (Device)-[:SUBJECT_OF]->(Recall)
  (Device)-[:IN_CODE]->(ProductCode)
  (Device)-[:FILED_BY]->(Company)
  (Assessment)-[:ASSESSED]->(Device)
  (Assessment)-[:FLAGGED]->(Recall)

All writes are MERGE-based so ingesting the same clearance twice is a no-op, and
incremental ingestion of a single new clearance uses the same code path as the bulk build.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import relate

SCHEMA = [
    "CREATE INDEX device_k IF NOT EXISTS FOR (d:Device) ON (d.k)",
    "CREATE INDEX recall_id IF NOT EXISTS FOR (r:Recall) ON (r.id)",
    "CREATE INDEX code_code IF NOT EXISTS FOR (p:ProductCode) ON (p.code)",
    "CREATE INDEX company_name IF NOT EXISTS FOR (c:Company) ON (c.name)",
    "CREATE INDEX assessment_id IF NOT EXISTS FOR (a:Assessment) ON (a.id)",
]
FULLTEXT = "CREATE FULLTEXT INDEX device_text IF NOT EXISTS FOR (d:Device) ON EACH [d.name, d.applicant]"

# Rule: a human confirmed it, OR (the extractor says predicate, or the LLM triage labelled an ambiguous
# mention as predicate, quote-checked) and the extraction audit did not find it wrong - unless a human
# rejected it. Humans always win; the audit outranks the extractor and the LLM.
SOURCE_ROLE_MCP_REVIEW = "(coalesce(r.audit, '') = 'role_corrected' AND coalesce(r.reviewer, '') = 'mcp-client')"
LINEAGE_EDGE = (f"(coalesce(r.review, '') <> 'rejected' OR {SOURCE_ROLE_MCP_REVIEW}) AND "
                f"((r.review = 'confirmed' AND NOT {SOURCE_ROLE_MCP_REVIEW}) OR "
                "(NOT coalesce(r.audit, '') IN ['error', 'not_predicate'] AND "
                "(r.kind = 'predicate' OR (r.ai_label = 'predicate' AND coalesce(r.audit, '') <> 'role_corrected'))))")
DISPUTED_EDGE = ("coalesce(r.audit, '') = 'unresolved' AND "
                 "(coalesce(r.review, '') <> 'confirmed' OR coalesce(r.reviewer, '') = 'mcp-client')")


class Graph:
    """One connection per process; callers must use it from a single thread (Relate
    connections are thread-affine). The API layer pins it to a dedicated worker thread."""

    def __init__(self, path: str | Path, read_only: bool = False):
        self.path = str(path)
        self.read_only = read_only
        self.conn = relate.connect(self.path, read_only=read_only) if read_only else relate.connect(self.path)

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ helpers
    def q(self, cypher: str, params: dict | None = None) -> list[dict]:
        return [dict(r) for r in self.conn.execute(cypher, params or {})]

    def ensure_schema(self) -> None:
        for s in SCHEMA:
            self.conn.execute(s)
        try:
            self.conn.execute(FULLTEXT)
        except relate.Error:
            # Older engines without IF NOT EXISTS on full-text: ignore "already exists".
            pass

    # ------------------------------------------------------------------ writes
    def upsert_product_codes(self, rows: list[dict]) -> None:
        self.conn.execute(
            "UNWIND $rows AS r MERGE (p:ProductCode {code: r.code}) "
            "SET p.name = r.name, p.device_class = r.device_class, p.regulation = r.regulation, "
            "p.unattributed_recalls = r.unattributed_recalls, "
            "p.unattributed_recalls_n = coalesce(r.unattributed_recalls_n, 0), "
            "p.unattributed_design_recalls_n = coalesce(r.unattributed_design_recalls_n, 0)",
            {"rows": rows})

    def upsert_devices(self, rows: list[dict]) -> None:
        """rows: dicts with keys k, name, applicant, company, decision_date, received_date,
        product_code, decision, clearance_type, summary_status, summary_url, summary_sha256,
        in_scope, lineage_known."""
        for i in range(0, len(rows), 500):
            self.conn.execute(
                """UNWIND $rows AS r
                MERGE (d:Device {k: r.k})
                SET d.name = r.name, d.applicant = r.applicant,
                    d.decision_date = CASE WHEN r.decision_date IS NULL THEN NULL ELSE date(r.decision_date) END,
                    d.received_date = CASE WHEN r.received_date IS NULL THEN NULL ELSE date(r.received_date) END,
                    d.product_code = r.product_code, d.decision = r.decision,
                    d.clearance_type = r.clearance_type, d.summary_status = r.summary_status,
                    d.summary_url = r.summary_url, d.summary_sha256 = r.summary_sha256,
                    d.in_scope = r.in_scope, d.lineage_known = r.lineage_known,
                    d.text_source = r.text_source, d.panel = r.panel,
                    d.unresolved_predicates = coalesce(r.unresolved_predicates, 0),
                    d.unresolved_citations = r.unresolved_citations
                WITH d, r
                MERGE (c:Company {name: r.company})
                MERGE (d)-[:FILED_BY]->(c)
                WITH d, r WHERE r.product_code IS NOT NULL
                MERGE (p:ProductCode {code: r.product_code})
                MERGE (d)-[:IN_CODE]->(p)""",
                {"rows": rows[i:i + 500]})

    def upsert_citations(self, rows: list[dict]) -> None:
        """rows: {src, dst, kind, confidence, page, snippet, quote, method, source_url, ...}.
        An existing human review or LLM label on the edge is preserved; audit fields are rewritten
        (a row without them clears a stale audit decision)."""
        for i in range(0, len(rows), 500):
            self.conn.execute(
                """UNWIND $rows AS r
                MATCH (a:Device {k: r.src}) MATCH (b:Device {k: r.dst})
                MERGE (a)-[c:CITES]->(b)
                SET c.kind = r.kind, c.confidence = r.confidence, c.page = r.page,
                    c.snippet = r.snippet, c.quote = r.quote, c.method = r.method,
                    c.text_source = r.text_source, c.source_url = r.source_url,
                    c.source_sha256 = r.source_sha256, c.name_check = r.name_check,
                    c.name_check_method = r.name_check_method, c.panel_check = r.panel_check,
                    c.explicit_label = r.explicit_label,
                    c.audit = r.audit, c.audit_note = r.audit_note, c.audit_by = r.audit_by,
                    c.audit_date = r.audit_date, c.corrected_from = r.corrected_from""",
                {"rows": rows[i:i + 500]})

    def upsert_recalls(self, rows: list[dict]) -> None:
        """rows: recall dicts incl. k_numbers list; links each to the devices it names. Optional
        `links` carry per-device evidence (dataset.link_recalls); existing evidence is kept otherwise."""
        rows = [{**r, "links": r.get("links", []) + [{"k": k, "name_check": None, "before_clearance": None}
                                                     for k in r["k_numbers"]
                                                     if k not in {x["k"] for x in r.get("links", [])}]}
                for r in rows]
        for i in range(0, len(rows), 500):
            self.conn.execute(
                """UNWIND $rows AS r
                MERGE (x:Recall {id: r.id})
                SET x.recall_number = r.recall_number, x.event = r.event,
                    x.classification = r.classification, x.root_cause = r.root_cause,
                    x.design_related = r.design_related,
                    x.initiated = CASE WHEN r.initiated IS NULL THEN NULL ELSE date(r.initiated) END,
                    x.status = r.status, x.firm = r.firm, x.reason = r.reason,
                    x.product = r.product, x.url = r.url, x.product_code = r.product_code
                WITH x, r
                UNWIND r.links AS l
                MATCH (d:Device {k: l.k})
                MERGE (d)-[s:SUBJECT_OF]->(x)
                SET s.name_check = coalesce(l.name_check, s.name_check),
                    s.before_clearance = coalesce(l.before_clearance, s.before_clearance)""",
                {"rows": rows[i:i + 500]})

    def review_citation(self, src: str, dst: str, status: str, note: str | None,
                        reviewer: str = "user") -> dict | None:
        if status not in ("confirmed", "rejected", ""):
            raise ValueError("status must be confirmed, rejected or empty")
        rows = self.q(
            """MATCH (a:Device {k:$src})-[c:CITES]->(b:Device {k:$dst})
            SET c.review = $status, c.review_note = $note, c.reviewed_at = datetime(), c.reviewer = $reviewer
            RETURN a.k AS src, b.k AS dst, c.kind AS kind, c.review AS review""",
            {"src": src, "dst": dst, "status": status or None, "note": note, "reviewer": reviewer})
        return rows[0] if rows else None

    def set_triage(self, src: str, dst: str, label: str, quote: str, model: str) -> dict | None:
        rows = self.q(
            """MATCH (a:Device {k:$src})-[c:CITES]->(b:Device {k:$dst})
            SET c.ai_label = $label, c.ai_quote = $quote, c.ai_model = $model, c.ai_at = datetime()
            RETURN a.k AS src, b.k AS dst, c.kind AS kind, c.ai_label AS ai_label, c.review AS review""",
            {"src": src, "dst": dst, "label": label, "quote": quote, "model": model})
        return rows[0] if rows else None

    def citation(self, src: str, dst: str) -> dict | None:
        rows = self.q("""MATCH (a:Device {k:$src})-[c:CITES]->(b:Device {k:$dst})
            RETURN c.kind AS kind, c.snippet AS snippet""", {"src": src, "dst": dst})
        return rows[0] if rows else None

    def save_assessment(self, target_k: str, verdict: str, payload: dict, memo: str,
                        memo_source: str, recall_ids: list[str]) -> str:
        aid = "A-" + uuid.uuid4().hex[:10]
        self.conn.execute(
            """MATCH (d:Device {k:$k})
            CREATE (a:Assessment {id:$id, created_at: datetime(), target_k:$k, verdict:$verdict,
                                  payload:$payload, memo:$memo, memo_source:$src})
            CREATE (a)-[:ASSESSED]->(d)
            WITH a UNWIND $recalls AS rid
            MATCH (x:Recall {id: rid}) MERGE (a)-[:FLAGGED]->(x)""",
            {"k": target_k, "id": aid, "verdict": verdict, "payload": json.dumps(payload),
             "memo": memo, "src": memo_source, "recalls": recall_ids})
        return aid

    # ------------------------------------------------------------------ reads
    def stats(self) -> dict:
        nodes = {r["label"]: r["c"] for r in self.q(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS c")}
        rels = {r["t"]: r["c"] for r in self.q("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")}
        cites = {r["kind"]: r["c"] for r in self.q(
            "MATCH ()-[r:CITES]->() RETURN r.kind AS kind, count(*) AS c")}
        return {"nodes": nodes, "relationships": rels, "citations_by_kind": cites}

    def device(self, k: str) -> dict | None:
        rows = self.q(
            """MATCH (d:Device {k:$k})
            OPTIONAL MATCH (d)-[s:SUBJECT_OF]->(x:Recall)
            OPTIONAL MATCH (d)-[:IN_CODE]->(p:ProductCode)
            RETURN d {.*} AS device, p {.*} AS code,
                   collect(DISTINCT x {.*, link_name_check: s.name_check,
                                       linked_before_clearance: s.before_clearance}) AS recalls""", {"k": k})
        if not rows:
            return None
        r = rows[0]
        return {**_clean(r["device"]), "product": _clean(r["code"]),
                "recalls": [_clean(x) for x in r["recalls"] if x]}

    def search(self, text: str, limit: int = 12) -> list[dict]:
        text = text.strip()
        if not text:
            return []
        if text.upper().startswith("K") and text[1:].isdigit():
            return self.q("""MATCH (d:Device) WHERE d.k STARTS WITH $p
                RETURN d.k AS k, d.name AS name, d.applicant AS applicant,
                       toString(d.decision_date) AS decision_date, d.product_code AS product_code
                ORDER BY d.k LIMIT $n""", {"p": text.upper(), "n": limit})
        safe = " ".join(w for w in "".join(ch if ch.isalnum() else " " for ch in text).split())
        if not safe:
            return []
        query = " ".join(f"{w}~" if len(w) > 3 else w for w in safe.split())
        return self.q("""CALL db.index.fulltext.queryNodes('device_text', $q) YIELD node, score
            RETURN node.k AS k, node.name AS name, node.applicant AS applicant,
                   toString(node.decision_date) AS decision_date, node.product_code AS product_code, score
            ORDER BY score DESC LIMIT $n""", {"q": query, "n": limit})

    def ancestors(self, k: str, depth: int = 4) -> list[dict]:
        """Every predicate ancestor up to `depth` generations, with the shortest citation chain
        (and the evidence on each hop) and the ancestor's recalls."""
        return self._lineage(k, depth, direction="up")

    def descendants(self, k: str, depth: int = 3) -> list[dict]:
        return self._lineage(k, depth, direction="down")

    def _lineage(self, k: str, depth: int, direction: str) -> list[dict]:
        depth = max(1, min(int(depth), 8))
        pattern = (f"(d:Device {{k:$k}})-[:CITES*1..{depth}]->(a:Device)" if direction == "up"
                   else f"(d:Device {{k:$k}})<-[:CITES*1..{depth}]-(a:Device)")
        rows = self.q(
            f"""MATCH p = {pattern}
            WHERE a.k <> $k AND all(r IN relationships(p) WHERE {LINEAGE_EDGE})
            WITH a, p ORDER BY length(p)
            WITH a, collect(p)[0] AS p, count(p) AS routes
            OPTIONAL MATCH (a)-[s:SUBJECT_OF]->(x:Recall)
            WITH a, p, routes, collect(DISTINCT x {{.*, link_name_check: s.name_check,
                                                   linked_before_clearance: s.before_clearance}}) AS recalls
            RETURN a {{.*}} AS device, length(p) AS gen, routes,
                   [n IN nodes(p) | n.k] AS chain,
                   [r IN relationships(p) | {{src: startNode(r).k, dst: endNode(r).k, page: r.page,
                        snippet: r.snippet, confidence: r.confidence, review: r.review, reviewer: r.reviewer,
                        name_check: r.name_check, source_url: r.source_url, kind: r.kind,
                        audit: r.audit, audit_note: r.audit_note, ai_label: r.ai_label,
                        text_source: r.text_source, panel_check: r.panel_check,
                        quote: r.quote, method: r.method}}] AS hops,
                   recalls
            ORDER BY gen, device.decision_date""", {"k": k})
        out = []
        for r in rows:
            out.append({**_clean(r["device"]), "gen": r["gen"], "routes": r["routes"],
                        "chain": r["chain"], "hops": r["hops"],
                        "recalls": [_clean(x) for x in r["recalls"] if x]})
        return out

    def direct_citations(self, k: str) -> list[dict]:
        """All extracted citations from k (any kind, incl. rejected) for the review panel."""
        return [{**r, "dst_decision_date": str(r["dst_decision_date"]) if r["dst_decision_date"] else None}
                for r in self.q(
            """MATCH (d:Device {k:$k})-[c:CITES]->(b:Device)
            RETURN b.k AS dst, b.name AS name, b.applicant AS applicant, b.decision_date AS dst_decision_date,
                   c.kind AS kind, c.confidence AS confidence, c.page AS page, c.snippet AS snippet,
                   c.review AS review, c.review_note AS review_note, c.source_url AS source_url,
                   c.ai_label AS ai_label, c.ai_quote AS ai_quote, c.ai_model AS ai_model,
                   c.name_check AS name_check, c.reviewer AS reviewer,
                   c.panel_check AS panel_check, c.quote AS quote, c.method AS method,
                   c.text_source AS text_source, c.audit AS audit, c.audit_note AS audit_note,
                   c.audit_by AS audit_by, c.corrected_from AS corrected_from
            ORDER BY CASE c.kind WHEN 'predicate' THEN 0 WHEN 'reference' THEN 1 ELSE 2 END, b.k""",
            {"k": k})]

    def lineage_edges_from(self, ks: list[str]) -> list[dict]:
        """Every lineage edge leaving the given devices, on any route (the ancestor query keeps only one
        shortest path per ancestor, so a doubtful edge on another route would otherwise go unseen)."""
        if not ks:
            return []
        return self.q(
            f"""MATCH (a:Device)-[r:CITES]->(b:Device) WHERE a.k IN $ks AND {LINEAGE_EDGE}
            RETURN a.k AS src, b.k AS dst, r.page AS page, r.snippet AS snippet, r.confidence AS confidence,
                   r.review AS review, r.reviewer AS reviewer, r.name_check AS name_check,
                   r.source_url AS source_url, r.kind AS kind, r.audit AS audit, r.audit_note AS audit_note,
                   r.ai_label AS ai_label, r.text_source AS text_source, r.panel_check AS panel_check,
                   r.quote AS quote, r.method AS method
            ORDER BY src, dst""", {"ks": list(ks)})

    def out_of_lineage_predicates(self, k: str) -> list[dict]:
        """Citations the extractor read as predicates that do not count in lineage queries (removed by
        the audit or rejected by a person), minus K-number typos the audit corrected to another edge."""
        rows = self.q(
            f"""MATCH (d:Device {{k:$k}})-[r:CITES]->(b:Device)
            RETURN b.k AS dst, r.kind AS kind, r.page AS page, r.quote AS quote, r.snippet AS snippet,
                   r.review AS review, r.review_note AS review_note, r.audit AS audit,
                   r.audit_note AS audit_note, r.corrected_from AS corrected_from,
                   ({LINEAGE_EDGE}) AS in_lineage""", {"k": k})
        corrected = {r["corrected_from"] for r in rows if r["corrected_from"] and r["in_lineage"]}
        return [r for r in rows if r["kind"] == "predicate" and not r["in_lineage"] and r["dst"] not in corrected]

    def cited_after_recall(self, design_only: bool = True, limit: int = 200) -> list[dict]:
        """Clearances whose (direct or 2nd-generation) predicate was already under a recall
        when the new device was cleared. A row is conditional if every shortest path
        to that recall holder contains an unresolved audit link."""
        flt = "AND x.design_related" if design_only else ""
        rows = self.q(
            f"""MATCH p = (d:Device)-[:CITES*1..2]->(a:Device)-[:SUBJECT_OF]->(x:Recall)
            WHERE all(r IN relationships(p) WHERE type(r) = 'SUBJECT_OF' OR ({LINEAGE_EDGE}))
              AND d.decision_date IS NOT NULL AND x.initiated IS NOT NULL
              AND x.initiated < d.decision_date {flt}
            WITH d, a, x, min(length(p)) - 1 AS gen,
                 min(CASE WHEN all(r IN relationships(p) WHERE NOT ({DISPUTED_EDGE}))
                          THEN length(p) ELSE null END) AS supported_length
            RETURN d.k AS k, d.name AS name, d.applicant AS applicant,
                   toString(d.decision_date) AS decision_date, toString(d.received_date) AS received_date,
                   a.k AS ancestor, a.name AS ancestor_name, gen,
                   (supported_length IS NULL OR supported_length > gen + 1) AS conditional,
                   x.id AS recall_id, x.event AS event, x.classification AS classification,
                   x.root_cause AS root_cause, toString(x.initiated) AS initiated, x.firm AS firm,
                   x.reason AS reason, x.url AS url
            ORDER BY decision_date DESC, gen LIMIT $n""", {"n": limit})
        return rows

    def recall_event_reach(self, event: str, depth: int = 3) -> dict:
        """For one recall event (or several, comma-separated): the clearances FDA lists on it and every
        later clearance that descends from them. See lineage.recall_reach for the timing classification."""
        events = [e.strip() for e in str(event).split(",") if e.strip()]
        devs = self.q("""MATCH (d:Device)-[s:SUBJECT_OF]->(x:Recall) WHERE x.event IN $es
            RETURN d.k AS k, d.name AS name, toString(d.decision_date) AS decision_date,
                   toString(min(x.initiated)) AS initiated, count(x) AS records,
                   collect(DISTINCT s.name_check) AS name_checks,
                   any(b IN collect(s.before_clearance) WHERE b) AS before_clearance
            ORDER BY k""", {"es": events})
        if not devs:
            return {"event": event, "recalled": [], "descendants": []}
        desc = self.q(
            f"""MATCH p = (s:Device)<-[:CITES*1..{max(1, min(depth, 6))}]-(d:Device)
            WHERE s.k IN $ks AND NOT d.k IN $ks AND all(r IN relationships(p) WHERE {LINEAGE_EDGE})
            WITH d, min(length(p)) AS gen,
                 min(CASE WHEN all(r IN relationships(p) WHERE NOT ({DISPUTED_EDGE})) THEN length(p) ELSE null END)
                     AS supported_gen,
                 collect(DISTINCT s.k) AS via,
                 collect(DISTINCT CASE WHEN all(r IN relationships(p) WHERE NOT ({DISPUTED_EDGE}))
                                       THEN s.k ELSE null END) AS supported_via
            RETURN d.k AS k, d.name AS name, d.applicant AS applicant,
                   toString(d.decision_date) AS decision_date, gen, supported_gen, via, supported_via
            ORDER BY d.decision_date DESC, d.k""", {"ks": [d["k"] for d in devs]})
        return {"event": event, "recalled": devs, "descendants": desc}

    def assessments(self, k: str | None = None, limit: int = 20) -> list[dict]:
        """Saved assessments, each with a `stale` flag: after it was saved, a citation somewhere in
        the assessed device's ancestry (4 generations) was reviewed or AI-labelled, or a device in
        that ancestry was (re-)ingested - so the saved verdict may no longer match the graph."""
        rows = self.q(
            """MATCH (a:Assessment)-[:ASSESSED]->(d:Device)
            WHERE $k IS NULL OR d.k = $k
            OPTIONAL MATCH (a)-[:FLAGGED]->(x:Recall)
            WITH a, d, collect(x.id) AS flagged
            OPTIONAL MATCH (d)-[:CITES*0..4]->(y:Device)-[c:CITES]->(:Device)
            WHERE c.reviewed_at > a.created_at OR c.ai_at > a.created_at
            WITH a, d, flagged, collect(DISTINCT y.k + '->' + endNode(c).k) AS changed_edges
            OPTIONAL MATCH (d)-[:CITES*0..4]->(z:Device) WHERE z.ingested_live_at > a.created_at
            WITH a, d, flagged, changed_edges, collect(DISTINCT z.k) AS reingested
            RETURN a.id AS id, toString(a.created_at) AS created_at, d.k AS k, d.name AS name,
                   a.verdict AS verdict, a.memo AS memo, a.memo_source AS memo_source, flagged,
                   changed_edges, reingested,
                   size(changed_edges) > 0 OR size(reingested) > 0 AS stale
            ORDER BY created_at DESC LIMIT $n""", {"k": k, "n": limit})
        return rows


def _clean(d: dict | None) -> dict | None:
    """Make Relate temporal values JSON-friendly."""
    if d is None:
        return None
    out = {}
    for key, v in d.items():
        if hasattr(v, "isoformat"):
            out[key] = v.isoformat()
        elif v is not None and type(v).__module__.startswith("relate"):
            out[key] = str(v)
        else:
            out[key] = v
    return out


def open_graph(path, read_only: bool = False) -> Graph:
    g = Graph(path, read_only=read_only)
    if not read_only:
        g.ensure_schema()
    return g
