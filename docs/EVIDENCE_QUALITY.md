# Evidence quality (Phase 1)

How accurate, traceable and uncertainty-aware Forebear's FDA evidence is, how that was measured, what changed, and
what is still unknown. Written for the Phase 2 investigation agent and for anyone checking its findings.

**Who decided what.** All audit decisions and evaluation labels in this phase were made by the extraction audit run by
an AI coding agent (Claude Code) reading the cached FDA page text and openFDA records. None of them is a human
sign-off. They are stored apart from human review (`audit*` edge properties, `eval/*labels*.json`), they say so in
`audit_by` / `labeller`, and a human review in the app overrides them. The optional NVIDIA-hosted LLM was tested
(section *LLM triage*) and is not used for any decision.

## Summary

| Measure | Before (main @ d9fa0aa) | After (this branch) |
|---|---|---|
| In-family summaries readable | 571 of 1,040 (527 with predicates, 44 without) | 639 (533 + 45 OCR + 1 embedded attachment with predicates; 38 + 22 OCR without) |
| Image-only summaries unread | 68 | 0 unread; 67 OCR'd, 1 recovered from a PDF Portfolio attachment |
| Predicate edges extracted | 1,079 | 1,229 (+66 recovered from long predicate tables, +1 from the portfolio, +88 from OCR, −5 non-predicates) |
| Estimated extraction precision (sample, see *Evaluation*) | 0.995 | 0.999 (95% lower bound on the unchanged stratum: 0.912) |
| Predicate edges flagged "name ≠ FDA record" | 124 (unexplained) | 122 by name check v2 + 26 by panel check; **every** flagged edge decided |
| Original 124 flags | unknown mix | 88 legitimate name differences, 13 K-number errors, 9 not predicates, 14 unresolved |
| Verified K-number errors removed from lineage | 4 (curated) | 13 (audit), 12 with a verified correction (6 new edges, 6 already cited correctly) |
| Non-predicate citations removed from lineage | 0 | 8 by audit, 5 by extraction rules |
| Predicate links awaiting a human decision | — | 21 (`eval/link_audit_queue.json`) |
| Cited K-numbers that could not become edges | 3, silently dropped | 11, recorded on the citing device (4 predicate citations) and surfaced in assessments |
| Recall records linked | 559 | 563, each link with name/timing evidence; 55 recalls that name no 510(k) kept per product code (16 design-related) |
| "No design-recall signal" verdicts that are explicitly provisional | 0 | 255 of 356; 6 more became "Lineage not checkable" |

All numbers come from `data/build_report.json`, `eval/link_audit.json`, `eval/extraction_eval.json` and the commands
under *Reproduce*.

## How the audit works

Everything below runs offline from the committed cache (`data/raw/`), except the two fetch steps, which are the
only commands that write `data/raw/`.

### 1. Deterministic checks on every extracted edge
`forebear/evidence.py` compares what the summary text says about a cited K-number with that device's openFDA record.
No check removes an edge on its own; each one is stored on the edge and read by the audit and the lineage rules.

| Check | Question | Stored as |
|---|---|---|
| Name check v2 | Does a distinctive word of the cited device's FDA name appear in the text that names that K-number? | `name_check` (`match` / `mismatch` / `n/a`), `name_check_method` |
| Local span | Which slice of the page names this K-number (from the previous citation to the next, grouped citations kept together)? | `quote` (≤ 400 chars) |
| Panel check | Is the cited device reviewed by the same FDA advisory committee as the citing one? (All 1,040 in-family devices are anesthesiology, `AN`.) | `panel_check` |
| Correction candidates | Which known K-numbers are one digit, or one adjacent transposition, away and have a matching name? | audit report only |

Name check v2 tolerates OCR damage (`rn`→`m`, `~`→`g`), run-together words (`REVOLUTIONFULL`), FDA misspellings
(`RESCAN`, `Galapogos`, `ESPIRT`) through a small edit distance, and model codes (`LP-6`, `840`, `7200`), but ignores
regulation numbers, years and K-numbers, and words cut off at the span edge. It reads the local span instead of a
fixed window, so a neighbouring device's name in a list no longer produces a false "match".

### 2. Extraction rules (`forebear/predicates.py`, method `regex-context-v3`)
- A predicate label must sit in the same sentence as the K-number, unless it is a heading or table caption
  ("Predicate Device(s):", a line starting with "Predicate ..."). This stops "...than the predicate device. Users can
  upload the data to the cloud platform (K160127)" from producing a predicate.
- A predicate heading stays in force down a long table or list (beyond the old 220-character limit) as long as no
  sentence intervenes. This recovers predicates listed far below their heading.
- A K-number in a sentence about an accessory, compatible device, tubing, modem, cloud/connectivity platform or display
  system is a mention, unless that sentence itself says "predicate", "substantially equivalent" or "legally marketed".
- Each hit keeps its local span as the quote.

### 3. Verified OCR for image-only summaries
`scripts/fetch_data.py ocr` (optional dependencies in `requirements-ocr.txt`, no system binaries):
1. Download the PDF again from the URL in `data/raw/summaries/{K}.json`.
2. Refuse to OCR unless its SHA-256 equals the one recorded when the summary was first fetched (`sha_mismatch`).
3. Render each page at 300 dpi (pypdfium2) and read it with RapidOCR (ONNX models bundled in the pinned wheel).
4. Group boxes into lines so table rows stay together; drop non-Latin glyphs; record per-page mean confidence.
5. Write `data/raw/ocr/{K}.json` with engine and version, dpi, page confidences, low-confidence pages and outcome.

The build uses OCR text only through `summaries.load_text()`, which checks the SHA-256 again. Devices read this way
have `summary_status = "ocr"` and `text_source = "ocr"`, and their edges carry `method = regex-context-v3+ocr`. Every
OCR-read K-number must still resolve in openFDA and predate the citing device. The PDFs are not kept.

### 4. Audit decisions (`data/audit/link_decisions.json`, applied by `forebear/audit.py`)
Population: every predicate edge flagged by the legacy name check (which produced the original 124 flags), name check
v2 or the panel check. `python scripts/audit_links.py` lists them with all signals. Each flagged edge was then read in
the full cached page text, together with the cited device's FDA record and, where cached, its own summary.

Decision rule: the legal citation is the K-number, so an edge is
- **error** only when evidence shows the K-number identifies a different product: another FDA panel, or the cited
  device's own summary *and* FDA's other records (recalls) describe something else. With `correct_to`, the build adds the edge to the device the text
  does name, marked `audit = "corrected"`, but only if that K-number exists in openFDA and predates the citing device;
- **not_predicate** when the K-number is cited for a component, accessory, data platform or as a reference device;
- **variant** when the K-number plausibly identifies the named product (same manufacturer and product line, OCR damage,
  the name elsewhere on the page, an FDA record name that differs, a cross-panel secondary predicate whose name matches);
- **unresolved** otherwise. These stay in the lineage, flagged, and are listed in `eval/link_audit_queue.json`.

Audit decisions are written to the edge's `audit`, `audit_note`, `audit_by` and `corrected_from` properties, never to
`review`/`reviewer`. `audit_by` says "Claude Code agent; not human-reviewed". A human review in the app (or the
`review_citation` MCP tool) overrides any audit decision. The 4 older curated reviews in `data/reviews.json` are kept
as they were; the audit reached the same conclusion on all 4.

Lineage rule (`graph.LINEAGE_EDGE`): a person confirmed it, OR (the extractor said predicate, or the LLM labelled a
mention predicate) and the audit did not mark it `error`/`not_predicate`, unless a person rejected it.

### 5. Uncertainty in assessments (`forebear/lineage.py`, rules `forebear-rules-v3`)
A lineage hop is **doubtful** when it is audit-unresolved, its K-number was supplied by an audit correction rather than
printed in the PDF, its name check fails, its cited device is from another panel (unless the audit found a variant), or
only the LLM made it a predicate. A person's confirmation clears
it. Each assessment now reports `coverage.evidence`:

| Value | Meaning | Effect |
|---|---|---|
| `complete` | No doubtful hop and nothing missing within two generations | none |
| `partial` | A doubtful hop within two generations; a direct predicate whose own summary was not read; an unresolved predicate citation in the candidate's or a direct predicate's summary; a recall within two generations with no stated root cause (`Other`, `Under Investigation by firm`, missing) or, on the candidate or a direct predicate, no FDA classification; or design-related recalls in the candidate's product code that name no 510(k) | A "no signal" result is prefixed **Provisional** and says why |
| `uncertain` | Every direct predicate link is doubtful | A "no signal" result becomes **INSUFFICIENT_LINEAGE** ("Lineage not checkable") |

New info-level signals: `UNCERTAIN_LINK_IN_LINEAGE`, `PREDICATE_CITATION_UNRESOLVED` (cited K-number not in openFDA,
cleared after the citing device, or removed by the audit or a reviewer, minus audited corrections),
`RECALL_CAUSE_OR_CLASS_UNKNOWN` and `UNATTRIBUTED_RECALLS_IN_PRODUCT_CODE`. Recall severity rules are unchanged, so uncertainty can only lower confidence in a
reassuring result, never hide a recall signal.

### 6. Recall joins
The device-to-recall join is FDA's own (`k_numbers` on the openFDA recall record). The build now also records, on each
`SUBJECT_OF` edge, whether the recall's product/reason text names the linked device (`name_check`) and whether the
recall started before that device was cleared (`before_clearance`), and keeps per product code the recall records that
name no 510(k) at all (they exist, but no lineage query can see them). Classification comes from enforcement reports
joined on recall number; recalls without one stay unclassified, and the rules treat an unclassified design recall within
two generations as a review signal.

### 7. Reproducibility guard
`build_graph.py` now calls `use_raw_cache(offline=True)`: a missing openFDA cache entry raises instead of silently calling
the network. `fetch_data.py expand` computes exactly the query sets the build uses, so after the extraction rules or the
OCR cache change, `expand` followed by `build_graph.py` reproduces the store with no network during the build.

## Results

### The original 124 flagged links
Each of the 124 edges the previous build flagged was traced to its current state (computed from the old build's flag
list against the rebuilt store):

| Outcome | Count | How |
|---|---|---|
| Legitimate naming difference, resolved by name check v2 | 38 | e.g. ResScan vs FDA "RESCAN", "Galapagos" vs "Galapogos", "Revolution Full Face Mask" vs "REVOLUTIONFULL", OCR "Slurnbergear" |
| Legitimate naming difference, audit `variant` | 50 | name elsewhere on the page, renamed product (Magneto → Therapy Mask 3100; REMstar Auto A-Flex HT → DreamStation, per FDA recall records), a mask added in a ventilator clearance (K092043, per its own summary), option clearances of a named ventilator (Dräger Evita NIV/NeoFlow), cross-panel secondary predicates (Masimo, Nihon Kohden, HomMed) |
| Genuine K-number error, audit `error` | 13 | the K-number belongs to a suture, a gastroscope, an insulin assay, a hip implant, a meniscal implant, an apheresis system, stents, an ECG module, a bone cable, a patient monitor, a guidewire or a lab test |
| Not a predicate | 9 | 4 reclassified by the new extraction rules (cloud platform, accessory, display system, material source); 5 by audit (accessory modem, tubing, compatibility, data platform, reference device, feature history) |
| Unresolved | 14 | same manufacturer, but the cached records cannot show whether the clearance covered the named product (ResMed "Modular Mask" under K961783, "Mirage Nasal Mask" under K984428, Respironics "Profile Lite Small Child" under the Trilogy 200's K093416, AutoScan under K024191, ...) |

### Verified corrections
Applied only when the intended device is shown by the text, the corrected K-number exists in openFDA, names that
device, and predates the citing clearance:

| Citing | Cited (wrong) | openFDA says | Corrected to |
|---|---|---|---|
| K080079 S8 Escape II | K010909 | surgical suture | **K013909** S7 Elite (one digit) |
| K040202 Salter CPAP cannula | K012263 | Marquette Eagle monitor | **K010263** REMstar Plus (one digit) |
| K053607, K071702 Breas Vivo 40 | K982545 | Biomet bone cable | **K982454** BiPAP Vision (manual; digit pair swapped) |
| K063830 REMstar Auto M-Series | K040101 | Diadexus lab test | **K041010** REMstar Auto with C-Flex (manual; two digit swaps; K050759 cites the same device as K041010) |
| K063404 Servo-i | K896391 | Bard stents | **K896381** MVP-10 (one digit) |
| K112271 3B Willow | K042043 | Fujinon gastroscope | K042403 Mirage Swift (already cited correctly) |
| K130178 Inspiration 5i/7i | K072950 | Cygnus ECG module | K072590 Inspiration (already cited) |
| K123149 Servo-i | K073149 | Arthrex meniscal cinch | K073179 Servo-i (already cited) |
| K180295 HAMILTON-G5 | K131744 | Terumo apheresis | K131774 HAMILTON-G5 (already cited) |
| K132013 Swift Air | K060359 | insulin assay | K050359 Ultra Mirage II (already cited) |
| K241216 myAir | K200656 | Lima hip system | K200565 Galapagos (already cited) |

One further error has no verifiable correction (K092835's "Reusable Contour II (K991646)", a guidewire, is cited for a
design feature only). Citing devices whose predicate citation was removed report `PREDICATE_CITATION_UNRESOLVED`.

### Coverage: OCR and other recovery
68 image-only summaries were processed; all 68 downloads matched the recorded SHA-256 (no `sha_mismatch`).

| Outcome | Count |
|---|---|
| OCR, readable, predicates found | 45 (88 predicate edges) |
| OCR, readable, no predicate found | 22 |
| PDF Portfolio: summary read from its embedded attachment's text layer (K163127, predicate HAMILTON-C2 K121225) | 1 |
| Unreadable | 0 |

OCR quality: 430 pages, mean box confidence ≥ 0.80 on every page; 2 documents have a page below 0.90. A seeded sample of
20 of the 88 OCR edges was read in the OCR page text: 20/20 genuine predicate citations. Of the 22 OCR'd
summaries without a predicate, 21 do contain K-numbers, but older (1990s) summaries phrase equivalence as "Data
Comparison Sheet" tables or "equivalent device circuit as ..." with no predicate label, so the extractor keeps them as
mentions; one names a predecessor without a K-number. These 22 devices remain "lineage unknown" and are never shown as
green; their mentions can be confirmed by a person (or LLM-labelled on request) in the app.

Still unread and why (unchanged by design): 354 clearances filed a 510(k) Statement (no public summary), 35 have no
summary PDF online, 12 predate 1996, and 147 out-of-family predicates are metadata-only until someone ingests them.

### Lineage, dates and duplicates
- Every edge still requires the cited K-number to exist in openFDA and to be decided on or before the citing device.
  Citations that fail are now kept on the citing device (`unresolved_citations`): 8 K-numbers not in openFDA (mostly OCR
  digit damage such as K481744, K581412) and 3 cleared after the citing device; 4 of the 11 are predicate citations.
- Duplicates: the cache holds 1,941 recall rows for 618 recall numbers (overlapping queries). Repeats agree field for
  field, except 7 whose product text differs only in line endings between older and newer fetches; the build keys
  recalls on `product_res_number`. 510(k) records and citation edges are keyed by K-number and (src, dst) with `MERGE`.
- Dates: all cached recall start dates parse; 2 recall-device links start before that device was cleared
  (Esprit recall Z-1230-04 lists two later Esprit clearances) and are marked `before_clearance`.
- Recall classification: 184 of 563 linked recalls have no enforcement report and stay unclassified; an unclassified
  design recall within two generations is treated as a review signal.
- 106 of 762 recall links have product text that does not name the device by the name check (the join is FDA's
  `k_numbers`; often the product text uses a model number or a family name). This is recorded per link, not used to
  drop links.

### BreathePal demo chain, verified independently
From the raw cache, then through the graph (`tests/test_shipped_evidence.py`):
1. K252078 BreathePal Bilevel (Compal, received 2025-07-02, decided 2026-03-17). Summary
   `cdrh_docs/pdf25/K252078.pdf` (SHA-256 recorded), page 5: "Primary Predicate Device BiPAP A30 Ventilatory support system
   (K113053)"; page 6 states substantial equivalence to it; page 7 has the comparison table. It is the only K-number the
   summary cites.
2. K113053 is Respironics "BIPAP A 30 VENTILATORY SUPPORT SYSTEM", decided 2012-02-01, before BreathePal was received.
   The edge has no audit flag (name check `n/a`: the FDA name has no distinctive word).
3. Recalls Z-1957-2021 and Z-1958-2021 (event 88071) and Z-1973-2021 (event 88058): root cause "Device Design",
   Class I (enforcement reports), initiated 2021-06-14, reason text about PE-PUR foam, and FDA's `k_numbers` include
   K113053. Z-1973-2021's product text does not name the A30, so that join rests on FDA's K-number list alone; this is
   now visible on the link.
4. Verdict: REVIEW_LINEAGE (direct predicate with a Class I design recall). Unchanged by Phase 1. The audit removed one
   grand-predicate edge of this lineage (K113053 → K071509, a feature history, not a predicate), which does not affect
   the verdict.
5. Caveat: these recalls cover product families. Z-1957-2021's product text names the BiPAP Hybrid A30 / V30 Auto and
   Z-1973-2021's names DreamStation ASV/ST/AVAPS models; FDA lists K113053 among their clearances. The signal is
   "FDA attributes a Class I design recall to the predicate's clearance", not "this exact model was recalled".

### Uncertainty in assessments (all 1,040 in-family devices, rules v3)
| Verdict | Count | Evidence status |
|---|---|---|
| DESIGN_RECALL_ON_FILE | 99 | |
| REVIEW_LINEAGE | 137 | |
| NO_DESIGN_RECALL_SIGNAL | 356 | 101 complete, 255 **Provisional** (partial) |
| INSUFFICIENT_LINEAGE | 448 | includes 6 that would have been green but whose every direct link is doubtful |

Common reasons for "partial": a direct predicate whose own summary was never read (out-of-family, metadata only), a
nearby recall with root cause "Other" or "Under Investigation by firm", and design-related recalls in the product code
that name no 510(k).


## Independent review and what changed
A separate reviewer agent re-checked the audit against the cached evidence (no network, a copy of the store). Its
substantive findings, all verified and addressed in this branch:

| Finding | Fix |
|---|---|
| K201620 → K131982 was marked `error` ("DreamStation" vs FDA name "REMstar Auto A-Flex HT"), but FDA's own recall records (Z-1322-2023, Z-2228-2025) file DreamStation Auto BiPAP under K131982. The removal hid a Class I design recall: K201620 showed a provisional green instead of REVIEW_LINEAGE. | Now `variant`; K201620 is REVIEW_LINEAGE again (regression test). The error rule now requires the cited device's records, not just its 510(k) name, to contradict the text. |
| K120562 → K092043 was marked `error`, but K092043's own summary says it added the Performax Youth EE mask. | Now `variant`. |
| K093416 ("Profile Lite Small Child" vs Trilogy 200) rated `error`/`not_predicate` against the rubric; the firm's own K151120 uses K093416 for the mask throughout. | Now `unresolved`; conflict with the curated rejections documented. |
| Recalls with no root cause or classification were treated like known non-design recalls. | They now make a green result provisional (`RECALL_CAUSE_OR_CLASS_UNKNOWN`). |
| Agent-made corrections counted as fully trusted; unattributed design recalls did not affect completeness. | Both now make results partial. |
| `link_recalls`/`unattributed_recalls` defined twice in `dataset.py`; OCR could be accepted if both SHA-256 values were missing. | Duplicates removed; a SHA-256 is now required on both sides (test). |
| Two audit quotes were not verbatim; K063830 had an evident correction (K041010); two `variant` labels were too generous. | Quotes fixed, K041010 applied as a documented manual correction, K062793 → K940870 now `not_predicate`, K092847 → K081837 now `unresolved`. |

Lesson recorded for Phase 2: an FDA 510(k) device name is the submission-era name; before calling a K-number a typo,
check the cited device's own summary and the recall records that cite it.

## Evaluation

`scripts/eval_extraction.py` compares the pre-Phase-1 extractor (kept verbatim in `eval/legacy/predicates_v2.py`, text
layer only) with the current one on the same validated universe of (citing, cited) pairs, stratified:

| Stratum | Population | Read | Genuine predicate citations |
|---|---|---|---|
| both (unchanged) | 1,074 | 40 (seed 17) | 40 |
| old only (demoted) | 5 | 5 | 0 |
| new only (recovered from text) | 67 | 67 | 66 (K143677 → K082209, a module in a comparison-table cell, is wrong) |
| OCR | 88 | 20 (seed 17) | 20 |

Precision estimate: 0.995 before, 0.999 after. **Read this with care.** The unchanged stratum's 40/40 only bounds its
precision below at 0.912 (exact 95%), and the link-audit census, which read every flagged edge in full, found 8
non-predicate citations and 13 K-number errors that the extractor still produces; the audit removes them from lineage,
but the extractor's true precision is lower than the point estimate. Labels are the agent's reading of the full page,
recorded per edge in `eval/extraction_eval_labels.json`; a correct citation of a mistyped K-number counts as a correct
extraction there and as an error in the link audit.

Adversarial regression tests (`tests/test_extraction_rules.py`) cover: a predicate label leaking into the next
sentence, accessory/compatible/display-system mentions, a predicate heading over a long table, the classification name
"Accessory to Noncontinuous Ventilator" inside a predicate list, run-together and misspelt FDA names, truncated words,
regulation numbers and years posing as model numbers, and grouped citations. One known limitation is pinned by a test:
a compatible device named in a sentence that also says "predicate" is still extracted as a predicate (the audit catches
those).

### LLM triage
`scripts/llm_triage_experiment.py` ran the app's quote-checked triage call (NVIDIA-hosted nemotron, mistral fallback) on
the 30 hardest labelled items, at most one call plus one fallback each, writing nothing to the graph. 28 answered;
agreement with the audit was 5/28. It labelled most rows of genuine predicate tables as "reference". It did not help,
so it is not used in the audit or the build; the existing on-request "Ask AI to label" stays as it was (its label is
still visible, overridable, and an LLM-only link now counts as doubtful in assessments). Results:
`eval/llm_triage_experiment.json`.

## Remaining limitations
- **21 unresolved links** stay in the lineage, flagged; they need a person (`eval/link_audit_queue.json`).
- **Curated reviews that conflict with the evidence.** `data/reviews.json` rejects K120562/K120639/K151120 → K093416
  through the human-review field (reviewer `curated`, no named person). Respironics' own K151120 cites the Profile Lite
  Small Child mask as K093416 on six pages, so the audit rates these links `unresolved`; the curated rejections still
  win until a person re-checks them. They were left unchanged because they are the maintainer's review records.
- **Extractor precision is below the sample estimate**: the 21 wrong edges the audit found are handled by
  `data/audit/link_decisions.json`, not by the rules. New or re-ingested summaries get the rules only; only edges with a
  recorded decision get the audit. The queue is regenerated by `scripts/audit_links.py`.
- **Unflagged errors are not measured.** The census covers edges that the name or panel check flags. An edge whose
  wrong K-number happens to belong to a similarly named device of the same panel passes both checks; the random sample
  (40) found none, which bounds but does not exclude them.
- **Name check `n/a`**: FDA names without a distinctive word (e.g. "BIPAP A 30 ...") cannot be checked.
- **Pre-2000 comparison-sheet summaries** (22 OCR'd, plus some text-layer ones) state equivalence without a predicate
  label and stay as mentions.
- **Out-of-family predicates** are metadata only (147), so many lineages stop at generation 1 or 2 (hence most
  "Provisional" results).
- **Recall attribution** depends on FDA's `k_numbers`; 55 recall records name no 510(k) and cannot be attributed.
- **Live ingest** applies the rules, the audit decisions file and recall-link evidence, but does not OCR (the OCR
  dependencies are optional and the step is offline-only).
- The 4 older curated reviews record no named person; the audit agrees with 1 (K092835 → K991646) and rates the other 3
  `unresolved` (above).

## Blockers and inputs for Phase 2
1. A person should work the 21-item queue and re-check the 3 conflicting curated rejections; the agent must treat those links as doubtful until then (it does: they count
   in `coverage.doubtful_links` and make results provisional).
2. The agent should read `coverage.evidence` and the uncertainty signals (`UNCERTAIN_LINK_IN_LINEAGE`,
   `PREDICATE_CITATION_UNRESOLVED`, `UNATTRIBUTED_RECALLS_IN_PRODUCT_CODE`), exposed through the API and the
   `check_predicate` MCP tool, and must not report a provisional "no signal" as a clean result.
3. To deepen provisional lineages the agent will need to ingest out-of-family predicates live; those edges get rules
   but no audit, so it should rerun `scripts/audit_links.py` (offline, on the rebuilt raw cache) or flag them.
4. No new dependency is required at runtime; OCR needs `requirements-ocr.txt` only when refreshing the cache.

## Intentional data changes
- `data/raw/ocr/` (new, 68 files): recovered text with engine, version, dpi, confidences and source SHA-256.
- `data/raw/openfda/`: 42 new cached responses from `fetch_data.py expand` (new cited K-numbers change the query sets);
  `data/raw/manifest.json` updated. No existing cache file changed. Five responses that exploratory scripts wrote during
  this work, outside the fetch script, were deleted before the expand run.
- `data/audit/link_decisions.json` (new): 140 decisions, 9 of them revised after the independent review.
- `data/forebear.rl` and `data/build_report.json`: rebuilt offline. Numbers that moved, and why: recall events
  88058+88071 reach 22 later devices (was 19), 8 cleared after the recall (unchanged): K183226 leaves (it cites K083526
  only as a reference device) and four Trilogy-100 descendants recovered from predicate tables and OCR join; the
  design-recall watchlist has 114 devices, 66 with a direct predicate (was 106/62).

## Reproduce
From the repository root (Windows, PowerShell; stop the app first so the store is not locked):
```powershell
.venv\Scripts\python.exe scripts\audit_links.py          # offline: signals, decisions, eval\link_audit*.json
.venv\Scripts\python.exe scripts\build_graph.py          # offline: data\forebear.rl, data\build_report.json
.venv\Scripts\python.exe scripts\eval_extraction.py score
.venv\Scripts\python.exe -m pytest
```
Refreshing evidence (network; writes `data\raw` only through the fetch script):
```powershell
.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
.venv\Scripts\python.exe scripts\fetch_data.py ocr       # new image-only summaries only
.venv\Scripts\python.exe scripts\fetch_data.py expand    # after rule/OCR changes, before build_graph.py
.venv\Scripts\python.exe scripts\eval_extraction.py sample   # new seeded sample (relabel before scoring)
.venv\Scripts\python.exe scripts\llm_triage_experiment.py --max 30   # optional; needs NVIDIA_API_KEY in .env
```
