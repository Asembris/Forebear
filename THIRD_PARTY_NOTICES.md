# Third-party data, content and software

The [MIT License](LICENSE) covers the code and documentation written for Forebear. It does not cover the FDA material, manufacturer-authored text or third-party software described here, which keep their own terms. This file states what the repository contains and the terms its sources publish. It is not legal advice.

## FDA data

| What | Where in the repo | Published terms |
| --- | --- | --- |
| openFDA records: 510(k), device recall, enforcement and classification endpoints | `data/raw/openfda/`, and derived values in `data/forebear.rl` | openFDA dedicates its content and data to the public domain under [CC0 1.0](https://open.fda.gov/license/), with no warranty. Its [terms](https://open.fda.gov/terms/) ask for credit (not required) and the license asks users not to imply endorsement. |
| FDA-authored pages, such as 510(k) clearance letters and recall records on accessdata.fda.gov | Page text in `data/raw/summaries/`; links throughout the docs | FDA states that fda.gov content is not copyrighted and is in the public domain, "unless otherwise noted" ([website policies](https://www.fda.gov/about-fda/about-website/website-policies)). |

Data provided by the U.S. Food and Drug Administration (<https://open.fda.gov>). FDA has not reviewed or endorsed Forebear, and its warranties disclaimer applies to everything derived from these sources.

## 510(k) summary text written by manufacturers

A 510(k) summary is written by the company that submitted the device (21 CFR 807.92) and published by FDA. openFDA's terms note that some FDA-published data "may not be public domain", including copyrightable works that private entities gave to FDA. Forebear therefore **does not claim** that summary text is public domain.

- **What is included.** `data/raw/summaries/{K}.json` and `data/raw/ocr/{K}.json` hold the extracted text of each cached FDA PDF, page by page, with its URL and SHA-256. The PDFs themselves are not included. The Relate store, the example reports in `docs/investigations/` and the UI show short quoted excerpts with page numbers.
- **Why.** The text is there so that every predicate citation can be checked against its source and the graph can be rebuilt offline (`tests/test_reproducibility.py`). Each excerpt links back to FDA's copy of the PDF.
- **Rights.** Any rights in this text stay with its authors, and the MIT License does not apply to it. Rights holders who want their text removed from the cache can ask the maintainer through the repository. `scripts/fetch_data.py` regenerates the cache from FDA when a redistributable copy is not wanted.

## Names and trademarks

Device, company and product names (for example Philips Respironics, DreamStation, BiPAP, REMstar, SleepRes and BreathePal) appear only as identifiers taken from FDA records. They belong to their owners. Forebear is not affiliated with, or endorsed by, FDA or any company it names.

## Research cited

The README cites FDA's 2023 draft guidance on predicate selection and Kadakia et al., *JAMA* 2023 (PubMed 36625810). Only their findings are summarized; no text is reproduced.

## Software shipped in the repository

| Component | Where | License |
| --- | --- | --- |
| Inter variable font (via `@fontsource-variable/inter` 5.3.0) | `web/dist/assets/inter-*.woff2` | SIL Open Font License 1.1, [full text](docs/licenses/Inter-OFL-1.1.txt) |
| Newsreader variable font (via `@fontsource-variable/newsreader` 5.3.0) | `web/dist/assets/newsreader-*.woff2` | SIL Open Font License 1.1, [full text](docs/licenses/Newsreader-OFL-1.1.txt) |
| React and React DOM 18.3.1 | bundled into `web/dist/assets/index-*.js`; their license headers are kept in the bundle | MIT |

## Software installed, not redistributed

Python dependencies are installed from PyPI by `pip install -r requirements.txt` (or in the Docker build) and are not committed. They include `relate-db` 1.0.2 (Apache-2.0), FastAPI, Starlette, Uvicorn, Pydantic, httpx, pypdf, truststore, python-dotenv and the `openai` client, each under its own license. The optional OCR packages are listed in `requirements-ocr.txt`. The Relate CLI is not bundled: the README explains how to download it and check it against [`docs/relate-v1.0.2-SHA256SUMS.txt`](docs/relate-v1.0.2-SHA256SUMS.txt).
