"""Independent verification of agent findings.

A finding is accepted only if everything it asserts can be found in what the tools returned during the run
(the Ledger) and agrees with the graph. Nothing the model writes is trusted on its own:

- every K-number and recall id in the claim or its evidence was returned by a tool, written in full;
- each citation pair it names ("K1->K2") is a citation a tool returned; a sentence saying a link was verified,
  checked or matched needs a passing verify_citation result for the links it names;
- a claim that a person reviewed or confirmed something needs a human-confirmed link in the evidence;
- each recall it pins on a device is linked to that device by FDA's own k_numbers;
- recall counts stated about a device equal that device's counts in the graph, on one basis; a class stated for
  listed recalls matches each recall; dates match the record they describe; pages and SHA-256 values match the
  verified source; any other number appears in trusted tool output;
- it makes no safety, approval or regulatory determination, and does not call evidence complete or settled when
  the deterministic assessment says it is not;
- it states no absence ("no recall", "clean", "zero recalls") that contradicts the graph, and none on incomplete
  evidence unless that same sentence says it is provisional / incomplete.

`certainty: established` on a finding about a device whose evidence is not complete is downgraded to
provisional (noted on the finding). Rejected findings stay in the report with their reasons.
"""
from __future__ import annotations

import re

from .tools import Ledger

K_ANY = re.compile(r"\bK\d{6}\b")
RECALL_ANY = re.compile(r"\bZ-\d{4}-\d{4}\b")
RECALL_LIKE = re.compile(r"\bZ-\d{2,4}(?:[/\-]\d{1,4})+\b")
PAIR = re.compile(r"\b(K\d{6})\s*(?:->|→|-+>)\s*(K\d{6})\b")
EVENT_ANY = re.compile(r"\bevent[:\s#]*(\d{4,7})\b", re.I)
DATE_ANY = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")
NUMBER = re.compile(r"(?<![\w.-])\d+(?:[.,]\d+)?(?![\w-])")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")

SAFE_WORD = r"(safe|safer|unsafe|dangerous|defective|harmless|hazardous|hazard-free)"
# Safety / regulatory determinations Forebear never makes (it reports documented lineage and recall history).
OVERCLAIM = re.compile(
    r"\b(is|are|be|was|were|remains?|seems?|appears?)\s+(\w+\s+){0,3}?" + SAFE_WORD + r"\b|"
    r"\bsafe to (use|cite|rely)\b|\bsafety (is|was|has been) (confirmed|established|assured|shown)\b|"
    r"\b(clinically|demonstrably|inherently) safe\b|\bno (known )?(hazard|danger|harm)s?\b|\bposes? no\b|"
    r"\b(safe|safer|suitable|acceptable|good|appropriate|valid|reliable|trustworthy|sound) (predicate|choice)\b|"
    r"\bno (safety )?(risk|concern|issue)s?\b|\brisk[- ]free\b|\b(fda[- ])?approved\b|\bnot? (substantially )?"
    r"equivalent\b|\bmeets? (all )?(regulatory|fda) (requirements|standards)\b|\bcompliant\b|"
    r"\bguarantee[sd]?\b|\bdefinitive(ly)?\b|\bclears? (it|the device) for\b|\brecommend(ed)? (as|for use as) "
    r"(a )?predicate\b|\bno (further|additional) (review|investigation|checks?) (is |are )?(needed|required)\b",
    re.I)
# "the evidence is complete / settled": only true where the deterministic assessment says complete
SETTLED = re.compile(r"\b(lineage|ancestry|evidence|coverage|record)\b(\s+[\w'’()-]+){0,3}?\s+(is|was|are)\s+(\w+\s+)?(complete|"
                     r"established|settled|clean|fully (checked|verified|read))\b|\bfully (verified|checked) "
                     r"(lineage|ancestry)\b|\bcomplete (lineage|ancestry|evidence)\b", re.I)
# Claims that something is absent: never against the graph, and on incomplete evidence only when qualified.
ABSENCE = re.compile(r"\bno (design(?:[- ]related)? |class i )?(recall|signal|issue|problem)s?\b|\bclean\b|"
                     r"\bnothing (found|of concern)\b|\bfree of\b|\bwithout (any )?recalls?\b|\bzero (recall|"
                     r"design|class)|\b0 (recall|design|class)|\bnever (been )?recalled\b|\bnot (been )?recalled\b",
                     re.I)
QUALIFIED = re.compile(r"provisional|incomplete|partial|uncertain|not checkable|cannot be (ruled out|"
                       r"confirmed|checked)|could not|unverified|insufficient|not complete|within the (readable|"
                       r"read) |may be missing|would not show", re.I)
LINEAGE_WORD = re.compile(r"\b(lineage|ancestry|ancestors?|predicates?|family)\b", re.I)
DESIGN_WORD = re.compile(r"design", re.I)
VERIFIED_WORD = re.compile(r"\bverif(y|ied|ication)\b|\b(checked|cross-checked) (against|in|on)\b|\bmatch(es|ed)? "
                           r"(the|exactly|on)\b|\bconfirmed (in|against|on|by) the (pdf|summary|fda|original)", re.I)
HUMAN_WORD = re.compile(r"\b(human|person|people|reviewer|manually|by hand)\b|\bapproved by\b", re.I)
HUMAN_PENDING = re.compile(r"\b(needs?|awaits?|awaiting|requires?|pending|should|recommend\w*|propos\w*|until|"
                           r"for a|by a person|no person|not (been )?(reviewed|confirmed)|unreviewed)\b", re.I)
SHA_ANY = re.compile(r"\b[0-9a-fA-F]{64}\b")
CLASS_ANY = re.compile(r"\bclass (iii|ii|i)\b", re.I)
CLASS_QUALIFIED = re.compile(r"unclassified|not classified|no (fda )?classification|unknown|mixed|some of|several "
                             r"of|one of|among|lack|missing|ruled out|cannot be|could be|may be|whether|\bnone\b|"
                             r"\bneither\b|\bnor\b", re.I)
UNATTRIBUTED = re.compile(r"product code|unattributed|no 510\(k\)|name no|cannot be attributed", re.I)
ALL_DESIGN = re.compile(r"\b(all|both|each|every)\b[^.;]{0,80}\bdesign[- ]related", re.I)
NOT_DESIGN = re.compile(r"\bnot design|\bnon-design|\bnone\b", re.I)
PAGE_ANY = re.compile(r"\bpages?\s+(\d+)", re.I)
CLEARED_ON = re.compile(r"\b(cleared|decided|decision(?: date)?|received)\b[^.;]{0,25}?\b(?:in|on|of)\s+"
                        r"((?:19|20)\d{2}(?:-\d{2}-\d{2})?)", re.I)
INITIATED_ON = re.compile(r"\b(initiated|began|started|issued)\b[^.;]{0,25}?\b(?:in|on)\s+((?:19|20)\d{2}"
                          r"(?:-\d{2}-\d{2})?)", re.I)
WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
COUNT = re.compile(r"\b(all\s+)?(\d+|" + "|".join(WORDS) + r")\s+(?:(?:distinct|separate|fda|product|recall|"
                   r"additional|more|other|further|known|linked|total)\s+)*"
                   r"(events?|records?|recalls?|times\b|design[- ]related|class\s+i\b(?!i))", re.I)
POSSESSIVE = re.compile(r"\b(has|have|had|having|with|carries|carry|carrying|lists|shows|accounts? for)\b", re.I)
VIA = re.compile(r"\b(predicate|ancestor|through|via|lineage|inherit\w*|trac\w*|descend\w*|cites?|cited|chain)\b",
                 re.I)


def _strip_asides(s: str) -> str:
    while re.search(r"\([^()]*\)", s):
        s = re.sub(r"\([^()]*\)", " ", s)
    return s


def _masked(s: str) -> str:
    """Identifiers and dates replaced by same-length filler, so their digits are never read as counts."""
    for rx in (RECALL_ANY, RECALL_LIKE, K_ANY, DATE_ANY, SHA_ANY):
        s = rx.sub(lambda m: "x" * len(m.group(0)), s)
    return s


def _subject_before(sentence: str, pos: int) -> str | None:
    """Nearest K-number before pos in the sentence, ignoring parenthetical asides."""
    ks = list(K_ANY.finditer(_strip_asides(sentence[:pos])))
    return ks[-1].group(0) if ks else None


def count_claims(claim: str) -> list[tuple[str | None, str, int]]:
    """(subject K-number or None, 'events'|'records'|'recalls'|'design'|'class_i', n) for each recall count stated
    in the claim. A count belongs to the nearest K-number before it in the same sentence when the words in between
    say the device has them ("K113053 (BiPAP A30) has 4 recall events"), or to the sentence's only K-number."""
    out = []
    for sentence in SENTENCE.split(claim):
        masked = _masked(sentence)
        only = set(K_ANY.findall(sentence))
        for m in COUNT.finditer(masked):
            _all, n, noun = m.groups()
            n = int(WORDS.get(n.lower(), n))
            if 1900 <= n <= 2100 or n >= 10000:   # "a 2024 Class I recall", "the 88058 recall": not counts
                continue
            noun = noun.lower()
            kind = ("events" if noun.startswith("event") else "records" if noun.startswith("record") else
                    "recalls" if noun.startswith(("recall", "time")) else "design" if noun.startswith("design")
                    else "class_i")
            before = _strip_asides(sentence[:m.start()])
            ks = list(K_ANY.finditer(before))
            subject = None
            if ks:
                gap = before[ks[-1].end():]
                if len(gap) <= 160 and POSSESSIVE.search(gap) and not RECALL_ANY.search(gap):
                    subject = ks[-1].group(0)
            if subject is None and len(only) == 1:
                subject = next(iter(only))
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
    s = _masked(claim)
    s = re.sub(r"\bclass\s+(i{1,3}|[123])\b", " ", s, flags=re.I)
    s = re.sub(r"\b510\s*\(k\)", " ", s, flags=re.I)
    return [n.replace(",", "") if "." in n else str(int(n.replace(",", ""))) for n in NUMBER.findall(s)]


def _date_ok(stated: str, actual: str | None) -> bool:
    return bool(actual) and (str(actual)[:10] == stated if len(stated) == 10 else str(actual)[:4] == stated)


def verify_finding(f: dict, ledger: Ledger, evidence_status: dict[str, str],
                   counts: dict[str, list[dict]] | None = None, verdicts: dict[str, str] | None = None) -> dict:
    """evidence_status: K-number -> coverage.evidence of its deterministic assessment; verdicts: K-number -> verdict.
    counts: K-number -> [device_counts over all its recalls, over its signalled recalls], from the graph."""
    claim = f["claim"]
    counts, verdicts = counts or {}, verdicts or {}
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
    claim_ks = set(K_ANY.findall(claim)) or ks
    sentences = SENTENCE.split(claim)

    prev_ks: set = set()
    for sentence in sentences:
        s_ks = set(K_ANY.findall(sentence))
        ref_ks = s_ks or prev_ks             # "... K113053 cites K082660. All three links are verified."
        s_pairs = set(PAIR.findall(sentence)) or {p for p in ledger.citations if p[0] in ref_ks and p[1] in ref_ks} \
            or ev_pairs
        prev_ks = s_ks or prev_ks
        if VERIFIED_WORD.search(sentence):
            bad = [p for p in s_pairs if not str(ledger.verified.get(p, {}).get("status", "")).startswith("verified")]
            if not s_pairs or bad:
                reasons.append(f"claims verification, but verify_citation did not pass for "
                               f"{sorted(bad) or 'any named citation'}")
        if HUMAN_WORD.search(sentence) and not HUMAN_PENDING.search(sentence):
            if not any(ledger.citations.get(p, {}).get("provenance") == "human_confirmed" for p in s_pairs):
                reasons.append("says a person reviewed or confirmed evidence, but no link it names was confirmed "
                               "by a person")
        # recalls pinned on a device: the device the sentence attaches the recall to must be FDA-linked to it
        for m in RECALL_ANY.finditer(sentence):
            rid = m.group(0)
            if rid not in known:
                continue
            linked = ledger.recall_links.get(rid, set())
            if not linked and UNATTRIBUTED.search(sentence):
                continue                 # a recall that names no 510(k), described as such
            subj = _subject_before(sentence, m.start())
            between = _strip_asides(sentence[:m.start()])
            between = between[between.rfind(subj) + 7:] if subj else ""
            if subj and subj not in linked and not VIA.search(between):
                reasons.append(f"recall {rid} is attributed to {subj}, but FDA links it to {sorted(linked)}")
            elif not (linked & (s_ks or claim_ks)) and (s_ks or claim_ks):
                reasons.append(f"recall {rid} is not linked by FDA to {sorted(s_ks or claim_ks)} "
                               f"(linked: {sorted(linked)})")
        # dates: clearance and recall start dates must match the record they describe
        for m in CLEARED_ON.finditer(sentence):
            subj = _subject_before(sentence, m.start())
            if subj and subj in ledger.devices and not _date_ok(m.group(2), ledger.devices[subj].get("decision_date")) \
                    and not _date_ok(m.group(2), ledger.devices[subj].get("received_date")):
                reasons.append(f"{subj} {m.group(1)} date stated as {m.group(2)}, but its record says "
                               f"{ledger.devices[subj].get('decision_date')}")
        for m in INITIATED_ON.finditer(sentence):
            rs = [r.group(0) for r in RECALL_ANY.finditer(sentence)]
            near = [r for r in rs if r in ledger.recalls]
            if near and not any(_date_ok(m.group(2), ledger.recalls[r].get("initiated")) for r in near):
                reasons.append(f"recall start date {m.group(2)} does not match {near} "
                               f"({[ledger.recalls[r].get('initiated') for r in near]})")
        # absence claims: never against the graph; on incomplete evidence only when this sentence qualifies them
        if ABSENCE.search(sentence):
            subjects = s_ks or claim_ks
            design = bool(DESIGN_WORD.search(sentence))
            lineage = bool(LINEAGE_WORD.search(sentence))
            for k in sorted(subjects):
                c = counts.get(k)
                own = c[0] if c else None
                if own and (own["design"] if design else own["records"]):
                    reasons.append(f"states an absence, but {k} has {own['design'] if design else own['records']} "
                                   f"{'design-related ' if design else ''}recall record(s) in the graph")
                if lineage and verdicts.get(k) in ("REVIEW_LINEAGE", "DESIGN_RECALL_ON_FILE"):
                    reasons.append(f"states an absence in the lineage of {k}, whose assessment is {verdicts[k]}")
                # the absence must rest on something the model was shown: an assessment for a lineage claim,
                # a zero recall count for a device claim
                if lineage and not any(x in evidence_status for x in subjects):
                    reasons.append(f"states an absence in the lineage of {k}, but no assessment of "
                                   f"{sorted(subjects)} was shown")
                elif not lineage and not _counts_ok([("design" if design else "records", 0)],
                                                    ledger.recall_totals.get(k, [])):
                    reasons.append(f"states an absence of recalls for {k}, but no zero count for {k} was shown")
            if not QUALIFIED.search(sentence):
                open_ = sorted(k for k in subjects if evidence_status.get(k, "unassessed") != "complete")
                if open_ or not subjects:
                    reasons.append(f"states an absence as settled although the evidence is not complete for "
                                   f"{open_ or 'the devices involved'}")
        if SETTLED.search(sentence):
            judged = [k for k in (s_ks or claim_ks) if k in evidence_status] or list(evidence_status)
            open_ = sorted(k for k in judged if evidence_status[k] != "complete")
            if open_ or not judged:
                reasons.append(f"calls the evidence complete or settled, but the assessment says otherwise for "
                               f"{open_ or 'the devices involved'}")

    # "all/both/each ... design-related" over listed recalls: every listed recall the model saw must be design-related
    if rids and ALL_DESIGN.search(claim) and not NOT_DESIGN.search(claim):
        for rid in sorted(rids & set(ledger.recalls)):
            if ledger.recalls[rid].get("design_related") is False:
                reasons.append(f"recall {rid} is not design-related (root cause "
                               f"{ledger.recalls[rid].get('root_cause') or 'unknown'})")
            elif "design_related" not in ledger.recalls[rid]:
                reasons.append(f"recall {rid} was called design-related, but its root cause was not shown")
    classes = {"Class " + c.upper() for c in CLASS_ANY.findall(claim)}
    if len(classes) == 1 and rids and not CLASS_QUALIFIED.search(claim):
        want = classes.pop()
        for rid in sorted(rids & set(ledger.recalls)):
            have = ledger.recalls[rid].get("classification")
            if have != want:
                reasons.append(f"recall {rid} is {have or 'not classified by FDA'}, not {want}")
    by_subject: dict[str, list[tuple[str, int]]] = {}
    unattributed = []
    for subj, kind, n in count_claims(claim):
        if subj:
            by_subject.setdefault(subj, []).append((kind, n))
        else:
            unattributed.append(str(n))
    for subj, stated in by_subject.items():
        sets = counts.get(subj)
        shown_sets = ledger.recall_totals.get(subj, [])
        if sets is not None and not _counts_ok(stated, sets):
            reasons.append(f"recall counts for {subj} do not match the graph: stated "
                           f"{[f'{n} {kind}' for kind, n in stated]}, graph has {sets[0]} (all recalls) / "
                           f"{sets[-1]} (signalled recalls)")
        elif not _counts_ok(stated, shown_sets):
            # correct or not, a count is only accepted if the model was shown it for this device
            reasons.append(f"recall counts for {subj} were not shown to the model in this run "
                           f"(shown: {[{k: v for k, v in x.items()} for x in shown_sets][:3] or 'none'})")
    for d in DATE_ANY.finditer(claim):
        if d.group(0) not in ledger.dates:
            reasons.append(f"date {d.group(0)} does not appear in any tool result")
    stray = [n for n in _numbers(claim) if n not in ledger.numbers]
    if stray:
        reasons.append(f"numbers not found in trusted tool output: {stray}")
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
    out = {**f, "status": "rejected" if reasons else "verified", "reasons": list(dict.fromkeys(reasons))}
    if not reasons and f.get("certainty") == "established" and f.get("kind") not in ("uncertainty", "gap"):
        open_ = sorted(k for k in claim_ks if evidence_status.get(k) != "complete")
        if open_ and (ABSENCE.search(claim) or LINEAGE_WORD.search(claim)):
            out["certainty"] = "provisional"
            out["certainty_note"] = f"downgraded from 'established': evidence for {open_} is not complete"
    return out


def overclaims(text: str) -> bool:
    """For free text that cannot carry evidence (open questions): does it make a determination?"""
    return bool(OVERCLAIM.search(text) or SETTLED.search(text))


def verify_all(findings: list[dict], ledger: Ledger, evidence_status: dict[str, str],
               counts: dict[str, list[dict]] | None = None, verdicts: dict[str, str] | None = None) -> list[dict]:
    return [verify_finding(f, ledger, evidence_status, counts, verdicts) for f in findings]
