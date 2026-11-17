"""Predicate due-diligence assessment built from Relate lineage queries.

The rules are deliberately simple and printed in the UI. They follow the recall-related
best practice in FDA's September 2023 draft guidance on predicate selection ("choose a
predicate that has not been subject to a design-related recall") and the lineage finding
of Kadakia et al., JAMA 2023 (devices whose predicates had Class I recalls had a higher
risk of their own Class I recall). A verdict is a *due-diligence signal*, never a safety
determination: recalls can be lot- or software-version-specific, and openFDA's root-cause
field is coarse.
"""
from __future__ import annotations

import json

from .graph import Graph

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1, "info": 0}


def _recall_ev(x: dict) -> dict:
    return {"type": "recall", "id": x["id"], "event": x.get("event"), "classification": x.get("classification"),
            "root_cause": x.get("root_cause"), "design_related": x.get("design_related"),
            "initiated": x.get("initiated"), "firm": x.get("firm"), "reason": x.get("reason"),
            "url": x.get("url"), "status": x.get("status")}


def _count(recs: list[dict]) -> str:
    """'N recall event(s) (M product record(s))': FDA files one record per product in an event."""
    events = {x.get("event") or x["id"] for x in recs}
    return f"{len(events)} recall event(s) ({len(recs)} product record(s))"


def assess(g: Graph, k: str, depth: int = 4) -> dict | None:
    dev = g.device(k)
    if dev is None:
        return None
    ancestors = g.ancestors(k, depth)
    descendants = g.descendants(k, 3)
    signals: list[dict] = []

    # D: the candidate's own recalls (one signal, all recalls as evidence)
    own = sorted(dev["recalls"], key=lambda x: x.get("initiated") or "", reverse=True)
    if own:
        design = [x for x in own if x.get("design_related")]
        class1 = [x for x in own if x.get("classification") == "Class I"]
        if design:
            sev, what = "high", _count(design) + ", design-related"
        elif class1:
            sev, what = "medium", _count(class1) + ", Class I (not design-related)"
        else:
            sev, what = "low", _count(own) + ", none design-related or Class I"
        signals.append({"code": "DIRECT_RECALL", "severity": sev, "title": f"{k} itself has {what}",
                        "evidence": [_recall_ev(x) for x in own], "chain": [k], "gen": 0})

    # A: recalls anywhere in the predicate ancestry, one signal per ancestor.
    # medium (-> REVIEW) when, within 2 generations, a recall is design-related and Class I/II or
    # not yet classified, or (direct predicate only) any Class I recall - the JAMA study's measure.
    for a in ancestors:
        hits = []
        for x in a["recalls"]:
            design = bool(x.get("design_related"))
            cls = x.get("classification")
            if (design and cls in ("Class I", "Class II", None) and a["gen"] <= 2) or                (cls == "Class I" and a["gen"] == 1):
                hits.append(("medium", x))
            elif design or cls == "Class I":
                hits.append(("low", x))
        if not hits:
            continue
        sev = "medium" if any(h[0] == "medium" for h in hits) else "low"
        recs = sorted((h[1] for h in hits), key=lambda x: x.get("initiated") or "", reverse=True)
        n_design = sum(1 for x in recs if x.get("design_related"))
        gen_word = {1: "Direct predicate", 2: "Grand-predicate"}.get(a["gen"], f"Generation-{a['gen']} ancestor")
        signals.append({
            "code": "ANCESTOR_RECALL", "severity": sev,
            "title": f"{gen_word} {a['k']} ({a.get('name') or 'unnamed'}) has {_count(recs)}"
                     f"{f', {n_design} record(s) design-related' if n_design else ''}",
            "evidence": [_recall_ev(x) for x in recs] + [{"type": "citation", **h} for h in a["hops"]],
            "chain": a["chain"], "gen": a["gen"]})

    # L: coverage gaps - be explicit about what we could not read
    unknown = [a for a in ancestors if not a.get("lineage_known")]
    if not dev.get("lineage_known"):
        signals.append({"code": "LINEAGE_UNKNOWN", "severity": "info",
                        "title": f"{k}'s own predicates could not be read "
                                 f"(summary status: {dev.get('summary_status')})", "evidence": [], "chain": [k]})
    if unknown:
        signals.append({"code": "LINEAGE_TRUNCATED", "severity": "info",
                        "title": f"Ancestry stops at {len(unknown)} device(s) whose own summaries were not read",
                        "evidence": [{"type": "device", "k": a["k"], "name": a.get("name"),
                                      "summary_status": a.get("summary_status")} for a in unknown[:12]],
                        "chain": []})

    # N/U: links in the ancestry whose evidence is doubtful. A doubtful link may route the ancestry to
    # the wrong device, and the right one may be missing, so these never count as "checked".
    seen, flagged, doubtful = set(), [], []
    for a in ancestors:
        for i, h in enumerate(a["hops"]):
            e = (h["src"], h["dst"])
            if e in seen:
                continue
            seen.add(e)
            why = doubt(h)
            if why:
                doubtful.append({"type": "citation", "doubt": why, "gen": i + 1, **h})
                if "name_mismatch" in why:
                    flagged.append({"type": "citation", **h})
    if flagged:
        signals.append({"code": "NAME_MISMATCH_IN_LINEAGE", "severity": "info",
                        "title": f"This ancestry uses {len(flagged)} link(s) where the cited device's FDA name does not "
                                 f"appear in the summary text (possible K-number typo). Verify them before relying on "
                                 f"the result.", "evidence": flagged, "chain": []})
    other = [d for d in doubtful if d["doubt"] != ["name_mismatch"]]
    if other:
        signals.append({"code": "UNCERTAIN_LINK_IN_LINEAGE", "severity": "info",
                        "title": f"{len(other)} link(s) in this ancestry rest on uncertain evidence (unresolved in the "
                                 f"extraction audit, cited device from another FDA panel, or labelled only by the LLM "
                                 f"and not confirmed by a person)", "evidence": other, "chain": []})

    # C: predicate citations in the candidate's (or a direct predicate's) own summary that did not become
    # lineage edges: K-number not in openFDA, cleared later, or removed by the audit or a reviewer.
    gen1 = [a for a in ancestors if a["gen"] == 1]
    missing = _missing_predicates(g, dev) + [m for a in gen1 for m in _missing_predicates(g, a)]
    if missing:
        signals.append({"code": "PREDICATE_CITATION_UNRESOLVED", "severity": "info",
                        "title": f"{len(missing)} predicate citation(s) in the summaries of {k} or its direct predicates "
                                 f"could not be resolved to a device in this graph, so part of the ancestry is missing",
                        "evidence": missing[:20], "chain": []})

    # F: how the family downstream has fared (context, not a verdict input)
    recalled_desc = [d for d in descendants if d["recalls"]]
    if descendants:
        signals.append({"code": "DESCENDANT_RECALLS", "severity": "info",
                        "title": f"{len(recalled_desc)} of {len(descendants)} later devices citing this lineage "
                                 f"(≤3 generations) have recalls", "evidence": [], "chain": []})

    # Evidence completeness: keeps a green result from resting on evidence we could not verify.
    trusted_gen1 = [a for a in gen1 if not doubt(a["hops"][0])]
    gen1_unread = [a for a in gen1 if not a.get("lineage_known")]
    if gen1 and not trusted_gen1:
        evidence = "uncertain"
    elif missing or gen1_unread or any(d["gen"] <= 2 for d in doubtful):
        evidence = "partial"
    else:
        evidence = "complete" if ancestors else "none"

    signals.sort(key=lambda s: (-SEVERITY_ORDER[s["severity"]], s.get("gen", 0)))
    worst = max((SEVERITY_ORDER[s["severity"]] for s in signals), default=0)
    n_low = sum(1 for s in signals if s["severity"] == "low")
    if worst == 3:
        verdict = "DESIGN_RECALL_ON_FILE"
    elif worst == 2:
        verdict = "REVIEW_LINEAGE"
    elif not ancestors or evidence == "uncertain":
        verdict = "INSUFFICIENT_LINEAGE"      # we could not check: never show a green result here
    else:
        verdict = "NO_DESIGN_RECALL_SIGNAL"
    if not dev.get("lineage_known"):
        insufficient = (f"The candidate's own predicates could not be read (summary status: "
                        f"{dev.get('summary_status')}), so its ancestry was not checked.")
    elif ancestors and evidence == "uncertain":
        insufficient = ("Every direct predicate link of the candidate rests on uncertain evidence (see the "
                        "uncertain-link signals), so its ancestry was not treated as checked.")
    else:
        insufficient = "No predicate citations were found for the candidate, so its ancestry was not checked."
    clear = ("No design-related recall on the candidate or its direct/grand-predicates in the readable ancestry "
             f"({n_low} lower-severity signal(s) listed). Not a safety finding.")
    if evidence == "partial":
        clear = ("Provisional: " + clear + " Part of the ancestry within two generations is missing or rests on "
                 "uncertain links (see the coverage signals), so a recall there would not show.")
    reasons = {
        "DESIGN_RECALL_ON_FILE": "The candidate itself has a design-related recall on file. FDA's draft guidance "
                                 "recommends predicates without design-related recalls; document how this is addressed.",
        "REVIEW_LINEAGE": "A direct or grand-predicate has a design-related recall (Class I/II or unclassified), the "
                          "direct predicate has a Class I recall, or the candidate has a Class I recall.",
        "INSUFFICIENT_LINEAGE": insufficient,
        "NO_DESIGN_RECALL_SIGNAL": clear,
    }
    return {
        "k": k, "device": dev, "verdict": verdict, "verdict_reason": reasons[verdict],
        "signals": signals, "depth": depth,
        "ancestors": ancestors, "descendants": descendants,
        "coverage": {"ancestors": len(ancestors), "ancestors_lineage_unknown": len(unknown),
                     "candidate_lineage_known": bool(dev.get("lineage_known")),
                     "evidence": evidence, "doubtful_links": len(doubtful),
                     "unresolved_predicate_citations": len(missing),
                     "direct_predicates": len(gen1), "direct_predicates_trusted": len(trusted_gen1)},
        "rules_version": RULES_VERSION,
    }


RULES_VERSION = "forebear-rules-v3"


def doubt(h: dict) -> list[str]:
    """Why a lineage hop's evidence is doubtful ([] if it is not). A person's confirmation clears it."""
    if h.get("review") == "confirmed":
        return []
    why = []
    if h.get("audit") == "unresolved":
        why.append("audit_unresolved")
    if h.get("name_check") == "mismatch" and h.get("audit") not in ("variant", "corrected"):
        why.append("name_mismatch")
    if h.get("panel_check") == "different" and h.get("audit") not in ("variant", "corrected"):
        why.append("different_fda_panel")
    if h.get("kind") not in (None, "predicate") and h.get("ai_label") == "predicate":
        why.append("llm_label_only")
    return why


def _missing_predicates(g: Graph, d: dict) -> list[dict]:
    """Predicate citations from d's summary that are not lineage edges."""
    out = []
    if d.get("unresolved_citations"):
        for u in json.loads(d["unresolved_citations"]):
            if u.get("kind") == "predicate":
                out.append({"type": "unresolved_citation", "src": d["k"], "cited": u["cited"],
                            "reason": u["reason"], "page": u.get("page"), "quote": u.get("quote")})
    for c in g.out_of_lineage_predicates(d["k"]):
        out.append({"type": "unresolved_citation", "src": d["k"], "cited": c["dst"], "page": c.get("page"),
                    "reason": "rejected_by_reviewer" if c.get("review") == "rejected" else f"audit_{c.get('audit')}",
                    "quote": c.get("quote") or c.get("snippet"), "note": c.get("review_note") or c.get("audit_note")})
    return out


def compare(g: Graph, ks: list[str], depth: int = 4) -> list[dict]:
    """One row per candidate predicate - the comparison table FDA's draft guidance suggests
    submitters include when explaining predicate selection."""
    rows = []
    for k in ks:
        a = assess(g, k, depth)
        if a is None:
            rows.append({"k": k, "found": False})
            continue
        d = a["device"]
        rows.append({
            "k": k, "found": True, "name": d.get("name"), "applicant": d.get("applicant"),
            "decision_date": d.get("decision_date"), "verdict": a["verdict"],
            "own_recalls": len(d["recalls"]),
            "own_design_recalls": sum(1 for x in d["recalls"] if x.get("design_related")),
            "flagged_ancestors_gen12": sum(1 for s in a["signals"]
                                           if s["code"] == "ANCESTOR_RECALL" and s["severity"] == "medium"),
            "ancestors": a["coverage"]["ancestors"],
            "lineage_unknown": a["coverage"]["ancestors_lineage_unknown"],
            "top_signal": a["signals"][0]["title"] if a["signals"] else None,
        })
    return rows


def evidence_ids(a: dict) -> set[str]:
    """Identifiers an LLM memo may cite: the candidate, its ancestors, and every recall id in signals."""
    ids = {a["k"]} | {x["k"] for x in a["ancestors"]}
    for s in a["signals"]:
        for e in s["evidence"]:
            if e.get("type") == "recall":
                ids.add(e["id"])
    return ids
