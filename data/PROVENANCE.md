# Data provenance

All data is US federal government work, which is public domain in the US. It was fetched on 2026-11-16 with no API key.

| Source | Endpoint / URL pattern | What we keep | Where |
|---|---|---|---|
| openFDA 510(k) | `https://api.fda.gov/device/510k.json?search=product_code:{BZD,MNS,MNT,CBK}`, then `k_number:(... OR ...)` for cited predicates | Raw JSON responses, with bulky fields dropped (the `openfda` block, serial-number lists, addresses) | `data/raw/openfda/510k_*.json` |
| openFDA device recalls | `https://api.fda.gov/device/recall.json?search=product_code:...` and `k_numbers:(... OR ...)` | Same as above | `data/raw/openfda/recall_*.json` |
| openFDA enforcement reports | `https://api.fda.gov/device/enforcement.json?search=event_id:(...)` | Recall classification (Class I/II/III), joined on `recall_number` | `data/raw/openfda/enforcement_*.json` |
| openFDA classification | `https://api.fda.gov/device/classification.json?search=product_code:...` | Device class and regulation number | `data/raw/openfda/classification_*.json` |
| FDA 510(k) summary PDFs | `https://www.accessdata.fda.gov/cdrh_docs/pdf{YY}/{K}.pdf` | Text per page, source URL, SHA-256 of the PDF bytes, fetch time and status. The PDF itself is not kept. | `data/raw/summaries/{K}.json` |
| Recovered text of image-only summaries | Same PDF, downloaded again by `fetch_data.py ocr` and used only if its SHA-256 equals the recorded one | Local OCR text (RapidOCR, engine version, 300 dpi, per-page confidence), or for a PDF Portfolio the embedded summary PDF's text layer (attachment name and SHA-256) | `data/raw/ocr/{K}.json` |

Every cache file records `_fetched` (endpoint, query, time).

## Coverage of the four product codes
From `data/build_report.json`; 1,040 clearances in total:
- **533:** summary text layer read and at least one predicate found.
- **45 + 1:** image-only summary recovered (45 by OCR, 1 from a PDF Portfolio's embedded summary) and at least one predicate found (`ocr`, `attachment_text`).
- **38 + 22:** summary read (text layer / OCR) but no predicate citation found (`ok_no_predicate_found`, `ocr_no_predicate_found`). Treated as unknown lineage.
- **354:** a "510(k) Statement" was filed instead of a summary, so no predicates are public.
- **35:** no summary PDF online.
- **12:** cleared before 1996.

Another 147 out-of-family predicates carry metadata and recalls, but their own summaries were not read. Their lineage stops there unless someone ingests them.

Citations that could not become edges (cited K-number not in openFDA, or cleared after the citing device) are recorded on the citing device (`unresolved_citations`) instead of being dropped silently.

## Curated reviews
`data/reviews.json` holds 4 curated decisions on specific citation edges (K-number typos in the source PDFs), with evidence quoted; the reviewer is recorded only as `curated`. The build applies them after extraction.

## Extraction audit
`data/audit/link_decisions.json` holds the extraction-audit decisions on every flagged predicate link, each with quoted evidence. They were made by an AI agent reading the cached text, are stored in the edges' `audit*` properties (never in the human review fields) and are overridden by any human review. Method and results: `docs/EVIDENCE_QUALITY.md`.

## Live data
Anything the running app fetches (via "Add a clearance") goes to `data/live/`, which is gitignored and never read by the build.

## Rebuild
- **Offline, from the cache.** `python scripts/build_graph.py`. It is deterministic and never calls the network (a cache miss is an error); `tests/test_reproducibility.py` checks it.
- **Refresh from FDA.** Delete `data/raw` and run `python scripts/fetch_data.py metadata`, then `summaries`, then `ocr` (needs `requirements-ocr.txt`), then `expand`, then `build_graph.py`. Run `expand` again whenever the extraction rules or the OCR cache change.
