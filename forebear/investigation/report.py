"""The due-diligence report.

Facts, conclusions and recall counts are computed here from the graph, deterministically, whatever the model
said: the verdict and coverage come from `lineage.assess`, every citation hop behind a recall signal is checked
against the cached FDA text by `verify_citation_facts`, and the counts are counted here. The agent contributes
what it investigated (its tool trace), its findings (each independently verified, rejected ones kept with
reasons) and its proposals (pending a person). Machine-generated content is labelled as such throughout.
"""
from __future__ import annotations

import re

from ..graph import Graph
from ..lineage import EVIDENCE_WINDOW, RULES_VERSION, assess
from .tools import RunContext, coverage_gap_facts, verify_citation_facts
from .verify import K_ANY, RECALL_ANY, device_counts, overclaims, verify_all

DISCLAIMER = ("Evidence research, not a medical-device safety determination or regulatory advice. Forebear reports "
              "documented 510(k) predicate lineage and FDA recall records; recalls can be lot-, model- or "
              "software-specific, openFDA's root-cause field is coarse, and FDA recall records can cover product "
              "families. Machine-generated findings below have not been reviewed by a person.")

STANCE_TEXT = {
    "recall_signal_documented": "A recall signal is documented in the predicate lineage (see recall summary and "
                                "evidence paths).",
    "no_signal_in_verdict_window": "No design-related recall signal was found on the candidate, its direct predicates "
                                   "or grand-predicates, and the evidence in that window is complete. This is not a "
                                   "finding that the device or its predicates are safe.",
    "provisional_no_signal": "Provisional: no design-related recall signal was found in the readable ancestry, but "
                             "part of the evidence within two generations is missing or uncertain, so a recall there "
                             "would not show. Do not treat this as a clean result.",
    "abstain_insufficient_evidence": "Abstain: the lineage could not be checked (no readable or trustworthy predicate "
                                     "links), so no conclusion about recall signals is possible.",
}


def stance_of(a: dict) -> str:
    if a["verdict"] in ("DESIGN_RECALL_ON_FILE", "REVIEW_LINEAGE"):
        return "recall_signal_documented"
    if a["verdict"] == "INSUFFICIENT_LINEAGE":
        return "abstain_insufficient_evidence"
    return "no_signal_in_verdict_window" if a["coverage"]["evidence"] == "complete" else "provisional_no_signal"


def _recall_summary(a: dict) -> dict:
    rows, window_ids, all_ids, window_events, design_window = [], set(), set(), set(), set()
    for s in a["signals"]:
        if s.get("code") not in ("DIRECT_RECALL", "ANCESTOR_RECALL"):
            continue
        recs = [e for e in s["evidence"] if e.get("type") == "recall"]
        gen = s.get("gen", 0)
        rows.append({"device": (s.get("chain") or [a["k"]])[-1], "generation": gen, "chain": s.get("chain"),
                     "severity": s["severity"], "title": s["title"], "records": len(recs),
                     "conditional": bool(s.get("conditional")),
                     "events": len({x.get("event") or x["id"] for x in recs}),
                     "design_related_records": sum(1 for x in recs if x.get("design_related")),
                     "class_i_records": sum(1 for x in recs if x.get("classification") == "Class I"),
                     "earliest_initiated": min((x["initiated"] for x in recs if x.get("initiated")), default=None),
                     "recall_ids": [x["id"] for x in recs]})
        for x in recs:
            all_ids.add(x["id"])
            if gen <= EVIDENCE_WINDOW:
                window_ids.add(x["id"])
                window_events.add(x.get("event") or x["id"])
                if x.get("design_related"):
                    design_window.add(x["id"])
    return {"by_device": rows,
            "totals": {"signalled_recall_records": len(all_ids),
                       "records_within_two_generations": len(window_ids),
                       "events_within_two_generations": len(window_events),
                       "design_related_records_within_two_generations": len(design_window)},
            "note": "The graph counts records that FDA's k_numbers associate with each cited device and that "
                    "the severity rules select. Counts include any routes marked conditional. FDA files one "
                    "record per product in an event."}


def _evidence_paths(g: Graph, a: dict, cap: int = 14) -> list[dict]:
    hops, seen = [], set()
    chains = [s["chain"] for s in a["signals"] if s["severity"] in ("high", "medium") and len(s.get("chain") or []) > 1]
    chains += [x["chain"] for x in a["ancestors"] if x["gen"] == 1]
    out = []
    for chain in chains:
        path = []
        for src, dst in zip(chain, chain[1:]):
            if (src, dst) not in seen and len(seen) < cap:
                seen.add((src, dst))
                hops.append(verify_citation_facts(g, src, dst))
            v = next((h for h in hops if h["src"] == src and h["dst"] == dst), None)
            path.append(v or {"src": src, "dst": dst, "status": "not_checked (cap reached)"})
        out.append({"chain": chain, "hops": path})
    uniq, keyset = [], set()
    for p in out:
        key = tuple(p["chain"])
        if key not in keyset:
            keyset.add(key)
            uniq.append(p)
    return uniq


def recall_counts(g: Graph, a: dict, texts: list[str], cap: int = 40) -> dict[str, list[dict]]:
    """For each K-number named in the texts: [counts over all its recalls, counts over its signalled recalls]."""
    signalled: dict[str, list[dict]] = {}
    for s in a["signals"]:
        if s.get("code") in ("DIRECT_RECALL", "ANCESTOR_RECALL"):
            holder = (s.get("chain") or [a["k"]])[-1]
            signalled[holder] = [e for e in s["evidence"] if e.get("type") == "recall"]
    out = {}
    for kk in sorted({x for t in texts for x in K_ANY.findall(t)})[:cap]:
        d = g.device(kk)
        if d is None:
            continue
        out[kk] = [device_counts(d["recalls"]), device_counts(signalled.get(kk, d["recalls"]))]
    return out


def _refs(f: dict, known: set[str]) -> list[str]:
    text = f["claim"] + " " + " ".join(f.get("evidence") or [])
    return sorted((set(K_ANY.findall(text)) | set(RECALL_ANY.findall(text))) & known)


def build(g: Graph, ctx: RunContext, meta: dict) -> dict:
    k, depth = meta["target_k"], meta["depth"]
    a = assess(g, k, depth)
    if a is None:
        raise ValueError(f"{k} is not in the graph")
    gaps = coverage_gap_facts(g, k, depth)
    stance = stance_of(a)
    conclusion_text = STANCE_TEXT[stance]
    if a["verdict"] == "REVIEW_LINEAGE" and any(s.get("conditional") and s["severity"] == "medium"
                                              for s in a["signals"]):
        conclusion_text = "Recall evidence warrants review. Conditional signals depend on unresolved predicate links."
    paths = _evidence_paths(g, a)
    unverified_hops = [h for p in paths for h in p["hops"] if not str(h.get("status", "")).startswith("verified")]

    # evidence status only from assessments the model was shown, since it can make the verifier ACCEPT a claim
    status_by_k = {kk: c["coverage"]["evidence"] for kk, c in ctx.ledger.assessments.items()}
    sub = ctx.submission or {}
    origin = meta.get("finding_origin") or "llm"
    verdicts = {kk: c["verdict"] for kk, c in ctx.ledger.assessments.items()}
    verdicts[k] = a["verdict"]
    counts = recall_counts(g, a, [f["claim"] for f in sub.get("findings") or []] + [sub.get("summary") or ""])
    checked = verify_all(sub.get("findings") or [], ctx.ledger, status_by_k, counts, verdicts)
    known = ctx.ledger.known_ids()
    for f in checked:
        f["origin"] = origin
        f["human_approved"] = False
        f["refs"] = _refs(f, known)
    accepted = [f for f in checked if f["status"] == "verified"]
    rejected = [f for f in checked if f["status"] == "rejected"]
    summary = sub.get("summary") or ""
    summary_issues = []
    if summary:
        probe = verify_all([{"claim": summary, "evidence": []}], ctx.ledger, status_by_k, counts, verdicts)[0]
        summary_issues = [r for r in probe["reasons"] if not r.startswith("cites no evidence")]
    questions = [q for q in sub.get("open_questions") or [] if not overclaims(q)]
    dropped_questions = len(sub.get("open_questions") or []) - len(questions)

    hops_all = [h for p in paths for h in p["hops"]]
    human = sum(1 for h in hops_all if h.get("provenance") == "human_confirmed")
    uncertainties = [{"code": s.get("code"), "title": s["title"]} for s in a["signals"] if s["severity"] == "info"
                     and s.get("code") not in ("DESCENDANT_RECALLS",)]
    if unverified_hops:
        uncertainties.append({"code": "EVIDENCE_PATH_NOT_VERIFIED",
                              "title": f"{len(unverified_hops)} citation hop(s) behind the reported signals could "
                                       f"not be verified against the cached FDA text: " +
                                       ", ".join(f"{h['src']}->{h['dst']} ({h.get('status')})"
                                                 for h in unverified_hops[:6])})
    if ctx.ledger.injection_flags:
        uncertainties.append({"code": "INSTRUCTION_LIKE_TEXT_IN_SOURCES",
                              "title": f"{len(ctx.ledger.injection_flags)} retrieved FDA text field(s) contained "
                                       f"instruction-like text; it was treated as data and not followed."})

    return {
        "schema": "forebear-investigation-report/1",
        "investigation_id": meta["id"],
        "request": meta["request"],
        "disclaimer": DISCLAIMER,
        "status": meta["status"],
        "mode": meta["mode"],
        "mode_note": meta.get("mode_note"),
        "target": {"k": k, "name": a["device"].get("name"), "applicant": a["device"].get("applicant"),
                   "decision_date": a["device"].get("decision_date"),
                   "summary_url": a["device"].get("summary_url"), "summary_sha256": a["device"].get("summary_sha256")},
        "conclusion": {"stance": stance, "text": conclusion_text, "verdict": a["verdict"],
                       "verdict_reason": a["verdict_reason"], "evidence": a["coverage"]["evidence"],
                       "evidence_scope": a["coverage"]["evidence_scope"], "generations_traversed": depth,
                       "source": "deterministic (forebear rules), not the model"},
        "recall_summary": _recall_summary(a),
        "evidence_paths": paths,
        "uncertainties": uncertainties,
        "missing_evidence": gaps,
        "agent": {"summary": None if summary_issues else summary,
                  "summary_withheld": summary if summary_issues else None, "summary_issues": summary_issues,
                  "findings_verified": accepted, "findings_rejected": rejected,
                  "open_questions": questions, "open_questions_dropped": dropped_questions,
                  "note": ("Machine-generated by the model named below; each finding was checked against this run's "
                           "tool results. Rejected findings are shown with the reason and are not part of the "
                           "conclusion.") if ctx.submission else
                          "No agent findings: " + (meta.get("mode_note") or "the agent did not submit a report.")},
        "proposals": ctx.proposals,
        "human_oversight": {
            "lineage_writes_by_agent": 0,
            "statement": "The agent cannot confirm, reject or edit citation links and did not; proposals await a "
                         "person. Review status of each evidence hop is shown as its provenance.",
            "evidence_hops_human_confirmed": human, "evidence_hops_machine_only": len(hops_all) - human},
        "reproducibility": {
            "rules_version": RULES_VERSION, "agent_version": meta["agent_version"],
            "prompt_sha256": meta.get("prompt_sha256"), "models_configured": meta.get("models"),
            "model_used": meta.get("model_used"), "llm_errors": meta.get("llm_errors"),
            "depth": depth, "budget": meta.get("budget"), "usage": meta.get("usage"),
            "started_at": meta.get("started_at"), "finished_at": meta.get("finished_at"),
            "graph": meta.get("graph_stats"),
            "tool_calls": [{"seq": t["seq"], "tool": t["tool"],
                            "args": (t["args"] if t["tool"] != "submit_report" else
                                     {"findings": len((t["args"] or {}).get("findings") or []),
                                      "note": "content verified above; raw text in the ToolCall node"}),
                            "ok": t["ok"], "shown_sha256": t.get("shown_sha256"),
                            "shown_truncated": bool(t.get("omitted")),
                            "origin": t["origin"], "result_sha256": t.get("result_sha256")}
                           for t in meta.get("trace", [])],
            "how_to_rerun": f"POST /api/investigations {{\"request\": ..., \"k\": \"{k}\", \"depth\": {depth}}} "
                            f"or scripts/investigate.py --k {k} --depth {depth}"},
    }


def _md_escape(s: str | None) -> str:
    return re.sub(r"([|])", r"\\\1", str(s or ""))


def markdown(r: dict) -> str:
    t, c = r["target"], r["conclusion"]
    L = [f"# Due-diligence investigation: {t['k']} {t.get('name') or ''}".rstrip(), "",
         f"> {r['disclaimer']}", "",
         f"- Investigation: `{r['investigation_id']}`  status: **{r['status']}**  mode: **{r['mode']}**",
         f"- Request: {r['request']}"]
    if r.get("mode_note"):
        L.append(f"- Mode note: {r['mode_note']}")
    L += [f"- Target: {t['k']}, {t.get('applicant')}, decided {t.get('decision_date')}; summary {t.get('summary_url')}",
          "", "## Conclusion (deterministic)", "",
          f"**{c['text']}**", "",
          f"Verdict `{c['verdict']}`, evidence `{c['evidence']}` ({c['evidence_scope']}; {c['generations_traversed']} "
          f"generations traversed). {c['verdict_reason']}", "", "## Recall summary (counted from the graph)", ""]
    tot = r["recall_summary"]["totals"]
    L.append(f"Within two generations: {tot['records_within_two_generations']} recall record(s) in "
             f"{tot['events_within_two_generations']} event(s), {tot['design_related_records_within_two_generations']}"
             f" design-related. All signalled records: {tot['signalled_recall_records']}.")
    if any(row.get("conditional") for row in r["recall_summary"]["by_device"]):
        L.extend(["", "Totals include conditional paths. FDA associates each recall with its listed device."])
    if r["recall_summary"]["by_device"]:
        L += ["", "| Device | Gen | Severity | Records | Events | Design | Class I | Recall ids |", "|---|---|---|---|---|---|---|---|"]
        for x in r["recall_summary"]["by_device"]:
            ids = ", ".join(x["recall_ids"][:6]) + (" ..." if len(x["recall_ids"]) > 6 else "")
            severity = x["severity"] + (" (conditional)" if x.get("conditional") else "")
            L.append(f"| {x['device']} | {x['generation']} | {severity} | {x['records']} | {x['events']} | "
                     f"{x['design_related_records']} | {x['class_i_records']} | {ids} |")
    L += ["", "## Evidence paths (each hop checked against the cached FDA summary text)", ""]
    for p in r["evidence_paths"]:
        L.append(f"- {' -> '.join(p['chain'])}")
        for h in p["hops"]:
            L.append(f"  - {h['src']} -> {h['dst']}: **{h.get('status')}**, page {h.get('page')}, "
                     f"{h.get('provenance', '')}, {h.get('source_url') or ''} (sha256 {str(h.get('source_sha256'))[:12]}...)")
            if h.get("untrusted_audit_note"):
                L.append(f"    - Source audit: {h['untrusted_audit_note']}")
    L += ["", "## Uncertainties", ""] + ([f"- `{u['code']}` {u['title']}" for u in r["uncertainties"]] or ["- none reported"])
    m = r["missing_evidence"] or {}
    L += ["", "## Missing evidence", "",
          f"- Unread ancestors: {m.get('unread_ancestors_total', 0)} "
          + ", ".join(f"{u['k']} (gen {u['gen']}, {u.get('summary_status')})" for u in m.get("unread_ancestors", [])[:8]),
          f"- Doubtful links: {m.get('doubtful_links_total', 0)} "
          + ", ".join(f"{d['src']}->{d['dst']} {d['doubt']}" for d in m.get("doubtful_links", [])[:8]),
          f"- Unresolved predicate citations: {m.get('unresolved_predicate_citations_total', 0)} "
          + ", ".join(f"{u['src']} cites {u['cited']} ({u.get('reason')})" for u in m.get("unresolved_predicate_citations", [])[:8]),
          f"- Recalls with unknown cause or class (gen <= 2): {len(m.get('recalls_with_unknown_cause_or_class', []))}",
          f"- Gaps beyond two generations: {m.get('deeper_gaps')}"]
    ag = r["agent"]
    L += ["", "## Agent findings (machine-generated, independently verified)", "", ag["note"], ""]
    if ag.get("summary"):
        L += [f"Agent summary (verified): {ag['summary']}", ""]
    elif ag.get("summary_issues"):
        L += [f"Agent summary withheld: it failed verification ({'; '.join(ag['summary_issues'])}).", ""]
    for f in ag["findings_verified"]:
        note = f" ({f['certainty_note']})" if f.get("certainty_note") else ""
        L.append(f"- [verified] ({f.get('kind')}, {f.get('certainty') or 'n/a'}{note}) {f['claim']}  "
                 f"evidence: {', '.join(f['evidence'])}")
    for f in ag["findings_rejected"]:
        L.append(f"- [REJECTED, shown for transparency] {f['claim']}  reasons: {'; '.join(f['reasons'])}")
    if ag.get("open_questions"):
        L += ["", "Open questions (machine-generated):"] + [f"- {q}" for q in ag["open_questions"]]
    if ag.get("open_questions_dropped"):
        L.append(f"({ag['open_questions_dropped']} open question(s) dropped: they made a determination.)")
    L += ["", "## Proposals awaiting a person", ""]
    L += [f"- `{p.get('id', '')}` {p['kind']} {p.get('k') or (p.get('src', '') + '->' + p.get('dst', ''))} "
          f"{p.get('suggestion') or ''}: {p.get('reason')} ({p['status']})" for p in r["proposals"]] or ["- none"]
    h, rep = r["human_oversight"], r["reproducibility"]
    L += ["", "## Human oversight", "", f"- {h['statement']}",
          f"- Evidence hops confirmed by a person: {h['evidence_hops_human_confirmed']}; machine-only: "
          f"{h['evidence_hops_machine_only']}",
          "", "## Reproducibility", "",
          f"- Rules `{rep['rules_version']}`, agent `{rep['agent_version']}`, prompt sha256 `{str(rep.get('prompt_sha256'))[:16]}`",
          f"- Model used: {rep.get('model_used') or 'none'}; configured: {rep.get('models_configured')}",
          f"- Usage: {rep.get('usage')}; budget: {rep.get('budget')}",
          f"- {rep['started_at']} to {rep['finished_at']}", "", "| # | Tool | Arguments | OK | Origin | Shown to model |", "|---|---|---|---|---|---|"]
    for tc in rep["tool_calls"]:
        seen = "shortened (omitted items are not evidence)" if tc.get("shown_truncated") else "complete"
        L.append(f"| {tc['seq']} | {tc['tool']} | `{_md_escape(str(tc['args'])[:90])}` | {tc['ok']} | {tc['origin']} "
                 f"| {seen} |")
    L.append(f"\nRe-run: {rep['how_to_rerun']}")
    return "\n".join(L) + "\n"
