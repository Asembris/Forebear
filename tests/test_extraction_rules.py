"""Phase 1: deterministic name/panel/span checks and extraction rules on adversarial text."""
import pytest

from forebear import evidence
from forebear.predicates import extract_from_summary


def kinds(text, self_k="K999999"):
    return {h["k"]: h["kind"] for h in extract_from_summary({"pages": [text]}, self_k)}


# ---------------------------------------------------------------- name / panel checks
@pytest.mark.parametrize("span,name", [
    ("Legally Marketed Predicate Device: ResScan (K140054)", "RESCAN"),                 # FDA misspelling
    ("Primary Predicate Device: Galapagos K200565", "Galapogos"),                       # FDA misspelling
    ("Respironics Revolution Full Face Mask (K082866)", "REVOLUTIONFULL FACE MASK"),    # run-together words
    ("Suiter - SlurnbergearTm headgear - K042294", "SLUMBERGEAR(TM), MODEL MULTIPLE"),  # OCR rn -> m
    ("Hans Rudolph 6600 Series V2 (K071149)", "HRI 6500, 6600 AND 6700 SERIES V2MASKS"),  # model number
    ("LP-6 Ventilator with Puritan Bennett Cigarette Lighter K905244", "MODEL LP6 VENTILATOR, MODIFICATION"),
])
def test_name_check_accepts_real_variants(span, name):
    assert evidence.name_check(span, name) == "match"


@pytest.mark.parametrize("span,name", [
    ("S7 Elite (K010909) Reason for submission", "NONABSORBABLE POLYPROPYLENE SURGICAL SUTURE"),
    ("Respironics REMstar Auto C-Flex CPAP System (K040101)", "MODIFICATION TO DIADEXUS PLAC TEST"),
    # a word cut off at the span edge must not match a generic word inside the FDA name
    ("EvitaXL (K980642, K983219, K992608, K010093) The EvitaXL is a care ventilat",
     "NON-INVASIVE VENTILATION NIV OPTION, MODEL 84 14 474"),
    # regulation numbers, years and K-numbers are not model numbers
    ("21 CFR 868.5905 cleared 2005 (K050359)", "MODEL 868 SYSTEM 2005"),
])
def test_name_check_rejects_unrelated_names(span, name):
    assert evidence.name_check(span, name) == "mismatch"


def test_local_span_keeps_a_grouped_citation_with_its_name():
    text = "Predicate: Respironics ComfortFull Full-Face CPAP Mask (K002465, K961915) * Comfort Select (K000705)"
    i = text.index("K961915")
    span = evidence.local_span(text, i, i + 7)
    assert "ComfortFull" in span and "K000705" not in span      # stops at the next citation
    # in "A (K1) B (K2)" the span for K2 starts after K1
    t2 = "S8 Prime (K033841) S8 Pioneer (K041209)"
    j = t2.index("K041209")
    assert "S8 Prime" not in evidence.local_span(t2, j, j + 7)


def test_panel_check_and_neighbours():
    assert evidence.panel_check("AN", "SU") == "different"
    assert evidence.panel_check("AN", "AN") == "same" and evidence.panel_check(None, "AN") == "unknown"
    known = {"K013909": {}, "K010909": {}, "K042403": {}, "K999999": {}}
    assert evidence.neighbour_ks("K010909", known) == ["K013909"]          # one digit
    assert evidence.neighbour_ks("K042043", known) == ["K042403"]          # adjacent transposition


def test_sentence_start_skips_abbreviations():
    assert evidence.sentence_start("Respironics, Inc. Sleep products") == 0
    s = "the predicate device. Users can upload data"
    assert s[evidence.sentence_start(s):] == "Users can upload data"

# ---------------------------------------------------------------- extraction rules (adversarial)
def test_predicate_label_does_not_leak_into_the_next_sentence():
    assert kinds("includes a data upload function than the predicate device. Users can upload the data "
                 "to the cloud platform (K160127). Testing passed.")["K160127"] == "mention"


def test_component_and_compatibility_mentions_are_not_predicates():
    assert kinds("The Oxygen port is the same accessory used with the predicate device. "
                 "This accessory was cleared under K023559 and has not been modified.")["K023559"] == "mention"
    assert kinds("ResControl transfers data to a polysomnograph display system such as Sonologica (K971812).")[
        "K971812"] == "mention"


def test_predicate_heading_persists_down_a_long_table():
    rows = "\n".join(f"Vendor {i} ventilator model {i} with option K0{i}1{i}{i}2" for i in range(1, 7))
    text = "Predicate Device Identification\nLegally marketed devices to which equivalence is claimed\n" + rows
    k = kinds(text)
    assert k["K061662"] == "predicate"            # last row, far more than 220 characters below the heading


def test_classification_name_with_accessory_does_not_demote_a_predicate_list():
    text = ("Classification Name: Accessory to Noncontinuous ventilator (IPPB) Predicate Devices: "
            "K030822 - Hans Rudolph 7600 Vmask K040506 - Fisher & Paykel HC431 Device Description")
    k = kinds(text)
    assert k["K030822"] == "predicate" and k["K040506"] == "predicate"


def test_compatible_device_in_a_predicate_sentence_is_still_a_known_limitation():
    """Documented limitation (docs/EVIDENCE_QUALITY.md): when the same sentence also says "predicate",
    the component guard does not fire; the audit decision file handles such edges."""
    text = ("The modified device is substantially equivalent to the predicate devices EasyCare Online (K093684) "
            "which includes compatibility with S9 AutoSet, cleared under K091947.")
    assert kinds(text)["K091947"] == "predicate"
