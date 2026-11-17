"""Deterministic evidence checks for an extracted citation edge.

Each check compares what the 510(k) summary text says about a cited K-number with the cited
device's own openFDA record. None of them decides anything on its own: they produce signals
that the extraction audit (scripts/audit_links.py) and the lineage rules read.

  name_check(...)    does the cited device's FDA name appear in the text that names it?
  panel_check(...)   is the cited device reviewed by the same FDA advisory panel?
  local_span(...)    the slice of page text that names one K-number in a list or table
  neighbour_ks(...)  K-numbers one digit or one adjacent transposition away (typo candidates)
  sentence_start(...) where the last sentence of a text begins (abbreviation-aware)
"""
from __future__ import annotations

import re

NAME_CHECK_METHOD = "name-check-v2"

# Generic words that do not identify a product.
GENERIC = set("""system systems device devices ventilator ventilators ventilatory mask masks cpap bipap series
model models unit units with and the for positive airway pressure nasal full face heated humidifier humidifiers
therapy respiratory breathing circuit circuits kit kits accessory accessories oral interface auto plus portable home
non continuous vented sleep apnea medical inc corp ltd llc company support option options modification modified
software new version size sizes reusable disposable single patient use multi adult pediatric infant neonatal
care total ventilation invasive noninvasive data module management connection tubing tube number numbers
product products type types""".split())
_GENERIC_LONG = [g for g in GENERIC if len(g) >= 5]

_BOILER = re.compile(r"\b8\d\d\.\d{3,4}\b|(?<![A-Za-z0-9])K\s?[\dOIl]{2}\s?[\dOIl\s]{4,6}|\b(?:19|20)\d\d\b")
_K_ANY = re.compile(r"(?<![A-Za-z0-9])K[\s\(\[#:]{0,3}(?:[0-9OIl]\s?){5}[0-9OIl](?![0-9])")
_SEP = re.compile(r"[\s,;/&()\[\]\-]*(?:(?:and|or|&)[\s,;/()\-]*)?", re.I)
_ABBR = {"inc", "co", "ltd", "corp", "no", "vs", "e.g", "i.e", "dr", "st", "mr", "u.s"}


def _norm(s: str) -> str:
    s = (s or "").lower().replace("™", " ").replace("®", " ")
    return s


def tokens(name: str | None) -> set[str]:
    """Distinctive tokens of an FDA device name: alphanumeric words of 3+ chars that are not generic.
    Pure numbers count only from 3 digits up (model numbers such as 840, 7200, 6600)."""
    out = set()
    for w in re.findall(r"[a-z0-9]+", _norm(name)):
        if len(w) < 3 or w in GENERIC:
            continue
        if w.isdigit() and (len(w) < 3 or re.fullmatch(r"(?:19|20)\d\d", w)):
            continue
        out.add(w)
    return out


def _lev_le(a: str, b: str, k: int) -> bool:
    """Levenshtein distance <= k (small k, short strings)."""
    if abs(len(a) - len(b)) > k:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > k:
            return False
        prev = cur
    return prev[-1] <= k


def local_span(text: str, start: int, end: int, before: int = 160, after: int = 100) -> str:
    """Text that names the K-number at text[start:end]: from the previous K-number (or `before` chars)
    to the next K-number (or `after` chars). In "A (K1) B (K2)" the span for K2 is " B (K2)"; in
    "K1 - A K2 - B" the span for K1 is "K1 - A". Both sides are kept because layouts differ."""
    ks = [m for m in _K_ANY.finditer(text, max(0, start - 600), min(len(text), end + 600))]
    # A group such as "(K002465, K961915)" or "K980642, K983219 and K010093" shares one name, so the
    # span extends over the whole group before looking for the neighbouring names.
    idx = next((i for i, m in enumerate(ks) if m.start() == start), None)
    if idx is None:
        ks, idx = [], 0
    g0 = g1 = idx
    while g0 > 0 and _SEP.fullmatch(text[ks[g0 - 1].end():ks[g0].start()]):
        g0 -= 1
    while g1 + 1 < len(ks) and _SEP.fullmatch(text[ks[g1].end():ks[g1 + 1].start()]):
        g1 += 1
    g_start = ks[g0].start() if ks else start
    g_end = ks[g1].end() if ks else end
    lo, hi = max(0, g_start - before), min(len(text), g_end + after)
    if g0 > 0:
        lo = max(lo, ks[g0 - 1].end())
    if g1 + 1 < len(ks):
        hi = min(hi, ks[g1 + 1].start())
    return text[lo:hi]


def name_check(span: str, cited_name: str | None) -> str:
    """'match' if a distinctive token of the cited device's FDA name appears in `span` (exactly, with
    spacing removed, with common OCR confusions undone, or within a small edit distance), 'mismatch'
    if none does, 'n/a' if the FDA name has no distinctive token. Shown to users; never drops an edge."""
    toks = tokens(cited_name)
    if not toks:
        return "n/a"
    low = _BOILER.sub(" ", _norm(span))
    variants = {low, low.replace("rn", "m"), low.replace("~", "g")}
    words: set[str] = set()
    compacts = []
    for v in variants:
        words |= set(re.findall(r"[a-z0-9]+", v))
        compacts.append(re.sub(r"[^a-z0-9]", "", v))
    fda_compact = re.sub(r"[^a-z0-9]", "", _norm(cited_name))
    for t in toks:
        if t in words:
            return "match"
        mixed = len(t) >= 3 and not t.isdigit() and not t.isalpha()      # model codes: lp6, hc431, s7a
        if (len(t) >= 4 or mixed) and not t.isdigit() and any(t in c for c in compacts):
            return "match"
        if len(t) >= 5 and not t.isdigit():
            k = 2 if len(t) >= 8 else 1
            if any(len(w) >= 4 and _lev_le(t, w, k) for w in words):
                return "match"
    # FDA names sometimes run words together ("REVOLUTIONFULL FACE MASK", "COMFORTGEL")
    for w in words:
        if (len(w) >= 5 and w not in GENERIC and not w.isdigit() and w in fda_compact
                and not any(w in g or g in w for g in _GENERIC_LONG)):
            return "match"
    return "mismatch"


def panel_check(src_panel: str | None, dst_panel: str | None) -> str:
    """'same' / 'different' / 'unknown' FDA advisory committee (e.g. AN = anesthesiology). A predicate
    from a different panel (sutures, glucose strips, stents for a CPAP mask) almost always means the
    K-number in the PDF is a typo or an OCR misread."""
    if not src_panel or not dst_panel:
        return "unknown"
    return "same" if src_panel == dst_panel else "different"


def neighbour_ks(k: str, known: dict[str, dict]) -> list[str]:
    """Known K-numbers that differ from k in exactly one digit, or by one adjacent transposition."""
    d = k[1:]
    out = []
    for other in known:
        o = other[1:]
        if o == d or len(o) != 6:
            continue
        diff = [i for i in range(6) if o[i] != d[i]]
        if len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                              and o[diff[0]] == d[diff[1]] and o[diff[1]] == d[diff[0]]):
            out.append(other)
    return sorted(out)


_SENT = re.compile(r"([A-Za-z\)]{1,12})\.\s+(?=[A-Z][a-z]{2,})")


def sentence_start(text: str) -> int:
    """Index where the last sentence of `text` begins (after '. ' + capitalised word, skipping
    abbreviations such as 'Inc.'); 0 if `text` has no sentence boundary."""
    pos = 0
    for m in _SENT.finditer(text):
        if m.group(1).lower() not in _ABBR:
            pos = m.end()
    return pos
