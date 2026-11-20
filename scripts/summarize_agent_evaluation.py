"""Export auditable structured observations from a Phase 3 run.

Model prose, uncertainty and investigative value require source review. This script
preserves the prose and scores only the predefined structured recall/page checks.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from evaluate_agent import EVAL, GRAPH, ROOT, sha256, write_json
from forebear.config import use_raw_cache
from forebear.graph import open_graph
from forebear.investigation import report as report_builder
from forebear.investigation.tools import RunContext, absorb_visible, run_tool


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_sources(frozen: dict) -> None:
    """Check frozen labels against raw FDA cache fields without opening Relate or the verifier."""
    cases = frozen["cases"]
    targets = {case["k"] for case in cases}
    assert len(targets) == len(cases) and targets.isdisjoint(frozen["demos"]), "case/demo overlap"
    cache: dict[str, dict] = {}

    def source(path: str) -> dict:
        if path not in cache:
            cache[path] = read_json(ROOT / path)
        return cache[path]

    for case in cases:
        for clearance in case["clearance_records"]:
            assert any(
                row["k_number"] == clearance["k"] and row["device_name"] == clearance["device_name"]
                for row in source(clearance["cache"])["results"]
            ), clearance
        for anchor in case["citations"]:
            document = source(anchor["text_cache"])
            assert document.get("sha256", document.get("source_sha256")) == anchor["pdf_sha256"], anchor
            page = document["pages"][anchor["page"] - 1]
            assert anchor["printed"] in "".join(page.upper().split()), anchor
        for witness in case["critical"]:
            for record in witness["records"]:
                assert any(
                    row["product_res_number"] == record["id"]
                    and str(row["res_event_number"]) == witness["event"]
                    and witness["holder"] in (row.get("k_numbers") or [])
                    and row["root_cause_description"] == record["cause"]
                    for row in source(record["recall_cache"])["results"]
                ), record
                assert any(
                    row["recall_number"] == record["id"] and str(row["event_id"]) == witness["event"]
                    and row["classification"] == "Class I" == record["classification"]
                    for row in source(record["enforcement_cache"])["results"]
                ), record


def critical_detection(case: dict, report: dict) -> list[dict]:
    known_edges = {(x["citing"], x["printed"]) for x in case["citations"] if x["role"] == "predicate"}
    rows = report.get("recall_summary", {}).get("by_device", [])
    results = []
    for witness in case["critical"]:
        required = {r["id"] for r in witness["records"]}
        observed = set()
        for row in rows:
            chain = row["chain"]
            if (chain[0] == case["k"] and chain[-1] == row["device"] == witness["holder"]
                    and set(zip(chain, chain[1:])) <= known_edges):
                observed.update(required.intersection(row["recall_ids"]))
        results.append({"holder": witness["holder"], "event": witness["event"],
                        "found": sorted(observed), "missing": sorted(required - observed)})
    return results


def citation_observations(case: dict, run: dict, model_only: bool = False) -> list[dict]:
    observations = []
    if not model_only:
        for path in run.get("report", {}).get("evidence_paths", []):
            observations.extend(path["hops"])
    origin = "llm" if model_only else "deterministic_fallback"
    for event in run.get("trace", []):
        if event.get("origin") != origin or not event.get("ok"):
            continue
        value = event["shown"] if model_only else event["result"]
        if event["tool"] == "list_citations":
            observations.extend({"src": value["k"], **row} for row in value["citations"])
        elif event["tool"] == "verify_citation":
            observations.append(value)
    results = []
    for anchor in case["citations"]:
        relevant = [o for o in observations if (o["src"], o["dst"]) == (anchor["citing"], anchor["printed"])]
        matching = [o for o in relevant if o.get("page") == anchor["page"]]
        role = anchor["role"]
        supported = any(
            (role == "predicate" and bool(o.get("in_lineage", o.get("counts_in_lineage")))
             and o.get("kind") == "predicate" and o.get("audit") != "unresolved")
            or (role == "reference" and o.get("kind") == "reference")
            or (role == "exclude" and o.get("audit") == "error"
                and not o.get("in_lineage", o.get("counts_in_lineage")))
            or (role == "disputed" and o.get("audit") == "unresolved")
            for o in matching
        )
        results.append({
            "citing": anchor["citing"], "printed": anchor["printed"], "page": anchor["page"], "role": role,
            "status": "matched" if supported else "role_unresolved_or_different" if matching
            else "different_page" if relevant else "absent",
            "observed_pages": sorted({o["page"] for o in relevant if o.get("page") is not None}),
        })
    return results


def observation(case: dict, raw: dict, live: bool = False) -> dict:
    report = raw.get("report", {})
    # Hash the deterministic projection without timing, generated IDs, or the growing report-store counters.
    projection = {key: report.get(key) for key in (
        "mode", "conclusion", "recall_summary", "evidence_paths", "missing_evidence", "uncertainties"
    )}
    projection["checklist"] = [
        [event["tool"], event["args"], event["result_sha256"], event["shown_sha256"]]
        for event in raw.get("trace", []) if event.get("origin") == "deterministic_fallback"
    ]
    trace = [
        {key: event[key] for key in ("tool", "args", "ok", "summary", "origin", "duration_ms", "shown_sha256",
                                     "result_sha256")}
        | {"omitted": bool(event["omitted"])}
        for event in raw.get("trace", []) if event["kind"] == "tool"
    ]
    reproducibility = report.get("reproducibility", {})
    result = {
        "k": case["k"], "status": raw["status"], "seconds": raw.get("seconds"), "error": raw.get("error"),
        "investigation_id": report.get("investigation_id"), "mode": report.get("mode"),
        "mode_note": report.get("mode_note"), "usage": reproducibility.get("usage"),
        "llm_errors": reproducibility.get("llm_errors"), "attempts": raw.get("attempts", []),
        "conclusion": projection["conclusion"], "recall_summary": projection["recall_summary"],
        "structured_witnesses": critical_detection(case, report),
        "structured_citations": citation_observations(case, raw),
        "evidence_paths": [
            {"chain": path["chain"], "hops": [
                {key: hop.get(key) for key in ("src", "dst", "page", "kind", "status", "audit", "provenance",
                                                "source_url")}
                for hop in path["hops"]
            ]} for path in report.get("evidence_paths", [])
        ],
        "missing_evidence": projection["missing_evidence"], "uncertainties": projection["uncertainties"],
        "agent": report.get("agent"), "proposals": report.get("proposals"), "tools": trace,
        "projection_sha256": hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest(),
    }
    if live:
        result["model_tool_citations"] = citation_observations(case, raw, model_only=True)
    return result


def review_projection(agent: dict) -> dict:
    return {
        "summary_status": "visible" if agent["summary"] else "withheld" if agent["summary_withheld"] else "absent",
        "summary_issues": agent["summary_issues"],
        "accepted": [x["claim"] for x in agent["findings_verified"]],
        "rejected": [{"claim": x["claim"], "reasons": x["reasons"]} for x in agent["findings_rejected"]],
    }


def recheck(graph, raw: dict) -> dict:
    """Re-run production report verification on previously captured live payloads."""
    k = raw["k"]
    record = {"k": k, "live_status": raw["status"]}
    submissions = [t for t in raw.get("trace", []) if t.get("tool") == "submit_report" and t["ok"]]
    if not submissions:
        return record | {"comparison": "no captured submission"}
    assert len(submissions) == 1, k
    before = raw["report"]
    repro = before["reproducibility"]
    ctx = RunContext(before["investigation_id"], k)
    for t in raw["trace"]:
        if t["kind"] != "tool" or not t["ok"]:
            continue
        if t["tool"] == "submit_report":
            ok, _ = run_tool(graph, t["tool"], t["args"], ctx)
            assert ok, k
        else:
            absorb_visible(ctx.ledger, t["tool"], t["shown"])
    after = report_builder.build(graph, ctx, {
        "id": before["investigation_id"], "request": before["request"], "target_k": k, "depth": repro["depth"],
        "status": raw["status"], "mode": before["mode"], "agent_version": repro["agent_version"],
        "finding_origin": "llm:" + ",".join(repro["model_used"]),
    })
    for key in ("conclusion", "recall_summary", "evidence_paths"):
        assert before[key] == after[key], (k, key)
    return record | {"comparison": "live submission replayed",
                     "before": review_projection(before["agent"]), "after": review_projection(after["agent"])}


def summarize(directory: Path, destination: Path, repeat: Path | None, archive: Path | None) -> None:
    frozen = read_json(EVAL / "cases.json")
    check_sources(frozen)
    cases = frozen["cases"]
    manifest = read_json(directory / "run.json")
    raw = [read_json(directory / f"{case['k']}.json") for case in cases]
    rows = [observation(case, result, live=manifest["mode"] == "llm")
            for case, result in zip(cases, raw, strict=True)]
    if repeat is not None:
        assert manifest == read_json(repeat / "run.json"), "repeat used different inputs"
        for case, row in zip(cases, rows, strict=True):
            second = observation(case, read_json(repeat / f"{case['k']}.json"))
            assert (row["status"], row["projection_sha256"]) == (
                second["status"], second["projection_sha256"]
            ), f"{case['k']} deterministic outputs changed"
        print(f"Reproduced {len(rows)}/{len(rows)} deterministic reports and checklist result hashes")
    write_json(destination, {"run": manifest, "cases": rows})
    if archive is not None:
        # Preserve the full reports, submitted arguments and exact visible tool results needed for replay.
        with gzip.open(archive, "wt", encoding="utf-8") as stream:
            json.dump({"run": manifest, "cases": raw}, stream, ensure_ascii=False, separators=(",", ":"))


def verify_submissions(archive: Path, destination: Path) -> None:
    frozen = read_json(EVAL / "cases.json")
    with gzip.open(archive, "rt", encoding="utf-8") as stream:
        captured = json.load(stream)
    manifest = captured["run"]
    assert manifest["mode"] == "llm" and manifest["graph_sha256"] == frozen["graph_sha256"]
    assert [c["k"] for c in captured["cases"]] == [c["k"] for c in frozen["cases"]], "frozen order mismatch"
    use_raw_cache(offline=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        copy = Path(tmp) / "graph.rl"
        shutil.copyfile(GRAPH, copy)
        assert sha256(copy) == frozen["graph_sha256"]
        graph = open_graph(copy, read_only=True)
        try:
            rows = [recheck(graph, raw) for raw in captured["cases"]]
        finally:
            graph.close()
    write_json(destination, {"run": manifest, "additional_inference_requests": 0, "cases": rows})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    comparison = parser.add_mutually_exclusive_group()
    comparison.add_argument("--repeat", type=Path, help="compare a repeated deterministic execution")
    comparison.add_argument("--recheck", action="store_true", help="replay report verification without inference")
    comparison.add_argument("--archive", type=Path, help="also save a compressed archive of exact raw results")
    args = parser.parse_args()
    if args.recheck:
        verify_submissions(args.run, args.output)
    else:
        summarize(args.run, args.output, args.repeat, args.archive)


if __name__ == "__main__":
    main()
