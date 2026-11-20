# Phase 3 · Evaluation and agent value validation

**Recommendation: NO-GO for relying on the autonomous report.** The agent added FDA-backed follow-up detail in some cases. Its published prose missed critical recall witnesses and overstated what the evidence established. Use the deterministic graph assessment as the primary evidence surface and keep its source gaps visible.

## Method

Both arms started with byte-identical copies of the shipped Relate store and used the committed offline FDA cache. Both received the same due-diligence request, target, and four-generation depth. The deterministic arm ran the shipped Phase 2 checklist, including its full graph assessment, evidence gaps, direct citations, source checks on significant routes, recall inspection and final report. The live arm used the shipped autonomous loop with NVIDIA Nemotron, its existing tool schemas, and explicit LLM mode. Its report incorporates the same deterministic builder. Shared content cannot establish model value, and a deterministic rescue after an incomplete run is counted separately from an autonomous completion.

The [cases](../eval/agent/cases.json) and [scoring protocol](../eval/agent/PROTOCOL.md) were committed at `2a84668` before either arm ran. The normalized case file SHA-256 is `7e3ad7b328c8ae095ac3d4f9a93ef08d7879bbf8cef582d055a5ccb5d968cee4`. The copied graph SHA-256 is `3ef2fab4317a3854a9e72c9f7b9c5be031dc90aceb32fd4233ba94341d3ffd20`. The Phase 2 demos K252078, K251770, K251889 and K201620 were excluded from the measured set and were not rerun.

### Provenance and coverage

| Stratum | Cases | Selection |
|---|---:|---|
| Recall signals | 8 | Own, direct and grand-predicate Class I records, single-event multi-record recalls and mixed causes |
| Naming conflicts | 4 | Unrelated clearance, ambiguous reference role, inferred correction and valid name variant |
| Uncertain lineage | 4 | Conflicting device identities, including an OCR-backed record and a suspect branch next to a supported Class I signal |
| Incomplete evidence | 4 | Missing PDF, misclassified cache status, scanned letter and unread direct predicate |
| Misleading or scoped no-signal results | 4 | Reference-only devices, honest scope controls and missing deeper ancestry |

The cases cover 15 BZD, 5 MNT, 3 CBK and 1 MNS clearances. The labels are 18 **agent-reviewed** and 6 **unresolved**, with **zero human-verified labels**. Unresolved tags concern the indicated interpretation and can coexist with a supported anchor or recall on another branch.

The manifest links each label to its FDA clearance entry, PDF page and hash where applicable, and any recall registry and enforcement rows. The review downloaded 27 summary PDFs whose bytes matched the frozen FDA hashes, inspected scan images for OCR-backed anchors, and confirmed the critical recall number, holder, event, classification and FDA cause against the original CDRH records and frozen openFDA responses. Pages are 1-based PDF positions. FDA filing content can refer to the same 510(k) in more than one role or on more than one page. A verified printed number establishes textual presence. A supported predicate relationship also requires role and identity evidence. [FDA device clearances](https://open.fda.gov/apis/device/510k/), [FDA recall registry](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm), [FDA enforcement reports](https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts/enforcement-reports)

### Scoring

- The critical set contains 17 target/holder/event witnesses across nine cases and 19 target/product-record checks. A witness requires at least one of its FDA IDs attributed to the correct clearance on a source-supported route. Record-level coverage is shown separately. These witnesses are sentinel signals. The evaluation does not estimate recall of every FDA record applicable to every associated model, accessory or lot.
- The 34 frozen citation anchors specify the citing clearance, printed number, page and role. The structured score covers the report and deterministic checklist. A second adjudication distinguishes a valid alternative page, an unresolved role and wrong attribution. Model-authored findings and exposed summaries receive a separate claim review. The production verifier status is retained as an observation.
- Uncertainty checks ask whether the report names the focal gap and qualifies the part of the lineage affected. Reassurance or completeness claims require scoped evidence. Useful findings require a concrete, supported detail or follow-up absent from the baseline report and checklist.
- Elapsed time is per investigation, including paced waits, tool execution and final report generation. Provider usage includes every accounted attempt and any length retry. End-to-end comparisons use the same cases. Non-completions are kept in the completion denominator.

## Measured results

| Measure | Deterministic | Live NVIDIA |
|---|---:|---:|
| Completed investigations out of 24 | 24 | 15 |
| Incomplete, deterministic rescue | 0 | 1 |
| Unattempted after the inference cap | 0 | 8 |
| Critical Class I witnesses in the graph section | 17/17 | 17/17 |
| Critical Class I witnesses in published model prose | — | 10/17 |
| Critical product IDs in the graph section | 19/19 | 19/19 |
| Critical product IDs in published model prose | — | 12/19 |
| Exact citation page and role on the 15 paired cases, report and deterministic checklist | 22/25 | 19/25 |
| Exact citation page and role inspected by the model on those cases | — | 17/25 |
| Focal uncertainty disclosed on the six unresolved labels | 5/6 | 4/6 in model prose |
| Cases with a material incremental finding | — | 5/15 completed |
| Median elapsed time on the 15 completed pairs | 0.078 s | 65.672 s |
| Model prompt and completion tokens, all attempts | 0 | 1,098,873 + 35,131 |

All nine cases with critical witnesses completed live before the cap, so the 17-witness comparison has no unattempted positives. The graph section was identical in its critical detections. The agent prose made seven omissions across two cases. An autonomous completion means the agent submitted findings. Five summaries were published and ten were withheld. The verifier accepted 88 findings and rejected 15 across the 15 submissions. Fourteen pending proposals changed no evidence.

The deterministic run matched 31/34 exact page and role anchors across all cases. A valid alternative PDF page explains one difference. Two remaining anchors describe the same conflicting role in K183226, where the workflow did not surface both pages as an unresolved conflict. The paired model retrieval count of 17/25 measures explicit citation-list or verification results the model actually saw. It includes five absent anchors, one valid alternative page, and the two K183226 conflicts. The numbers measure coverage of known anchors. Source adjudication below identifies errors in accepted prose independently of those counts.

For the six unresolved labels, the common clearance problem that both arms failed to surface was the contradictory role on K183226 page 15. The live budget interruption yielded no model prose for K023068. In the completed uncertainty cases, both arms usually identified the immediate evidence gap. Model prose still sometimes generalized a limited result, reclassified an unknown cause or spoke of a disputed route as established.

| Case | Deterministic s | Live s | Requests | Provider tokens | Agent witnesses | Main observation |
|---|---:|---:|---:|---:|---:|---|
| K211274 | 0.125 | 65.672 | 11 | 57,989 | 1/1 | Added recall reach and a named later clearance. Absence claim was withheld. |
| K210386 | 0.062 | 53.766 | 10 | 48,734 | 2/2 | Correct witnesses survived in separate findings. Summary hit an attribution false positive. |
| K253166 | 0.093 | 62.859 | 8 | 67,666 | 1/1 | Verified routes for lower-severity labeling recalls and distinguished them from the design recall. |
| K261262 | 0.063 | 76.891 | 7 | 43,564 | 1/1 | Added a separate packaging recall. Published an event-count error and an overbroad completeness claim. |
| K253647 | 0.078 | 66.344 | 13 | 80,750 | 0/4 | Grouped mixed FDA classes, losing four witnesses from the published model prose. |
| K230173 | 0.109 | 106.110 | 14 | 118,504 | 1/4 | Three Class I witnesses appeared only in the graph section. |
| K122715 | 0.203 | 90.625 | 14 | 144,072 | 2/2 | Both focal witnesses survived. Count parsing and other factual issues withheld the summary. |
| K993071 | 0.047 | 54.531 | 9 | 46,224 | 1/1 | Added recall-event reach across clearances despite unread target ancestry. |
| K241216 | 0.063 | 67.063 | 13 | 76,783 | — | Found the unrelated orthopedic record and identified provisional coverage, as the checklist did. |
| K183226 | 0.078 | 85.719 | 14 | 96,364 | — | Proposed link review and missed the contradictory conclusion on page 15. |
| K071702 | 0.093 | 60.156 | 7 | 48,698 | — | Identified the inferred correction and overclaimed that an unknown cause was non-design. |
| K252338 | 0.063 | 64.312 | 13 | 82,577 | — | Traced the Menai clearance. The summary was withheld. A finding confused the generation of an unread device with the depth of the missing link. |
| K151120 | 0.094 | 90.469 | 12 | 121,483 | 1/1 | Found the supported mask recall and flagged the naming conflict. An accepted finding still overstated the Class I/design overlap on the disputed ventilator branch. |
| K040944 | 0.047 | 47.157 | 10 | 49,554 | — | Named the conflict and abstained on lineage. |
| K972605 | 0.047 | 47.218 | 10 | 48,261 | — | Kept printed OCR evidence separate from device-identity doubt. |
| K023068 | 0.063 | 1.875 | 1 | 2,781 | — | Incomplete after the session cap. The deterministic rescue abstained. |
| K240778 | 0.046 | — | 0 | 0 | — | Live unattempted. |
| K993449 | 0.047 | — | 0 | 0 | — | Live unattempted. |
| K993307 | 0.062 | — | 0 | 0 | — | Live unattempted. |
| K191624 | 0.063 | — | 0 | 0 | — | Live unattempted. |
| K243583 | 0.078 | — | 0 | 0 | — | Live unattempted. |
| K253939 | 0.063 | — | 0 | 0 | — | Live unattempted. |
| K233643 | 0.156 | — | 0 | 0 | — | Live unattempted. |
| K260251 | 0.094 | — | 0 | 0 | — | Live unattempted. |

The live sweep consumed 166 requests, seven of them length retries. The 216,000-token cap on requested output stopped the sweep. Total provider-reported usage was 1,134,004 tokens. Of 1,040.8 seconds elapsed across attempted cases, 327.4 seconds were pacing and 710.8 seconds were spent in requests. The deterministic sweep took 1.94 seconds and zero inference requests. No NVIDIA rate-limit or transport error occurred. NVIDIA advertises its hosted developer endpoints for free prototyping. Account billing and remaining quota were unavailable, so usage and elapsed time are the measured costs. [NVIDIA NIM FAQ](https://docs.api.nvidia.com/nim/docs/product)

[Deterministic observations](../eval/agent/results/deterministic.json), [live observations](../eval/agent/results/live.json), [exact live reports and traces](../eval/agent/results/live_replay.json.gz)

### What the agent added

- **K211274, K210386 and K993071.** The agent used event-wide recall reach to identify later clearances worth checking. For K211274 it named K241469, whose filing documents the direct predicate, and found five later clearances across the event. For K210386 it named K231313, whose filing traces to K210386 and then to K140268 through K210386's filing. For K993071 it counted eight clearances after the recall began across the event's five linked clearances. These are review candidates. Inheriting a predicate relationship does not make a descendant an affected recall product. [K241469 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf24/K241469.pdf), [K231313 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf23/K231313.pdf), [FDA event 67108 record](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=124713)
- **K253166 and K261262.** The agent followed source routes for the separate labeling issues on K140980 and K121631 and distinguished them from the design recall on K183512. For K261262 it inspected the Class II packaging mix-up on fourth-generation K123979, a record outside the rule-selected report. These checks add context to records on the ancestry. They did not change either verdict. [K210844 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf21/K210844.pdf), [K140980 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf14/K140980.pdf), [FDA Z-1782-2022](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=195528), [FDA Z-2550-2016](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=148349)

## Failure investigation

- **K253647.** The graph report surfaced all four frozen Class I witnesses on K093633. The agent inspected several and grouped six records in one finding, with a Class I assertion that also swept in Class II records. The verifier rejected the finding and withheld the summary. The remaining model prose provided zero of the four witnesses with IDs. The assessment tool had shown the relevant signal without truncation, so failure to publish the evidence cannot be attributed to context shaping in this case. Page 7 of K222024 is a valid alternative to the frozen page 4 anchor. [K222024 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf22/K222024.pdf), [Class I Z-0827-2016](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=143615), [Class II Z-0108-2022](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=189133)
- **K230173.** The model prose identified event 89767 on direct predicate K102985 and left three frozen Class I events without specific citations. It retrieved aggregate counts and devoted calls to the longer V60 branch. The graph report retained all four witnesses and the rest of the rule-selected IDs. [K230173 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf23/K230173.pdf), [Z-2631-2023](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=203284), [Z-2061-2017](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=154944), [Z-1537-2013](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=118739)
- **K261262.** The exposed summary called product records from FDA event 93499 two events. Its summary and a finding also described complete evidence across four generations. The verified citation checks established the four printed links. The evidence completeness status describes two generations, and the run found zero tracked deeper gaps. The wider completeness claim exceeds that scope. The original verifier accepted both the summary and the finding. [Z-0537-2024](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=204518), [Z-0541-2024](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=204522)
- **K210386 and K122715.** The K210386 summary explicitly assigned each record to its correct clearance and was withheld after a false attribution alarm. Separate findings carried both witnesses. K122715 findings containing the year range `2022-23` generated a spurious count of 23 Class I records. Other statements in that report also mixed event totals and devices. A rejection can indicate a parser limitation, a factual error or both. [Z-1784-2022](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=195533), [Z-1783-2022](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=195532), [Stellar 150 Z-0915-2020](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=178585)
- **K071702 and K151120.** An exposed K071702 summary treated FDA's `Other` cause as established non-design. The snapshot lacked classifications for Z-0444-2007, Z-1057-2008 and Z-1085-2008. The original registry identifies all three as Class II. An accepted K151120 finding claimed five Class I design-related records on K083526, where the snapshot contains only four design-related records across all classes. The model joined two different count definitions and used a disputed ancestry branch. [FDA Z-0444-2007](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=48388), [FDA Z-1057-2008](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=66491), [FDA Z-1085-2008](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=66522), [FDA Z-1956-2021](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=187816)

## One targeted optimization

The K261262 event-count contradiction triggered a narrow verifier check at `fa30748`. A count explicitly tied to a single FDA event ID must be one event. A valid statement that one event has multiple product records still passes. The retest ran the original and revised report verification against the captured model submissions and the exact model-visible tool results. It covered the same 24 frozen case slots, with 15 captured submissions available for paired verification. The original verifier replay reproduced all 15 outcomes. No new NVIDIA request was needed.

| Report-layer measure on the same captured submissions | Before | After |
|---|---:|---:|
| Published summaries | 5 | 4 |
| Withheld summaries | 10 | 11 |
| Exposed single-event count contradictions observed | 1 | 0 |
| Accepted findings | 88 | 88 |
| Agent prose critical witnesses | 10/17 | 10/17 |
| Shared graph section critical witnesses | 17/17 | 17/17 |

The only changed outcome was withholding the K261262 summary. Its specific Class I findings still cite both product records, and its separate unsupported completeness claim remains exposed in a finding. The seven critical omissions remain. The comparison measures verifier behavior on actual submissions. It provides no new measurement of inference quality, latency or cost after the change. [Per-case verifier comparison](../eval/agent/results/verifier_comparison.json)

### Skeptical source review

The independent checks used original FDA registry fields and PDFs, separate from the graph and application verifier. The semantic adjudication is coding-agent review. There was no second human adjudicator or inter-rater estimate.

- **K183226.** Pages 4 and 6 describe DirectView K083526 as a reference. Page 15 names it as a predicate in the substantial-equivalence conclusion. The graph excludes the edge through a machine audit and discloses a gap. The agent proposed human review but did not identify the contradictory page, and its question incorrectly moved the relationship to K152356. Class I Z-1956-2021 is filed on K083526, so resolving this role would materially affect the investigation. The freeze keeps the role unresolved. [K183226 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf18/K183226.pdf), [FDA recall Z-1956-2021](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=187816)
- **K151120.** The PDF uses K093416 for a small-child mask and the Trilogy 200 reference. The FDA clearance identifies Trilogy 200. A verified PDF match on page 6 establishes that the number is printed beside the mask, and the graph's flagged route still places ventilator recalls in its recall table. The supported Class I witness in this case is on K140268, a separately named primary predicate. [K151120 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf15/K151120.pdf), [K093416 FDA summary](https://www.accessdata.fda.gov/cdrh_docs/pdf9/K093416.pdf), [Z-1783-2022](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=195532)
- **K233643.** The shared graph also treats K033008 as a predicate, even though the PDF places it in the reference table with the V60. This extra issue was found while reading the frozen case's source. The frozen V60 reference anchor and its original score criteria remain in place. [K233643 summary, pp. 5–6](https://www.accessdata.fda.gov/cdrh_docs/pdf23/K233643.pdf)
- **K993449 and K191624.** FDA serves the K993449 scanned summary, which names four related clearance IDs on its first page, including the Servo 300A K970839. One FDA record on that clearance is a Class II design recall. Its precise role in this filing should be reviewed before attribution. FDA also serves the K170367 summary, which the shipped graph had not read for the K191624 investigation. Neither arm had those newly checked PDFs as an input. [K993449 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf/K993449.pdf), [FDA Z-1252-2009](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=80384), [K170367 summary](https://www.accessdata.fda.gov/cdrh_docs/pdf17/K170367.pdf)

The sample is purposive, dominated by BZD, and shares some predicate families and recall events. The sentinel results do not establish exhaustiveness across product codes, other FDA filings or future snapshots. The model was run with one prompt and one endpoint configuration. A clean result in Forebear applies to the specified evidence window and file snapshot.

## What Relate adds

The isolated FDA 510(k) row for **K261262 (Altis Full Face Mask)** provides the clearance and applicant data. It contains no predicate relationship or recall field. Its PDF names immediate predicate K242547. The shipped snapshot has zero recall records directly attached to K261262. Following the two predicate relationships and then the FDA recall relationship returns two product records for grand-predicate K170924, both in Class I event 93499. Those FDA records describe earlier products. They establish a review signal in the ancestry. [K261262 FDA clearance record](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID=K261262), [K261262 PDF, p. 6](https://www.accessdata.fda.gov/cdrh_docs/pdf26/K261262.pdf), [K242547 PDF, p. 5](https://www.accessdata.fda.gov/cdrh_docs/pdf24/K242547.pdf), [Z-0537-2024 FDA record](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=204518), [Z-0541-2024 FDA record](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id=204522)

Run this from the repository root after the deterministic run below. The Relate accessor follows `CITES` edges in the predicate direction, then joins each reachable holder to its `SUBJECT_OF` recalls.

```powershell
@'
import json
from pathlib import Path
from forebear.graph import open_graph

k = "K261262"
frozen = json.loads(Path("eval/agent/cases.json").read_text(encoding="utf-8"))
case = next(case for case in frozen["cases"] if case["k"] == k)
cache = Path(case["clearance_records"][0]["cache"])
row = next(row for row in json.loads(cache.read_text(encoding="utf-8"))["results"] if row["k_number"] == k)
print(row["k_number"], row["device_name"], row["decision_date"])
print("Clearance fields:", sorted(row))
g = open_graph("data/live/phase3/repro-baseline/graph.rl", read_only=True)
try:
    print("Target-only recall IDs:", [r["id"] for r in g.device(k)["recalls"]])
    for ancestor in g.ancestors(k, 2):
        for recall in sorted(ancestor["recalls"], key=lambda r: r["id"]):
            if recall["classification"] == "Class I":
                print(" -> ".join(ancestor["chain"]), recall["id"], recall["event"], recall["classification"])
finally:
    g.close()
'@ | .venv\Scripts\python.exe -
```

```text
K261262 Altis Full Face Mask 2026-09-25
Target-only recall IDs: []
K261262 -> K242547 -> K170924 Z-0537-2024 93499 Class I
K261262 -> K242547 -> K170924 Z-0541-2024 93499 Class I
```

The graph returned this result in the deterministic arm. A person could reconstruct it by opening both PDFs and joining the FDA records manually.

## Reproduce

Use checkout `13b31bf` for the frozen Phase 3 graph and evaluation commands. The Phase 3.5 build changes the shipped graph SHA-256 and keeps these historical cases and observations intact. [Phase 3.5 provenance](../data/PROVENANCE.md#phase-35-source-corrections)

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\evaluate_agent.py --mode deterministic --out data/live/phase3/repro-baseline
.venv\Scripts\python.exe scripts\evaluate_agent.py --mode deterministic --out data/live/phase3/repro-repeat
.venv\Scripts\python.exe scripts\summarize_agent_evaluation.py data/live/phase3/repro-baseline data/live/phase3/repro-baseline.json --repeat data/live/phase3/repro-repeat
.venv\Scripts\python.exe scripts\summarize_agent_evaluation.py eval/agent/results/live_replay.json.gz data/live/phase3/repro-verifier.json --recheck
```

The repeat reproduced 24/24 report projections and checklist result hashes. The repository suite passed 239 tests, including an offline rebuild on a temporary store, the budget tests and the targeted count check. The summary command also checks frozen FDA cache fields and page anchors without opening Relate or using the application verifier.

The separate live command spends NVIDIA inference quota. It needs the existing NVIDIA variables and the official hosted endpoint. The original capture ran at `2a84668`. A fresh run at `13b31bf` uses the revised Phase 3 verifier, and the hosted model can vary across runs. Run directories must be new. Each contains the full reports, tool results, model-visible payloads, elapsed time, usage from every SDK attempt and a working graph copy. The exported observations preserve submitted content, verification outcomes, decision and gap data, tool calls and trace hashes.

```powershell
.venv\Scripts\python.exe scripts\evaluate_agent.py --mode llm --out data/live/phase3/repro-live
.venv\Scripts\python.exe scripts\summarize_agent_evaluation.py data/live/phase3/repro-live data/live/phase3/repro-live.json
```
