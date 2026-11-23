# Devpost submission checklist

For the maintainer, before the entry goes in. Check each item against the hackathon's own rules page: its deadline (with time zone), eligibility, video length, required technologies and judging criteria take precedence over this list.

## Repository

- [ ] **Judges can open the repo.** It is currently private (CodeQL and dependency review are skipped for that reason). Make it public, or grant access the way the rules require.
- [ ] **If it goes public**, re-run the Security workflow and check that CodeQL and dependency review pass. The README must not call a skipped run a pass.
- [ ] **`main` is green.** Backend, Frontend, Security and Hygiene badges at the top of the README.
- [ ] **Fresh-clone run.** Follow the [README walkthrough](../README.md#judge-walkthrough) on a clean machine or folder, by Docker and natively. <http://127.0.0.1:8765/api/health> returns `"ok": true` and [`#/check/K251770`](http://127.0.0.1:8765/#/check/K251770) shows depth 1 and depth 2 side by side.
- [ ] **No secrets.** `.env` is gitignored and gitleaks runs in CI. Keep `.env`, API keys and terminal history out of the video and screenshots.
- [ ] **Tag the submitted commit** so judges see exactly what was entered.

## Devpost fields

- [ ] **Story.** Lead with K251770: provisional "no design-recall signal" at one generation, **Review lineage** at two, because FDA lists the grand-predicates (not the DreamStation 2) on Class I recall Z-1974-2021. Then BreathePal (K252078) as the one-hop case.
- [ ] **Claims match the README.** Use the "Why Relate" wording. Do not say the recall can *only* be found with a graph: a person can find it by reading two PDFs and searching FDA's recall database. Relate makes it one parameterized query, with the evidence on every edge, run for every device.
- [ ] **Numbers come from the README's "Results, honestly" table**, including the no-go result for the investigation agent and "no human review yet".
- [ ] **Built with:** Relate (`relate-db` 1.0.2), Python 3.12, FastAPI, React, Vite, openFDA, plus the optional NVIDIA-hosted models (named in the README) and Claude Code.
- [ ] **Links:** repository, video, and the FDA PDF and recall links from the README tables.
- [ ] **Images.** Devpost galleries take raster images, so export `docs/assets/forebear-hero.svg` or use app screenshots.

## Video

- [ ] Opens on K251770 depth 1 vs depth 2 and the decision it changes; shows a quote opening the FDA PDF at its cited page.
- [ ] Shows or says the disclaimer: documented lineage and recall history, not regulatory advice or a safety finding.
- [ ] Within the rules' length limit; music and footage are yours or licensed for this use.

## Disclosures

- [ ] **AI assistance:** copy the README's [AI assistance](../README.md#ai-assistance-disclosure) section into the Devpost description, or link it, if the rules ask for disclosure.
- [ ] **Data and licensing:** link [third-party notices](../THIRD_PARTY_NOTICES.md). openFDA data is CC0; 510(k) summary text is written by manufacturers and is not claimed as public domain; FDA has not endorsed the project.
- [ ] **Pre-existing work:** if the rules restrict code written before the hackathon window, check the commit history against the window and say what came before.

## Facts and the tests that guard them

| Claim | Test |
| --- | --- |
| K251770 depth 1 and depth 2 verdicts, hops, quotes, Z-1974-2021 holders and the README query results | [`tests/test_two_hop_story.py`](../tests/test_two_hop_story.py) |
| K252078 → K113053 → Z-1957-2021 / Z-1958-2021 and the BreathePal evidence table | [`tests/test_story_facts.py`](../tests/test_story_facts.py), [`tests/test_shipped_evidence.py`](../tests/test_shipped_evidence.py) |
| Offline rebuild matches the shipped store | [`tests/test_reproducibility.py`](../tests/test_reproducibility.py) |

Run `.venv\Scripts\python.exe -m pytest` after any change to `data/` or the README's evidence tables.
