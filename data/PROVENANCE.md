# Data provenance

All data is US federal government work, which is public domain in the US. It was fetched on 2026-11-16 with no API key.

| Source | Endpoint / URL pattern | What we keep | Where |
|---|---|---|---|
| openFDA 510(k) | `https://api.fda.gov/device/510k.json?search=product_code:{BZD,MNS,MNT,CBK}`, then `k_number:(... OR ...)` for cited predicates | Raw JSON responses, with bulky fields dropped (the `openfda` block, serial-number lists, addresses) | `data/raw/openfda/510k_*.json` |
| openFDA device recalls | `https://api.fda.gov/device/recall.json?search=product_code:...` and `k_numbers:(... OR ...)` | Same as above | `data/raw/openfda/recall_*.json` |
| openFDA enforcement reports | `https://api.fda.gov/device/enforcement.json?search=event_id:(...)` | Recall classification (Class I/II/III), joined on `recall_number` | `data/raw/openfda/enforcement_*.json` |
| openFDA classification | `https://api.fda.gov/device/classification.json?search=product_code:...` | Device class and regulation number | `data/raw/openfda/classification_*.json` |
| FDA 510(k) summary PDFs | `https://www.accessdata.fda.gov/cdrh_docs/pdf{YY}/{K}.pdf` | Text per page, source URL, SHA-256 of the PDF bytes, fetch time and status. The PDF itself is not kept. | `data/raw/summaries/{K}.json` |

Every cache file records `_fetched` (endpoint, query, time).

## Coverage of the four product codes
From `data/build_report.json`; 1,040 clearances in total:
- **527:** summary text read and at least one predicate found. These are the devices whose predicates are known.
- **44:** summary text read, but no predicate citation found (`ok_no_predicate_found`). Treated as unknown lineage.
- **354:** a "510(k) Statement" was filed instead of a summary, so no predicates are public.
- **68:** the summary is an image-only scan with no text layer (not OCR'd yet).
- **35:** no summary PDF online.
- **12:** cleared before 1996.

Another 130 out-of-family predicates carry metadata and recalls, but their own summaries were not read. Their lineage stops there unless someone ingests them.

## Curated reviews
`data/reviews.json` holds human decisions on specific citation edges, with evidence quoted (currently 4 K-number typos in the source PDFs). The build applies them after extraction.

## Live data
Anything the running app fetches (via "Add a clearance") goes to `data/live/`, which is gitignored and never read by the build.

## Rebuild
- **Offline, from the cache.** `python scripts/build_graph.py`. It is deterministic; `tests/test_reproducibility.py` checks it.
- **Refresh from FDA.** Delete `data/raw` and run `python scripts/fetch_data.py metadata`, then `summaries`, then `build_graph.py`.
