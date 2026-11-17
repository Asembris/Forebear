"""Independent verification of agent findings.

A finding is accepted only if everything it asserts can be found in what the tools returned during the run
(the Ledger). Nothing the model writes is trusted on its own:

- every K-number and recall id in the claim or its evidence was returned by a tool;
- each citation pair it names ("K1->K2", or two K-numbers with "cites"/"predicate") is a citation a tool
  returned, and a claim that a citation was verified needs a passing verify_citation result;
- each recall it pins on a device is linked to one of the claim's devices by FDA's own k_numbers;
- every number it states (counts, years) appears in a tool result of this run;
- it makes no safety, approval or regulatory determination;
- it does not present absence of a recall signal as settled when the evidence is not complete.

Rejected findings stay in the report, with the reasons, so a reader sees what the model tried to say.
"""
from __future__ import annotations

import re

from .tools import Ledger

K_ANY = re.compile(r"\bK\d{6}\b")
RECALL_ANY = re.compile(r"\bZ-\d{4}-\d{4}\b")
RECALL_LIKE = re.compile(r"\bZ-\d{2,4}(?:[/\-]\d{1,4})+\b")
PAIR = re.compile(r"\b(K\d{6})\s*(?:->|→|-+>)\s*(K\d{6})\b")
EVENT_ANY = re.compile(r"\bevent[:\s#]*(\d{4,7})\b", re.I)
DATE_ANY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER = re.compile(r"(?<![\w.-])\d+(?:[.,]\d+)?(?![\w-])")

# Safety / regulatory determinations Forebear never makes (it reports documented lineage and recall history).
OVERCLAIM = re.compile(
    r"\b(is|are|be|was|were|remains?)\s+(an?\s+|the\s+)?(very\s+|completely\s+)?(safe|safer|unsafe|dangerous|"
    r"defective|harmless)\b|\bsafe to (use|cite|rely)\b|\bsafety (is|was) (confirmed|established|assured)\b|"
    r"\b(safe|safer|suitable|acceptable|good|appropriate|valid|reliable|trustworthy|sound) (predicate|choice)\b|"
    r"\bno (safety )?(risk|concern|issue)s?\b|\brisk[- ]free\b|\b(fda[- ])?approved\b|\bnot? (substantially )?"
    r"equivalent\b(?! claim)|\bmeets? (all )?(regulatory|fda) (requirements|standards)\b|\bcompliant\b|"
    r"\bguarantee[sd]?\b|\bdefinitive(ly)?\b|\bclears? (it|the device) for\b|\brecommend(ed)? (as|for use as) "
    r"(a )?predicate\b", re.I)
# Claims that something is absent or clean: only allowed when the evidence for that device is complete.
ABSENCE = re.compile(r"\bno (design(?:[- ]related)? |class i )?(recall|signal|issue|problem)s?\b|\bclean\b|"
                     r"\bnothing (found|of concern)\b|\bfree of\b|\bwithout (any )?recall", re.I)
QUALIFIED = re.compile(r"provisional|incomplete|partial|uncertain|not checkable|cannot be (ruled out|"
                       r"confirmed|checked)|could not|unverified|unknown|insufficient|not complete|gap", re.I)
VERIFIED_WORD = re.compile(r"\bverif(y|ied|ication)\b|\bconfirmed in the (pdf|summary|fda)", re.I)
SHA_ANY = re.compile(r"\b[0-9a-fA-F]{64}\b")
CLASS_ANY = re.compile(r"\bclass (iii|ii|i)\b", re.I)
# wording that says the listed recalls are a mix, or some are unclassified, so a single class is not asserted
CLASS_QUALIFIED = re.compile(r"unclassified|not classified|no (fda )?classification|unknown|mixed|some of|several "
                             r"of|one of|among", re.I)
PAGE_ANY = re.compile(r"\bpages?\s+(\d+)", re.I)
WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
COUNT = re.compile(r"\b(all\s+)?(\d+|" + "|".join(WORDS) + r")\s+(?:(?:distinct|separate|fda|product|recall)\s+)*"
                   r"(events?|records?|recalls?|design[- ]related|class\s+i\b(?!i))", re.I)


POSSESSIVE = re.compile(r"\b(has|have|had|having|with|carries|carry|carrying|lists|shows|accounts? for)\b", re.I)


def count_claims(claim: str) -> list[tuple[str | None, str, int]]:
    """(subject K-number or None, 'events'|'records'|'recalls'|'design'|'class_i', n) for each recall count stated
    in the claim. A count is attributed to the nearest K-number before it in the same sentence when the words in
    between say the device has them ("K113053 (BiPAP A30) has 4 recall events"); otherwise its subject is None."""
    out = []
    for m in COUNT.finditer(claim):
        _all, n, noun = m.groups()
        n = int(WORDS.get(n.lower(), n))
        noun = noun.lower()
        kind = ("events" if noun.startswith("event") else "records" if noun.startswith("record") else
                "recalls" if noun.startswith("recall") else "design" if noun.startswith("design") else "class_i")
        before = re.split(r"(?<=[.;])\s", claim[:m.start()])[-1]
        while re.search(r"\([^()]*\)", before):           # "K113068 (cited by K131982) has 2": skip asides
            before = re.sub(r"\([^()]*\)", " ", before)
        ks = list(K_ANY.finditer(before))
        subject = None
        if ks:
            gap = before[ks[-1].end():]
            if len(gap) <= 160 and POSSESSIVE.search(gap) and not RECALL_ANY.search(gap):
                subject = ks[-1].group(0)
        out.append((subject, kind, n))
    return out


def device_counts(recalls: list[dict]) -> dict[str, int]:
    return {"events": len({x.get("event") or x["id"] for x in recalls}), "records": len(recalls),
            "design": sum(1 for x in recalls if x.get("design_related")),
            "class_i": sum(1 for x in recalls if x.get("classification") == "Class I")}


def _counts_ok(stated: list[tuple[str, int]], sets: list[dict]) -> bool:
    """sets: the device's counts over all its recalls and over the rule-selected (signal) recalls. Every count
    stated about one device must come from the same basis."""
    keys = {"events": ["events"], "records": ["records"], "recalls": ["events", "records"],
            "design": ["design"], "class_i": ["class_i"]}
    return any(all(any(s.get(k) == n for k in keys[kind]) for kind, n in stated) for s in sets)


def _numbers(claim: str) -> list[str]:
    s = RECALL_ANY.sub(" ", K_ANY.sub(" ", claim))
    s = DATE_ANY.sub(lambda m: " ".join(m.group(0).split("-")), s)
    s = re.sub(r"\bclass\s+(i{1,3}|[123])\b", " ", s, flags=re.I)
    s = re.sub(r"\b510\s*\(k\)", " ", s, flags=re.I)
    out = []
    for n in NUMBER.findall(s):
        n = n.replace(",", "")
        if "." in n:
            out.append(n)
        else:
            out.append(str(int(n)))
    return out


def verify_finding(f: dict, ledger: Ledger, evidence_status: dict[str, str],
                   counts: dict[str, list[dict]] | None = None) -> dict:
    """evidence_status: K-number -> coverage.evidence of that device's deterministic assessment.
    counts: K-number -> [device_counts over all its recalls, device_counts over its signalled recalls], computed
    from the graph by the caller. Recall counts stated about a device must equal one of them."""
    claim = f["claim"]
    text = claim + " " + " ".join(f.get("evidence") or [])
    reasons: list[str] = []
    ks = set(K_ANY.findall(text))
    rids = set(RECALL_ANY.findall(text))
    known = ledger.known_ids()
    unknown = sorted((ks | rids) - known)
    if unknown:
        reasons.append(f"identifiers not returned by any tool in this run: {unknown}")
    if not (ks | rids) and not EVENT_ANY.search(text):
        reasons.append("cites no evidence identifier")
    shorthand = [t for t in RECALL_LIKE.findall(text) if not RECALL_ANY.fullmatch(t)]
    if shorthand:
        reasons.append(f"recall identifiers must be written in full to be checked: {shorthand}")
    for ev in EVENT_ANY.findall(text):
        if ev not in ledger.events:
            reasons.append(f"recall event {ev} was not returned by any tool")
    pairs = set(PAIR.findall(text))
    for src, dst in sorted(pairs):
        if (src, dst) not in ledger.citations:
            reasons.append(f"citation {src}->{dst} was not returned by any tool")
    ev_pairs = set(PAIR.findall(" ".join(f.get("evidence") or [])))
    for sentence in re.split(r"(?<=[.!?])\s+", claim):
        if not VERIFIED_WORD.search(sentence):
            continue
        s_ks = set(K_ANY.findall(sentence))
        named = set(PAIR.findall(sentence)) or {p for p in ledger.citations if p[0] in s_ks and p[1] in s_ks} \
            or ev_pairs
        bad = [p for p in named if not str(ledger.verified.get(p, {}).get("status", "")).startswith("verified")]
        if not named or bad:
            reasons.append(f"claims verification, but verify_citation did not pass for {sorted(bad) or 'any named citation'}")
    classes = {"Class " + c.upper() for c in CLASS_ANY.findall(claim)}
    if len(classes) == 1 and rids and not CLASS_QUALIFIED.search(claim):
        want = classes.pop()
        for rid in sorted(rids & set(ledger.recalls)):
            have = ledger.recalls[rid].get("classification")
            if have != want:
                reasons.append(f"recall {rid} is {have or 'not classified by FDA'}, not {want}")
    claim_ks = set(K_ANY.findall(claim)) or ks
    for rid in sorted(rids & known):
        linked = ledger.recall_links.get(rid, set())
        if claim_ks and not (linked & claim_ks):
            reasons.append(f"recall {rid} is not linked by FDA to {sorted(claim_ks)} (linked: {sorted(linked)})")
    by_subject: dict[str, list[tuple[str, int]]] = {}
    for subj, kind, n in count_claims(claim):
        if subj:
            by_subject.setdefault(subj, []).append((kind, n))
    for subj, stated in by_subject.items():
        sets = (counts or {}).get(subj)
        if sets is None:
            reasons.append(f"states recall counts for {subj}, whose recalls could not be counted")
        elif not _counts_ok(stated, sets):
            reasons.append(f"recall counts for {subj} do not match the graph: stated "
                           f"{[f'{n} {kind}' for kind, n in stated]}, graph has {sets[0]} (all recalls) / "
                           f"{sets[-1]} (signalled recalls)")
    stray = [n for n in _numbers(claim) if n not in ledger.numbers]
    if stray:
        reasons.append(f"numbers not found in any tool result: {stray}")
    for h in SHA_ANY.findall(claim):
        if h.lower() not in ledger.hashes:
            reasons.append(f"SHA-256 {h[:12]}... does not match any verified source")
    for p in PAGE_ANY.findall(claim):
        named = pairs or {q for q in ledger.citations if q[0] in ks and q[1] in ks}
        pages = {ledger.citations[q].get("page") for q in named if q in ledger.citations} | \
                {pg for q in named for pg in (ledger.verified.get(q, {}).get("checks") or {}).get("pages_naming_k_number", [])}
        if named and int(p) not in pages:
            reasons.append(f"page {p} is not where the tools located {sorted(named)} (pages {sorted(x for x in pages if x)})")
    if OVERCLAIM.search(claim):
        reasons.append("makes a safety, approval or regulatory determination, which this evidence cannot support")
    if ABSENCE.search(claim) and not QUALIFIED.search(claim):
        open_ = sorted(k for k in claim_ks if evidence_status.get(k, "unassessed") != "complete")
        if open_ or not claim_ks:
            reasons.append(f"states an absence as settled although the evidence is not complete for "
                           f"{open_ or 'the devices involved'}")
    return {**f, "status": "rejected" if reasons else "verified", "reasons": reasons}


def verify_all(findings: list[dict], ledger: Ledger, evidence_status: dict[str, str],
               counts: dict[str, list[dict]] | None = None) -> list[dict]:
    return [verify_finding(f, ledger, evidence_status, counts) for f in findings]
