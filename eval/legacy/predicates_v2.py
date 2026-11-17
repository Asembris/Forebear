"""Deterministic predicate extraction from 510(k) summary text.

510(k) summaries are often OCR'd scans, so K-numbers appear as "K(113068)", "K1 31982",
"KI12345" or "K 07l234". We normalise those, then classify each mention by its context:

  predicate  - the mention sits in a "Predicate Device(s)" section or near the word
               "predicate" / "substantially equivalent to"
  reference  - the mention is labelled a "reference device" (cited for a specific
               characteristic, not as the legal predicate)
  mention    - any other K-number in the summary body (kept, low confidence)

Every hit keeps the page number and a text snippet, so the UI can show *why* an edge exists.
The extractor never invents K-numbers: anything that does not resolve to a real openFDA
510(k) record, or that was cleared *after* the citing device was received, is discarded
later in graph building (see build_graph.py) and counted in the build report.
"""
from __future__ import annotations

import re

# K + optional bracket/space noise + six digit-like characters (OCR: O->0, I/l/|->1, S->5 not used)
K_PATTERN = re.compile(r"(?<![A-Za-z0-9])[K][\s\(\[#:]{0,3}((?:[0-9OIl]\s?){5}[0-9OIl])(?![0-9])")
OCR_MAP = str.maketrans({"O": "0", "I": "1", "l": "1"})

# Strong predicate labels. "substantially equivalent" is only a weak cue (see _classify).
PRED_HEAD = re.compile(r"predicate|legally\s+marketed|identical\s+to|modification\s+(?:of|to)|"
                       r"modified\s+(?:version|device)|previously\s+cleared", re.I)
WEAK_PRED = re.compile(r"substantial(?:ly)?\s+equivalen", re.I)
# Reference-device labels, incl. table headings ("Reason for Reference") and "Reference: K..."
REF_HEAD = re.compile(r"reference\s+(?:device|predicate)|referenced\s+device|reason\s+for\s+reference|"
                      r"\breference\s*:|\bthe\s+reference\b", re.I)
REF_SECTION_CHARS = 700     # a "Reference Device(s)" heading stays in force this far (reference tables)
PRED_LABEL_CHARS = 220      # a predicate label must be this close
WEAK_CHARS = 150            # "substantially equivalent to X (K...)" must be in the same sentence-ish span
# boilerplate that should not count: FDA letter header / form header showing the device's own number
SELF_HEAD = re.compile(r"510\(k\)\s*(?:number|no\.?|#)|submission\s+number|\bre:\s*$|page\s+\d", re.I)


def normalise(raw: str) -> str | None:
    digits = raw.replace(" ", "").translate(OCR_MAP)
    return "K" + digits if re.fullmatch(r"\d{6}", digits) else None


def _last_end(pattern: re.Pattern, text: str) -> int:
    return max((m.end() for m in pattern.finditer(text)), default=-1)


def _classify(before: str, after: str) -> tuple[str, float]:
    """`before` is up to REF_SECTION_CHARS of page text preceding the K-number."""
    sect = before[-REF_SECTION_CHARS:]
    off = len(before) - len(sect)
    last_ref = _last_end(REF_HEAD, sect)
    last_pred = _last_end(PRED_HEAD, sect)
    # Section rule: the most recent label wins, and a reference heading persists over a long table
    # ("Predicate Device: X - K1 ... Reference Devices / Reason for Reference ... K2" -> K2 reference).
    # "reference predicate" matches both patterns and ends at the same place: reference.
    if last_ref >= 0 and last_ref >= last_pred:
        return "reference", 0.6
    if last_pred >= 0 and (len(sect) - last_pred) <= PRED_LABEL_CHARS:
        return "predicate", 0.9
    weak = _last_end(WEAK_PRED, sect)
    if weak >= 0 and (len(sect) - weak) <= WEAK_CHARS:
        return "predicate", 0.6
    if re.search(r"predicate", after[:80], re.I):
        return "predicate", 0.8
    if REF_HEAD.search(after[:60]):
        return "reference", 0.6
    return "mention", 0.4


EXPLICIT_CHARS = 60          # a label this close before the number is an explicit label


def _explicit(before: str, kind: str) -> bool:
    """True when the classifying label sits right before the number, e.g. "Reference Devices: K..."
    or "Predicate Device: X (K..." - such labels outrank anything inferred elsewhere in the summary."""
    tail = before[-EXPLICIT_CHARS:]
    if kind == "reference":
        return bool(REF_HEAD.search(tail))
    if kind == "predicate":
        return bool(PRED_HEAD.search(tail))
    return False


def extract_from_summary(rec: dict, self_k: str) -> list[dict]:
    """Return one record per distinct cited K-number.

    A K-number often appears several times (header table, comparison table, conclusion). The
    occurrence with an explicit label wins; among equals, predicate > reference > mention."""
    best: dict[str, dict] = {}
    rank = {"predicate": 3, "reference": 2, "mention": 1}
    for page_no, text in enumerate(rec.get("pages", []), 1):
        for m in K_PATTERN.finditer(text):
            k = normalise(m.group(1))
            if not k or k == self_k:
                continue
            before, after = text[max(0, m.start() - REF_SECTION_CHARS):m.start()], text[m.end():m.end() + 200]
            if SELF_HEAD.search(before[-40:]) and not PRED_HEAD.search(before[-120:]):
                kind, conf = "mention", 0.3
            else:
                kind, conf = _classify(before, after)
            explicit = _explicit(before, kind)
            snippet = " ".join((before[-160:] + text[m.start():m.end()] + after[:80]).split())
            hit = {"k": k, "kind": kind, "confidence": conf, "page": page_no, "explicit": explicit,
                   "raw": m.group(0), "snippet": snippet}
            cur = best.get(k)
            key = (explicit, rank[kind], conf)
            if cur is None or key > (cur["explicit"], rank[cur["kind"]], cur["confidence"]):
                best[k] = hit
    return sorted(best.values(), key=lambda h: (-rank[h["kind"]], h["k"]))
