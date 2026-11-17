# Forebear

**Check a device's 510(k) ancestry before you cite it.**

Forebear reads predicate citations out of FDA 510(k) summaries and stores the medical-device family tree in a Relate graph, joined to FDA recall records. One query then shows whether a candidate predicate, or any of its ancestors, was recalled for a design problem, with the page and quote behind every link.

- **Why it matters.** FDA's 2023 draft guidance recommends choosing predicates not subject to design-related recalls. Kadakia et al. (JAMA 2023) found devices cleared on predicates with Class I recalls were associated with a 6.4× higher risk of their own Class I recall.
- **Why the existing tools fall short.** FDA's own databases answer one hop at a time.

> Status: **working prototype** (hackathon vertical slice).

## Run it (Windows, PowerShell)
Prerequisites: Python 3.12. Node 18+ is only needed if `web/dist` is missing; the build is committed.

```powershell
git clone https://github.com/Asembris/Forebear.git
cd Forebear
git config core.hooksPath .githooks              # activates the one-line commit-message check
Copy-Item .env.example .env                      # optional: only needed for LLM triage
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

This opens <http://127.0.0.1:8765>. The script:
- creates `.venv`;
- installs the pinned `requirements.txt`;
- rebuilds `data\forebear.rl` offline if it is missing;
- starts the server.

Manual equivalent:
```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\build_graph.py        # optional: store is shipped; rebuild is offline, ~2 s
.venv\Scripts\python.exe -m uvicorn forebear.api:app --port 8765
```

The rebuild reproduces the same graph and counts, but the `.rl` bytes and `data\build_report.json` timings differ, so Git shows them as modified. Run `git restore data\forebear.rl data\build_report.json` to return to the shipped store.

Frontend (only when changing the UI; Node 18+):
```powershell
cd web; npm ci; npm run build; cd ..
```

Tests (extraction and adversarial rules, OCR provenance, audit decisions, uncertainty rules, recall links, graph, verdict rules, ingest and rollback, API journey, BreathePal evidence chain, security, MCP, offline rebuild; the Relate-CLI MCP test is skipped if `tools\relate.exe` is absent):
```powershell
.venv\Scripts\python.exe -m pytest
```

## Try this (90 seconds)
1. **The story.** On the start page, click **K252078 BreathePal Bilevel (2026)**:
   - Verdict: **Review lineage**.
   - Its predicate, BiPAP A30 (K113053), is named on pages 5, 6 and 7 of the summary.
   - K113053 carries the June 2021 Philips PE-PUR foam recall records (Class I, root cause "Device Design").
   - The timeline shows the recall diamonds sitting *before* BreathePal's clearance date.
2. **The evidence.** Expand a signal to see the citation chain, the quoted summary text with a PDF link, and each FDA recall record.
3. **Writes.** Click **Save assessment to graph**. Then, under *What K252078 cites*, reject the edge: the lineage and verdict change immediately, and the saved assessment is marked **stale**. Restore the edge.
4. **Recall reach.** Open the tab and trace `88058,88071` (the Philips recall; openFDA files it as two events). Result: 14 recalled clearances; 25 later devices descend from them; 8 of those were cleared after the recall on their own lineage began.
5. **Live update.** In **Add a clearance**, enter an out-of-family ancestor (dashed node) to read its summary from FDA and extend the tree. This needs internet.

## Investigation agent (Phase 2)
An NVIDIA-hosted LLM investigates one device by calling Forebear's graph tools step by step (check the lineage, trace
ancestors, open recall records, verify each citation against the cached FDA PDF text, list coverage gaps), then submits
findings. Every finding is checked against what the tools returned; the conclusion and all recall counts in the
report are computed from the graph, not by the model. The agent cannot review or change lineage links or fetch FDA
documents: it can only propose, and a named person decides. Runs, tool traces, findings and proposals are stored in
Relate. Without NVIDIA inference, a labelled deterministic checklist runs instead. Details, safety boundaries and the
real runs: `docs\INVESTIGATION_AGENT.md`.

Needs `NVIDIA_API_KEY` and `NVIDIA_BASE_URL` in `.env` (see `.env.example`); optional `FOREBEAR_AGENT_MODELS`.

Command line (stop the app first, or use `--copy` to work on a copy under `data\live`):
```powershell
.venv\Scripts\python.exe scripts\investigate.py --copy "Investigate K252078, trace recalled predicates, verify the original FDA evidence, identify unresolved lineage, and prepare a documented due-diligence report."
.venv\Scripts\python.exe scripts\investigate.py --copy --k K201620 --mode deterministic "Investigate K201620"
```
It prints each model turn and tool call, then writes the report to `data\live\investigations\<id>.md` and `.json`.

HTTP API (app running on port 8765):
```powershell
$r = Invoke-RestMethod -Method Post http://127.0.0.1:8765/api/investigations -ContentType application/json -Body '{"request": "Investigate K252078 and its recalled predicates", "k": "K252078", "depth": 4}'
Invoke-RestMethod http://127.0.0.1:8765/api/investigations/$($r.id)                    # status and progress
Invoke-RestMethod http://127.0.0.1:8765/api/investigations/$($r.id)/trace              # tool calls (?results=true for outputs)
Invoke-RestMethod "http://127.0.0.1:8765/api/investigations/$($r.id)/report?format=markdown"
Invoke-RestMethod http://127.0.0.1:8765/api/proposals?status=pending_human_decision      # agent proposals awaiting a person
```
Other endpoints: `GET /api/investigations?k=K113053` (runs that examined a device, with a `stale` flag),
`GET /api/investigations/{id}/findings`, `POST /api/investigations/{id}/resume`, and
`POST /api/proposals/{id}/decision` with `{"decision": "approve"|"dismiss", "reviewer": "<your name>", "human": true}`.

Agent tests (scripted model, no network): `.venv\Scripts\python.exe -m pytest tests\test_investigation.py tests\test_investigation_api.py tests\test_bounded_results.py`

## How it uses Relate
- **Mode: single file** (`data/forebear.rl`, about 4 MB, committed).
  - It can be inspected directly, travels with the repo, and rebuilds deterministically from `data/raw/`.
  - The API is the single writer; the connection is pinned to one thread.
- **What the graph models.**
  - Nodes: `Device`, `Recall`, `ProductCode`, `Company`, `Assessment`.
  - `(:Device)-[:CITES {kind, page, snippet, review, ai_label}]->(:Device)` is the predicate genealogy, with evidence.
  - `(:Device)-[:SUBJECT_OF]->(:Recall)` attaches recalls.
  - `(:Assessment)-[:ASSESSED|FLAGGED]->` holds saved decisions.
  - `(:Investigation)-[:INVESTIGATES|EXAMINED|RAN|FOUND|PROPOSED|RESUMES]->` holds agent runs, their tool calls
    (`ToolCall`), machine findings (`Finding`, never human-approved) and proposals awaiting a person (`Proposal`).
- **What Relate does at run time.**
  - Variable-length Cypher walks ancestors and descendants (`[:CITES*1..N]`) with a per-edge rule that honours human review.
  - Recalls are joined on every ancestor.
  - Date comparisons find "cleared after the predicate was recalled".
  - A full-text index serves device search.
  - A stale-assessment query flags saved assessments whose ancestry was reviewed, AI-labelled or re-ingested after they were saved.
  - MERGE-based incremental ingest.
  - Review, AI-triage and assessment writes all change the next query's answer.
- **Agents (MCP).**
  - **Live tools:** `forebear` runs `python -m forebear.mcp_server` and talks to the running API. Tools: `check_predicate`, `compare_predicates`, `recall_reach`, `list_citations`, `ingest_clearance`, `review_citation`, `save_assessment`, `investigate`, `get_investigation`.
  - **Raw Cypher, read-only:** Relate's own server, `relate serve --database data\forebear.rl --mcp stdio --read-only`. The `.rl` file is locked while the app runs, so use it with the app stopped, or on a copy.
  - Both are configured in `.mcp.json` (Claude Code format).
  - The Relate CLI is not bundled. Download `relate-windows-amd64.exe` v1.0.2 from <https://github.com/relatedb/relate/releases>, verify it against `docs\relate-v1.0.2-SHA256SUMS.txt` (`Get-FileHash`), and save it as `tools\relate.exe`.

## Where the data lives
- `data/forebear.rl`: the Relate store.
- `data/raw/`: cached openFDA JSON and summary text with URL and SHA-256. Provenance is in `data/PROVENANCE.md`.
- `data/build_report.json`: counts and extraction statistics.
- `data/reviews.json`: human review decisions, applied by the build through the same review write the UI and MCP use; each must name the person (none yet). Four earlier AI-generated decisions that had been labelled "curated human review" are kept there for the record under `ai_generated_not_applied` and are not applied.
- `data/audit/link_decisions.json`: extraction-audit decisions on flagged predicate links (error / not_predicate / variant / unresolved, with verified corrections). Made by an AI agent, stored apart from human review, overridden by any human review. See `docs/EVIDENCE_QUALITY.md`.
- `data/raw/ocr/`: text recovered from the 68 image-only summaries (local OCR, or a PDF Portfolio's embedded summary), each checked against the PDF's recorded SHA-256.
- `data/live/` (gitignored): anything fetched by live ingest in the app. The committed `data/raw` is only written by `scripts/fetch_data.py`.
- `eval/`: extraction audit and evaluation outputs (`link_audit.json`, `link_audit_queue.json` = links awaiting a person, `extraction_eval*.json`, `llm_triage_experiment.json`).

Dataset: four FDA product codes for respiratory devices (CPAP/BiPAP: BZD; ventilators: MNS, MNT, CBK).
- 1,040 clearances, plus 147 out-of-family predicates.
- 1,229 predicate links, 123 reference-device links, 244 ambiguous mentions.
- Every predicate link flagged by the name or FDA-panel check has an audit decision: 13 verified K-number errors (removed from lineage, 12 with a verified correction), 8 non-predicates, 98 naming variants, and 21 unresolved links that are kept, flagged and listed for a person. Evidence quality, methods and remaining limits: `docs/EVIDENCE_QUALITY.md`.
- 563 recall records.

## AI and third-party tools (disclosure)
- **LLM (optional).** NVIDIA-hosted `nvidia/nemotron-3.5-lightning-30b-a3b`, falling back to `mistralai/mistral-large-4-1t-a52b`. Used only to label *ambiguous* citation mentions, on request. Its output must quote the snippet verbatim or it is discarded, and humans can override it.
  - The LLM is **not** used for verdicts, notes or the extraction audit. In testing it miscounted recalls, and on hard citation cases it agreed with the audit 5 times in 28 (`eval/llm_triage_experiment.json`). A link made a predicate only by the LLM counts as uncertain evidence in assessments.
  - Set `NVIDIA_API_KEY` and `NVIDIA_BASE_URL` in `.env` to enable it. Everything else works without it.
- **Investigation agent (optional).** NVIDIA-hosted `nvidia/nemotron-3-ultra-550b-a55b`, falling back to `mistralai/mistral-large-4-1t-a52b`, chosen by a bounded tool-calling probe (`docs/INVESTIGATION_AGENT.md`). It chooses which tools to call and writes findings; it does not produce verdicts or counts, its findings are verified against tool results (unsupported ones are shown as rejected), and it cannot change lineage.
  - The verdicts, the note and the extraction audit stay deterministic as described above.
- **Libraries.** FastAPI, Uvicorn, pypdf, httpx, React 18, Vite. Optional for refreshing the OCR cache: RapidOCR (ONNX) and pypdfium2 (`requirements-ocr.txt`).
- **Built with.** Claude Code (an AI coding assistant) wrote most of the code and docs under the team's direction.

Not regulatory advice. Forebear reports documented lineage and recall history; it does not judge device safety.
