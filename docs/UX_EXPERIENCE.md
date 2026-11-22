# Forebear UX: "The Invisible Thread"

Phase 4 replaces the web UI with a cinematic opening and an evidence-first investigation workspace. The FastAPI backend,
the Relate store, the graph data and the verdict rules are unchanged. Two backend-side changes were made. One is a new
test, `tests/test_story_facts.py`. The other adds fields to `/api/watchlist` without changing any existing field: a
row-level `conditional`, `supported_min_gen` and `recall_count`, plus top-level `direct_supported` and `conditional`.
They are computed over every recall route, rather than the six the row lists.

## The idea

A 510(k) clearance names its predicate on one page of one PDF. The question that matters, whether that predicate or its
ancestors were later recalled for a design problem, is invisible from that page. The thread between documents is the
product. The opening shows one real thread, and then hands that same thread to the workspace.

**Visual language.** One world in two registers. The film is unhurried and spacious. The workspace is dense and exact.
Both use the same palette, nodes, threads and evidence hierarchy:

| Token | Role |
| --- | --- |
| Midnight navy `#0b1322` | Ground. Everything sits in the same night. |
| Warm ivory `#f1ebdd` / paper `#f6f1e5` | Text and evidence. Every quote from an FDA PDF is set on paper, in a serif, with a blue rule. |
| Evidence blue `#7fa2ff` | The thread: citations, links, focus. |
| Restrained amber `#e7a948` | The past. It is used only for recalls and the chain they raise, never for decoration. |
| Violet `#b7a4f5` | Conditional routes, which depend on an unresolved citation. |
| Sage / brick | Confirmed by a person / disputed evidence. |

**Type.** Newsreader (variable serif) for statements, verdicts and quotes, because it reads like a document. Inter for the
interface. A monospace face with tabular, slashed numerals for K-numbers and recall ids. Fonts are bundled with the build
(`@fontsource-variable/*`), so the app still works offline.

**Mark.** An "F" drawn as a lineage graph (`web/src/brand/Mark.jsx`). The stem is a chain of generations, the arms are
citations, and the foot node, the oldest ancestor, is amber. The same geometry is used by the opening, the header and
the favicon.

## User journey

1. **Opening, about 3 s** (`web/src/film/Intro.jsx`). The mark assembles node by node, then thread by thread. The
   wordmark rises, and the line *Every clearance has a past* is set. The lockup then dissolves, and the film's field
   blooms out from where the mark stood. It plays once per tab session, and only on the landing page. Skip, Escape,
   Enter, Space or a click ends it at once. It never plays under reduced motion or in front of a deep link. Nothing
   loads behind it. "Replay" in the footer and "Replay the film" in the workspace bring it back.
2. **Hero.** The value in one sentence, live counts from the store (clearances, predicate links, recall records), and two
   paths: *Investigate K252078* goes straight to the workspace, and *Follow one thread* starts the film.
3. **Scroll film** (`Landing.jsx`, `renderer.js`). Three chapters over one fixed canvas:
   - **01 The filing.** One summary PDF, one highlighted line. The real quote from page 6 of K252078's summary, with a
     link to that page of the FDA PDF.
   - **02 The connection.** The thread is born at the highlighted line and travels back to K113053 (BiPAP A30, 2012)
     along a time ruler. Then K113053's own predicates appear.
   - **03 The discovery.** A diamond marks the Class I, Device Design recall that began on 14 Jun 2021, on the
     predicate's life line. Amber travels back along the thread to the 2026 clearance. The grand-predicates with
     design-related recalls light up too. The copy says plainly that a predicate recall is a question for the predicate
     rationale, not a finding about the new device.
4. **Handoff.** The lineage settles into the workspace's own generation-column layout (newest on the right). *Open the
   investigation* moves to `#/check/K252078` through a View Transition crossfade, where browsers support one, and the
   same graph is waiting in the same arrangement.
5. **Workspace** (`web/src/workspace/`). The rest of this document.

### The investigation page, top to bottom

- **Finding.** The device, the verdict, and an authority note: *Deterministic assessment · forebear-rules-v4.
  Authoritative within its documented scope … A documentation signal, not a safety determination.* Below it, one
  plain-language finding sentence, built only from the assessment payload. It names the page, the recall class, the root
  cause, the start date, and how long before the clearance the recall began. Coverage chips show evidence completeness,
  ancestors, unread summaries, doubtful links, conditional signals, and a jump link to the review queue.
- **Critical chain.** The route that raised the verdict, as cards joined by status-coded threads. Each card and each
  thread opens its provenance.
- **Evidence graph.** Generation columns that fit the panel width. Status-coded threads, and nodes coloured by recall
  status. Progressive disclosure: the verdict window (two generations) plus every node on a review-raising chain is shown
  first, and "+N more in generations 3–4" expands the rest. "Show later devices" adds descendants. A *Timeline* mode
  keeps the original recall-diamonds-against-clearance-date chart. Every node and every thread is a focusable button
  (Tab, then Enter). Hovering a node or a review item traces its route.
- **Provenance drawer** (`Provenance.jsx`). For a thread: its status and the exact reasons for it, the verbatim quote
  with the cited K-number highlighted, a paper card that opens the **original FDA PDF at the cited page**
  (`…/K252078.pdf#page=6`), and the source and extraction record (text layer or OCR, method, confidence, name and panel
  checks, audit note, reviewer, PDF SHA-256). Confirm and Reject buttons write to the graph. For a device: its record,
  route, links to FDA, and every recall record, with a count of how many began before the candidate's clearance. FDA
  serves its PDFs with `X-Frame-Options: SAMEORIGIN`, so they cannot be embedded; the page link opens them in a new tab.
- **What needs human review** (`Review.jsx`). Each uncertainty signal becomes three answers: **Conflict**, **Why it
  matters** and **Next step**, with working actions (open the thread, read a summary live, open the FDA recall records).
  The explanations restate what each rule in `forebear/lineage.py` measures. They add no new claim.
- **Recall signals**, **What it cites** (review and optional LLM triage), **Due-diligence note** (template memo; save
  with an inline analyst note), and **Investigation history**. History lists saved assessments with staleness first. Agent
  runs follow, labelled *optional · machine findings, never human-approved · the verdict does not depend on them*.

### Thread statuses (one grammar everywhere)

`web/src/evidence.js` mirrors `lineage.doubt()` exactly, so the UI never invents a status:

| Status | Rule | Line |
| --- | --- | --- |
| Confirmed | A person confirmed it (an MCP-client confirmation does not count) | sage, solid |
| Machine-extracted | Read from summary text, validated, not reviewed | blue, solid |
| Disputed | Name mismatch, different FDA panel, audit-corrected K-number, or LLM-only label | brick, dashed |
| Conditional | The audit could not resolve the citation | violet, dotted |
| Rejected | Removed by a reviewer; it no longer counts in any lineage query | faint, dashed |

**Conditional recall paths** are violet everywhere they appear. In assessments, a signal is marked *conditional*, and its
review item says what to confirm. In **recall reach**, a descendant whose every route runs through an unresolved citation
gets a violet row rule and chip, holders reached only that way are tinted, and a fourth headline count shows how many.
In the **watchlist**, the API marks a row conditional when none of its recall routes is supported. Conditional rows are
marked and counted, and can be filtered (*Supported routes* / *Conditional only*). Their ancestor is labelled *cited
device · citation unresolved*, never *direct predicate*. The headline direct-predicate count includes only supported
routes. When a signal is conditional, the finding sentence and critical chain call the holder a *cited device* reached
through an unresolved citation, and they prefer a supported chain when one exists.

### Other views

Compare, Recall reach, Watchlist, Add a clearance, History (assessments, agent runs, and proposals awaiting a named
person's decision) and Method (the verdict rules, thread statuses, the agent's secondary role, and how Relate is used).
All old hash links still resolve, including `#/check/K…`, `#/compare/…`, `#/reach/…`, `#/watch`, `#/ingest/…` and
`#/about`, which now maps to Method.

## Engineering

- **Two layers, one loop, no Three.js.** The film is lazy-loaded with the landing page and draws two fixed canvases
  from one rAF loop.
  - **The field** (`field-gl.js`) is raw WebGL2 with no library. It draws a moving nebula with film grain, about 1,200
    bright clearance-points (the store's device count) and 4,600 dust points drifting through a flow field, links between
    neighbours, and about 900 signals travelling along those links. It also draws a pointer lamp and an amber recall
    shockwave that pushes and tints the field. All motion is computed in shaders from uniforms, so nothing is uploaded
    per frame.
  - **Fallback.** Weak or software GPUs (`failIfMajorPerformanceCaveat`, a SwiftShader/llvmpipe check) and a lost
    context fall back to a lighter Canvas2D field. `?gl=1` forces WebGL for testing.
  - **The story** (`renderer.js`) is Canvas2D on top: the real lineage, the thread with its travelling year readout and
    comets, the recall diamond, and the measured gap. Labels are chips at a constant screen size, so they stay legible
    at every zoom.
  - **Framing.** Every scene is fitted into the space its chapter's copy leaves free; the copy's position is measured in
    the document. Picture and words cannot collide at any viewport.
  - **Phones** get a vertical schematic: newest at the top, dates labelled, and no compressed ruler pretending to be to
    scale. A scene plays while its copy rises from below.
  - **Scroll timing.** Scene time follows a closed-form, critically damped spring anchored to the chapters. `dt` is
    clamped, the loop pauses while the tab is hidden, and scroll is never hijacked.
  - **Re-renders.** Scene changes update only the readout and chapter index, through an external store, never the whole
    page.
- **Dossier framing.** A fine grid, numbered chapters (`01 / 03`), a mono scene readout (`[02 / 04] THE CONNECTION
  K252078 → K113053 · 2026 → 2012 · webgl field · illustrative`), and corner marks on evidence. In the workspace, amber
  signals travel along the critical chain, in both the graph and the chain strip, so the film's language continues into
  the product. Reduced motion stops all of it.
- **Honest content.** Every node, date, page, quote and recall id in the film comes from `web/src/story/facts.json`, and
  `tests/test_story_facts.py` checks each value against the shipped Relate store. That test caught three wrong
  grand-predicate dates while this phase was being built. The background field is labelled illustrative; its point
  count is the store's device count.
- **Never in the way.** Deep links skip the film. Reduced motion removes the opening and the canvas, and shows every
  word in reading order. If no 2D canvas is available, a static SVG still with all controls is used instead. There is a
  skip link, keyboard-operable graph nodes and threads, a `/` shortcut and arrow keys in search, a focus-trapped drawer
  with Escape, and visible focus rings. Layouts are responsive, from a 232 px rail on desktop to a scrolling tab bar and
  stacked panels on phones.
- **Code splitting.** The workspace shell is in the main chunk. The landing page, renderer, secondary views and history
  are separate lazy chunks.

## Independent review

A separate reviewer audited the branch for design, usability, evidence honesty and regressions. Each finding was fixed:

- **Conditional wording.** A conditional route was called "that predicate" / "Direct predicate". It is now a *cited
  device · citation unresolved*, and a supported chain is preferred.
- **Watchlist flag.** The conditional flag was inferred from a truncated list. It is now computed by the API over every
  route (see above).
- **Contrast.** Small text, including the safety disclaimer, was below WCAG AA. Muted text is now at least 5:1.
- Non-predicate citations no longer show a lineage status; they show *Not a lineage link*.
- The *Compare* entry point is restored on the investigation page.
- The film reads its page number from `facts.json`.
- The opening is a modal dialog, the page behind it is `inert`, and focus moves to the hero when it ends.
- Overclaiming copy is softened. The hero now says "as far back as their summaries can be read", the discovery chapter
  says "FDA recalls name the predicate", and the handoff says "Every fact above is real evidence".
- `doubt()` now matches `kind == ""`.
- Replay is hidden under reduced motion.
- Out-of-order search responses are dropped.
- In-page film anchors no longer parse as workspace routes.
- The mobile tab bar fades at its edge, so it reads as scrollable.

## Verification (this phase)

- `pytest`: 250 passed, including the 4 new story-fact checks and the new watchlist assertions.
- `npm run build`: passes.
- Playwright (`cd web; npm run test:e2e`): 37 passed. The suite starts the real API on a throwaway copy of the store
  (`web/e2e/serve.mjs` → `data/live/e2e.rl`), so its reviews and saved assessments never touch `data/forebear.rl`. It
  covers the opening (once per session, about 3 s, Skip, Escape, replay), deep links, the canvas film and its chapter
  index, the handoff, reduced motion, the finding and critical chain, keyboard access to provenance with the `#page=6`
  PDF link, node recall records, conditional-route wording (K120562), progressive disclosure, the two-canvas film with its scene readout, forced WebGL without page errors, a reject → verdict change → restore write, saving an assessment
  into history, search, recall reach, the watchlist conditional filter, and compare. Overflow and screenshot checks run
  at desktop 1440×900, tablet 820×1180 and mobile (Pixel 7). Screenshots are written to `web/test-results/shots/`
  (gitignored).
- Film frame times while scrolling the whole page (160 steps) on the real GPU (GTX 1660, ANGLE D3D11, WebGL path) at
  1920×950: median 16.7 ms and p95 16.7–16.8 ms. Two warm runs had no frame over 33 ms. The cold first run had two
  33 ms frames (one dropped frame each).
  - Before two fixes, the cold run had frames of up to 50 ms where the header turned solid. The fixes were removing a
    full-screen backdrop blur over the canvas, and keeping scene changes out of the page's React state.
  - The Canvas2D fallback measured median 16.7 ms with no frame over 33 ms at 1440×900 and 390×844 in software-rendered
    headless Chromium.

## Known limitations

- FDA PDFs cannot be embedded (`SAMEORIGIN`), so a page opens in a new tab rather than inline.
- The watchlist still lists at most 6 recall routes per row, as before. The row-level flags are computed over all of them.
- The View Transition crossfade from the film to the workspace needs a browser with `document.startViewTransition`.
  Elsewhere the switch is an instant cut.
- The film tells one fixed, verified case (K252078). It is not generated per device.
- WebGL frame times were measured on one desktop GPU. Phones get a reduced field (about 2,200 points) and a 1.5× pixel
  ratio cap, but were checked only in emulation.
- The workspace is dark only, by design.
