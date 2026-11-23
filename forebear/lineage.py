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
            "url": x.get("url"), "status": x.get("status"),
            "link_name_check": x.get("link_name_check"), "linked_before_clearance": x.get("linked_before_clearance"),
            "attribution": recall_attribution(x)}


ATTRIBUTION_CODES = ("name_token_match", "name_token_absent", "name_not_checkable")


def recall_attribution(x: dict) -> str:
    """What the recall-text name heuristic says about a recall record linked to a 510(k). The link itself is always
    FDA's: openFDA lists the clearance's K-number on the recall record. That is an association; nothing here verifies
    which model was recalled.

      name_token_match    a distinctive word of the device's FDA name appears in the recall's product/reason text
                          (evidence.name_check: exact, spacing- or OCR-normalised, or within a small edit distance).
                          One fuzzy token is a heuristic signal, not proof that the recall names this exact model.
      name_token_absent   no distinctive word of the FDA name was found; the recalled model may differ, or the text
                          may name it differently
      name_not_checkable  the FDA name has no distinctive word to look for, or no check was recorded

    Timing is deliberately not part of this code: `linked_before_clearance` (the recall began before this clearance
    was decided) is reported on its own and does not by itself establish whether this model was affected."""
    nc = x.get("link_name_check")
    if nc == "match":
        return "name_token_match"
    if nc == "mismatch":
        return "name_token_absent"
    return "name_not_checkable"


def _count(recs: list[dict]) -> str:
    """'N recall event(s) (M product record(s))': FDA files one record per product in an event."""
    events = {x.get("event") or x["id"] for x in recs}
    return f"{len(events)} recall event(s) ({len(recs)} product record(s))"


def assess(g: Graph, k: str, depth: int = 4) -> dict | None:
    depth = max(1, min(int(depth), 8))           # the range the lineage query actually traverses
    dev = g.device(k)
    if dev is None:
        return None
    ancestors = g.ancestors(k, depth)
    descendants = g.descendants(k, 3)
    signals: list[dict] = []

    pc = dev.get("product") or {}

    for a in ancestors:
        for h in a["hops"]:
            h["trust"] = trust(h)

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
        conditional = any("audit_unresolved" in doubt(hop) for hop in a["hops"])
        holder = f"{'Cited device' if conditional else gen_word} {a['k']}"
        signals.append({
            "code": "ANCESTOR_RECALL", "severity": sev, "conditional": conditional,
            "title": f"{holder} ({a.get('name') or 'unnamed'}) has {_count(recs)}"
                     f"{f', {n_design} record(s) design-related' if n_design else ''}"
                     + (". Its connection to this lineage is conditional on an unresolved citation."
                        if conditional else ""),
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
    # Every lineage edge leaving the candidate or an ancestor within the requested depth is checked, on any
    # route: its generation is its source's generation + 1 (the candidate is generation 0).
    gen_of = {k: 0} | {a["k"]: a["gen"] for a in ancestors}
    flagged, doubtful = [], []
    sources = [x for x, n in gen_of.items() if n < depth]
    for h in g.lineage_edges_from(sources):
        why = doubt(h)
        if why:
            doubtful.append({"type": "citation", "doubt": why, "gen": gen_of[h["src"]] + 1, "trust": "uncertain", **h})
            if "name_mismatch" in why:
                flagged.append({"type": "citation", **h})
    if flagged:
        signals.append({"code": "NAME_MISMATCH_IN_LINEAGE", "severity": "info",
                        "title": f"This ancestry uses {len(flagged)} link(s) where the cited device's FDA name does not "
                                 f"appear in the summary text (possible K-number typo). Verify them before relying on "
                                 f"the result.", "evidence": flagged, "chain": []})
    other = [d for d in doubtful if d["doubt"] != ["name_mismatch"]]
    if other:
        unresolved = ", ".join(f"{d['src']} → {d['dst']}" for d in other if "audit_unresolved" in d["doubt"])
        title = f"{len(other)} link(s) in this ancestry rest on uncertain evidence."
        if unresolved:
            title += f" Unresolved predicate evidence for {unresolved}. Recall signals through these links are conditional."
        signals.append({"code": "UNCERTAIN_LINK_IN_LINEAGE", "severity": "info",
                        "title": title, "evidence": other, "chain": []})

    # V: advisory links. An LLM triage label or an automated-client confirmation says a citation is a predicate,
    # but no person has decided. The cited device and its recalls are shown with full provenance, never traversed:
    # they cannot raise or lower the verdict. Inside the verdict window they make the evidence partial, because a
    # predicate (and its recalls) may be missing from the trusted lineage until someone decides.
    advisory = [{"type": "advisory_citation", "trust": "advisory", "basis": advisory_basis(h),
                 "gen": gen_of[h["src"]] + 1, **h} for h in g.advisory_edges_from(sources)]
    window_advisory = [x for x in advisory if x["gen"] <= EVIDENCE_WINDOW]
    if advisory:
        rec_note = "; ".join(f"{x['dst']} has {_count(x['recalls'])}"
                             + (f", {sum(1 for r in x['recalls'] if r.get('design_related'))} design-related"
                                if any(r.get("design_related") for r in x["recalls"]) else "")
                             for x in advisory if x["recalls"])
        signals.append({"code": "ADVISORY_LINK_PENDING_REVIEW", "severity": "info",
                        "title": f"{len(advisory)} predicate link(s) suggested only by an automated source (LLM triage or "
                                 f"the MCP client) await a person's decision and are not used for the verdict"
                                 + (f". Recalls on the suggested devices: {rec_note}" if rec_note else ""),
                        "evidence": advisory + [_recall_ev(r) | {"via_advisory": f"{x['src']}->{x['dst']}"}
                                                for x in advisory for r in x["recalls"]],
                        "chain": []})

    # X: citations a re-ingest retired because the refreshed FDA summary no longer supports them. Kept with their
    # reviews and provenance for the record; out of lineage. A retired edge a person had confirmed is a gap: the
    # person's decision was made on text the current summary no longer contains.
    retired = [r["hop"] | {"type": "retired_citation", "trust": "retired", "retired_at": r["retired_at"],
                           "retired_reason": r["retired_reason"], "retired_by_sha256": r["retired_by_sha256"],
                           "gen": gen_of[r["hop"]["src"]] + 1}
               for r in g.retired_citations_from(sources)]
    retired_confirmed = [x for x in retired if x["gen"] <= EVIDENCE_WINDOW and x.get("review") == "confirmed"
                         and x.get("reviewer") not in MACHINE_REVIEWERS]
    if retired:
        signals.append({"code": "CITATION_RETIRED_BY_REINGEST", "severity": "info",
                        "title": f"{len(retired)} citation(s) are no longer supported by the refreshed FDA summary of the "
                                 f"citing device and were retired from the lineage"
                                 + (f"; {len(retired_confirmed)} had been confirmed by a person and need re-review"
                                    if retired_confirmed else ""),
                        "evidence": retired, "chain": []})

    # C: predicate citations in the own summary of the candidate or of any ancestor whose predicates fall inside
    # the requested depth, that did not become lineage edges: K-number not in openFDA, cleared later, or removed
    # by the audit or a reviewer. `gen` is the generation the missing predicate would have had.
    gen1 = [a for a in ancestors if a["gen"] == 1]
    all_missing = [m | {"gen": 1} for m in _missing_predicates(g, dev)] + \
                  [m | {"gen": a["gen"] + 1} for a in ancestors if a["gen"] < depth for m in _missing_predicates(g, a)]
    missing = [m for m in all_missing if m["gen"] <= EVIDENCE_WINDOW]
    deeper_missing = [m for m in all_missing if m["gen"] > EVIDENCE_WINDOW]
    if all_missing:
        signals.append({"code": "PREDICATE_CITATION_UNRESOLVED", "severity": "info",
                        "title": f"{len(all_missing)} predicate citation(s) in the summaries of {k} or its ancestors "
                                 f"could not be resolved to a device in this graph, so part of the ancestry is missing"
                                 f" ({len(missing)} within two generations)",
                        "evidence": all_missing[:20], "chain": []})

    # G: gaps deeper than the evidence window but inside the requested depth. Recalls there can only yield
    # low-severity signals, so they cannot change the verdict, but the lower-severity list may be incomplete.
    deeper_doubtful = [d for d in doubtful if d["gen"] > EVIDENCE_WINDOW]
    deeper_unread = [a for a in ancestors if EVIDENCE_WINDOW <= a["gen"] < depth and not a.get("lineage_known")]
    deeper = {"missing_predicate_citations": len(deeper_missing), "doubtful_links": len(deeper_doubtful),
              "unread_ancestors": len(deeper_unread)}
    if any(deeper.values()):
        signals.append({"code": "DEEPER_ANCESTRY_GAPS", "severity": "info",
                        "title": f"Beyond two generations (up to the requested {depth}): {len(deeper_missing)} unresolved "
                                 f"predicate citation(s), {len(deeper_doubtful)} doubtful link(s), {len(deeper_unread)} "
                                 f"ancestor(s) whose own summaries were not read. Recalls there would only be "
                                 f"lower-severity signals, and some may be missing.",
                        "evidence": deeper_missing[:10] + deeper_doubtful[:10], "chain": []})

    # R: recalls filed under the candidate's product code that name no 510(k): no lineage query sees them
    if pc.get("unattributed_design_recalls_n"):
        un = [u for u in json.loads(pc.get("unattributed_recalls") or "[]") if u.get("design_related")]
        signals.append({"code": "UNATTRIBUTED_RECALLS_IN_PRODUCT_CODE", "severity": "info",
                        "title": f"{len(un)} design-related recall record(s) under product code {pc.get('code')} name no "
                                 f"510(k) number, so they cannot be attributed to this or any device's lineage",
                        "evidence": [{"type": "recall", **u} for u in un[:12]], "chain": []})

    # F: how the family downstream has fared (context, not a verdict input)
    recalled_desc = [d for d in descendants if d["recalls"]]
    if descendants:
        signals.append({"code": "DESCENDANT_RECALLS", "severity": "info",
                        "title": f"{len(recalled_desc)} of {len(descendants)} later devices citing this lineage "
                                 f"(≤3 generations) have recalls", "evidence": [], "chain": []})

    # U2: recalls whose cause or class is unknown cannot be ruled out as design-related / Class I
    unknown_recalls = [(0, x) for x in own if recall_unknown(x, 0)] + \
              [(a["gen"], x) for a in ancestors if a["gen"] <= 2 for x in a["recalls"] if recall_unknown(x, a["gen"])]
    if unknown_recalls:
        signals.append({"code": "RECALL_CAUSE_OR_CLASS_UNKNOWN", "severity": "info",
                        "title": f"{len(unknown_recalls)} recall record(s) on the candidate or its direct/grand-predicates have no "
                                 f"stated root cause or no FDA classification, so they cannot be ruled out as design-related "
                                 f"or Class I", "evidence": [_recall_ev(x) | {"gen": g} for g, x in unknown_recalls[:12]],
                        "chain": []})

    # Evidence completeness: keeps a green result from resting on evidence we could not verify.
    trusted_gen1 = [a for a in gen1 if not doubt(a["hops"][0])]
    gen1_unread = [a for a in gen1 if not a.get("lineage_known")]
    # `evidence` describes the verdict window only (the candidate and two predicate generations, the reach of
    # every severity rule that can change a verdict); gaps beyond it are counted in coverage.deeper_gaps.
    shallow = depth < EVIDENCE_WINDOW         # grand-predicates were not traversed at all
    window_doubtful = [d for d in doubtful if d["gen"] <= EVIDENCE_WINDOW]
    # Why the verdict window is not complete, one code per gap, so every view can say so without re-deriving it.
    evidence_reasons = [code for code, hit in (
        ("direct_predicate_links_all_uncertain", bool(gen1 and not trusted_gen1)),
        ("unresolved_predicate_citations", bool(missing)),
        ("direct_predicate_summaries_unread", bool(gen1_unread)),
        ("doubtful_links_in_window", bool(window_doubtful)),
        ("recall_cause_or_class_unknown", bool(unknown_recalls)),
        ("unattributed_recalls_in_product_code", bool(pc.get("unattributed_design_recalls_n"))),
        ("shallow_traversal", bool(shallow and ancestors)),
        ("advisory_links_pending_review", bool(window_advisory)),
        ("human_confirmed_citation_retired", bool(retired_confirmed)),
    ) if hit]
    if gen1 and not trusted_gen1:
        evidence = "uncertain"
    elif missing or gen1_unread or any(d["gen"] <= EVIDENCE_WINDOW for d in doubtful) or unknown_recalls or \
            pc.get("unattributed_design_recalls_n") or (shallow and ancestors) or window_advisory or retired_confirmed:
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
    elif not ancestors and any(x["gen"] == 1 for x in advisory):
        insufficient = ("The candidate's only predicate links were suggested by an automated source (LLM triage or the "
                        "MCP client) and await a person's decision, so its ancestry was not treated as checked.")
    else:
        insufficient = "No predicate citations were found for the candidate, so its ancestry was not checked."
    clear = ("No design-related recall on the candidate or its direct/grand-predicates in the readable ancestry "
             f"({n_low} lower-severity signal(s) listed). Not a safety finding.")
    if evidence == "partial" and shallow:
        clear = ("Provisional: " + clear.replace("its direct/grand-predicates", "its direct predicates") +
                 f" Only {depth} predicate generation was traversed, so grand-predicate recalls were not checked; "
                 f"request at least {EVIDENCE_WINDOW} generations.")
    elif evidence == "partial":
        clear = ("Provisional: " + clear + " Part of the ancestry within two generations is missing or rests on "
                 "uncertain links (see the coverage signals), so a recall there would not show.")
        if window_advisory:
            clear += (" Predicate links suggested only by an automated source are not counted until a person "
                      "confirms them (see ADVISORY_LINK_PENDING_REVIEW).")
    if any(deeper.values()):
        clear += (" Beyond two generations the ancestry has gaps (see DEEPER_ANCESTRY_GAPS), so the lower-severity "
                  "list may be incomplete.")
    reasons = {
        "DESIGN_RECALL_ON_FILE": "The candidate itself has a design-related recall on file. FDA's draft guidance "
                                 "recommends predicates without design-related recalls; document how this is addressed.",
        "REVIEW_LINEAGE": "A direct or grand-predicate has a design-related recall (Class I/II or unclassified), the "
                          "direct predicate has a Class I recall, or the candidate has a Class I recall.",
        "INSUFFICIENT_LINEAGE": insufficient,
        "NO_DESIGN_RECALL_SIGNAL": clear,
    }
    if any(s.get("conditional") and s["severity"] == "medium" for s in signals):
        reasons["REVIEW_LINEAGE"] = ("FDA recall records warrant review. Signals marked conditional depend on "
                                     "unresolved predicate evidence.")
    return {
        "k": k, "device": dev, "verdict": verdict, "verdict_reason": reasons[verdict],
        "signals": signals, "depth": depth,
        "ancestors": ancestors, "descendants": descendants,
        "coverage": {"ancestors": len(ancestors), "ancestors_lineage_unknown": len(unknown),
                     "candidate_lineage_known": bool(dev.get("lineage_known")),
                     "evidence": evidence, "evidence_reasons": evidence_reasons,
                     "doubtful_links": len(doubtful),
                     "advisory_links": len(advisory), "advisory_links_in_window": len(window_advisory),
                     "retired_citations": len(retired),
                     "unresolved_predicate_citations": len(missing),
                     "direct_predicates": len(gen1), "direct_predicates_trusted": len(trusted_gen1),
                     "evidence_scope": "candidate, direct predicates and grand-predicates (verdict window)",
                     "generations_traversed": depth, "deeper_gaps": deeper},
        "rules_version": RULES_VERSION,
    }


RULES_VERSION = "forebear-rules-v5"
EVIDENCE_WINDOW = 2                       # generations within which a recall can raise a verdict above "no signal"
MACHINE_REVIEWERS = ("mcp-client",)       # reviews recorded through an automated client, not a person


def doubt(h: dict) -> list[str]:
    """Why a lineage hop's evidence is doubtful ([] if it is not). A person's confirmation clears it; a
    confirmation sent through the MCP tool (reviewer "mcp-client", possibly an AI agent) does not, and a rejection
    sent through it leaves the edge in the lineage, flagged, until a person decides."""
    if current_human_review(h) and h.get("review") == "confirmed":
        return []
    why = []
    if human_review(h) and not current_human_review(h):
        why.append("review_outdated")         # a person reviewed an earlier version of the evidence
    if h.get("audit") == "unresolved":
        why.append("audit_unresolved")
    if h.get("audit") == "corrected":         # the K-number was supplied by the audit, not printed in the PDF
        why.append("audit_correction")
    if h.get("name_check") == "mismatch" and h.get("audit") not in ("variant", "corrected"):
        why.append("name_mismatch")
    if h.get("panel_check") == "different" and h.get("audit") not in ("variant", "corrected"):
        why.append("different_fda_panel")
    if h.get("kind") not in (None, "predicate") and h.get("ai_label") == "predicate":
        why.append("llm_label_only")
    if h.get("kind") not in (None, "predicate") and h.get("review") == "confirmed" \
            and h.get("reviewer") in MACHINE_REVIEWERS:
        why.append("client_confirmation_only")
    if h.get("review") == "rejected" and h.get("reviewer") in MACHINE_REVIEWERS:
        why.append("client_rejection_pending")    # an automated client disputes it; a person has not decided
    return why


def human_review(h: dict) -> bool:
    """A review recorded by a person (any version of the evidence)."""
    return bool(h.get("review")) and h.get("reviewer") not in MACHINE_REVIEWERS


def current_human_review(h: dict) -> bool:
    """Mirror of graph.CURRENT_HUMAN_REVIEW: a person's review made on the evidence the edge carries now."""
    return human_review(h) and (h.get("reviewed_source_sha256") or "") == (h.get("source_sha256") or "")


def trust(h: dict) -> str:
    """How far a trusted lineage hop can be relied on: 'human_verified' (a person confirmed it), 'extracted' (read
    from the FDA summary, nothing doubtful) or 'uncertain' (doubt(h) is not empty). Advisory and retired edges are
    labelled where they are listed; they are never lineage hops."""
    if h.get("review") == "confirmed" and current_human_review(h):
        return "human_verified"
    return "uncertain" if doubt(h) else "extracted"


def citation_state(h: dict | None) -> dict | None:
    """One citation edge (graph.citation_edge) labelled as the lineage rules treat it now: 'retired', 'advisory', a
    trusted hop's trust() ('human_verified', 'extracted' or 'uncertain'), or None when it is out of lineage (rejected
    by a person or removed by the audit)."""
    if h is None:
        return None
    label = ("retired" if h.get("retired_at") else "advisory" if h.get("advisory")
             else trust(h) if h.get("in_lineage") else None)
    return h | {"trust": label}


def advisory_basis(h: dict) -> list[str]:
    """Which automated sources call an untrusted citation a predicate."""
    out = []
    if h.get("ai_label") == "predicate":
        out.append("llm_label")
    if h.get("review") == "confirmed" and h.get("reviewer") in MACHINE_REVIEWERS:
        out.append("client_confirmation")
    if h.get("review") == "confirmed" and human_review(h) and not current_human_review(h):
        out.append("outdated_human_confirmation")
    return out


UNKNOWN_CAUSES = ("", "other", "under investigation by firm", "unknown/undetermined by firm")


def recall_unknown(x: dict, gen: int) -> bool:
    """A recall that the severity rules cannot classify: not known to be design-related and either its root
    cause is missing/unspecific, or (on the candidate or a direct predicate, where Class I alone matters)
    FDA's classification is missing."""
    if x.get("design_related"):
        return False
    cause = (x.get("root_cause") or "").strip().lower()
    return cause in UNKNOWN_CAUSES or (gen <= 1 and not x.get("classification"))


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


def provisional(a: dict) -> bool:
    """A "no signal" verdict that rests on an incomplete verdict window: it says nothing about the missing part."""
    return a["verdict"] == "NO_DESIGN_RECALL_SIGNAL" and a["coverage"]["evidence"] != "complete"


def compare(g: Graph, ks: list[str], depth: int = 4) -> list[dict]:
    """One row per candidate predicate - the comparison table FDA's draft guidance suggests
    submitters include when explaining predicate selection. Each row keeps the verdict's evidence coverage,
    the reasons it is incomplete and the verdict reason, so two equal verdicts on unequal evidence never
    look the same."""
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
            "verdict_reason": a["verdict_reason"], "provisional": provisional(a),
            "evidence": a["coverage"]["evidence"], "evidence_reasons": a["coverage"]["evidence_reasons"],
            "deeper_gaps": a["coverage"]["deeper_gaps"],
            # medium signals that all hang on an unresolved citation: the REVIEW verdict is conditional
            "conditional": a["verdict"] == "REVIEW_LINEAGE" and not any(
                s["severity"] == "medium" and not s.get("conditional") for s in a["signals"]),
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


def date_relation(clearance: str | None, recall_start: str | None) -> str:
    """'after' | 'before' | 'same_day' | 'unknown': when a clearance was decided relative to a recall start.
    Compared by calendar day (ISO YYYY-MM-DD strings sort chronologically). A missing date is 'unknown', never
    'before'; a same-day pair cannot be ordered and is never counted as 'after'."""
    c, r = (str(clearance)[:10] if clearance else ""), (str(recall_start)[:10] if recall_start else "")
    if not c or not r or c in ("None", "null") or r in ("None", "null"):
        return "unknown"
    return "after" if c > r else "before" if c < r else "same_day"


def _earliest(dates) -> str | None:
    ds = [str(d)[:10] for d in dates if d]
    return min(ds) if ds else None


def classify_reach(recalled: list[dict], desc: list[dict]) -> dict:
    """Recall reach from raw query rows (Graph.recall_event_reach).

    Each descendant reaches one or more recalled holders. A holder is supported if at least one path to it has no
    unresolved audit link, conditional if every path does. Timing is taken from the supported holders only (the
    earliest recall start among them); conditional holders get their own timing, reported separately, so a date
    reached only through an unresolved citation can never decide the supported classification. `evidence` is
    'supported' when any holder is supported, else 'conditional'."""
    start = {d["k"]: (str(d["initiated"])[:10] if d.get("initiated") else None) for d in recalled}
    out = []
    for r in desc:
        via = sorted(r["via"])
        supported_via = sorted(v for v in r.get("supported_via") or [] if v)
        conditional_via = sorted(set(via) - set(supported_via))
        sup_start = _earliest(start.get(v) for v in supported_via)
        cond_start = _earliest(start.get(v) for v in conditional_via)
        evidence = "supported" if supported_via else "conditional"
        basis = sup_start if supported_via else cond_start
        timing = date_relation(r.get("decision_date"), basis)
        out.append({
            "k": r["k"], "name": r["name"], "applicant": r.get("applicant"),
            "decision_date": str(r["decision_date"])[:10] if r.get("decision_date") else None,
            "gen": r["gen"], "supported_gen": r.get("supported_gen"),
            "via": via, "supported_via": supported_via, "conditional_via": conditional_via, "evidence": evidence,
            "recall_started": basis, "timing": timing, "after_recall": timing == "after",
            # mixed-confidence routes: what the conditional holders alone would say (None if there are none)
            "conditional_recall_started": cond_start if supported_via and conditional_via else None,
            "conditional_timing": (date_relation(r.get("decision_date"), cond_start)
                                   if supported_via and conditional_via else None),
        })
    counts = {"after_supported": 0, "after_conditional": 0, "before": 0, "same_day": 0, "unknown": 0}
    for d in out:
        if d["timing"] == "after":
            counts["after_supported" if d["evidence"] == "supported" else "after_conditional"] += 1
        else:
            counts[d["timing"]] += 1
    counts["conditional"] = sum(1 for d in out if d["evidence"] == "conditional")
    counts["mixed"] = sum(1 for d in out if d["conditional_via"] and d["supported_via"])
    recalled_out = []
    for d in recalled:
        x = {"link_name_check": "match" if "match" in (d.get("name_checks") or []) else
             "mismatch" if "mismatch" in (d.get("name_checks") or []) else None,
             "linked_before_clearance": bool(d.get("before_clearance"))}
        # the device can be on several records of the event: 'name_token_match' if the heuristic matched on any of
        # them, and every record's own result is kept in name_checks
        recalled_out.append({"k": d["k"], "name": d["name"], "decision_date": d.get("decision_date"),
                             "initiated": start[d["k"]], "records": d.get("records"),
                             "name_checks": sorted(c for c in d.get("name_checks") or [] if c),
                             "linked_before_clearance": x["linked_before_clearance"],
                             "attribution": recall_attribution(x)})
    return {"initiated": _earliest(start.values()), "recalled": recalled_out, "descendants": out, "counts": counts}


def recall_reach(g: Graph, event: str, depth: int = 3) -> dict:
    raw = g.recall_event_reach(event, depth)
    if not raw["recalled"]:
        return {"event": event, "initiated": None, "recalled": [], "descendants": [],
                "counts": {"after_supported": 0, "after_conditional": 0, "before": 0, "same_day": 0, "unknown": 0,
                           "conditional": 0, "mixed": 0}}
    return {"event": event, **classify_reach(raw["recalled"], raw["descendants"])}
