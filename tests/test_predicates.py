from forebear.predicates import extract_from_summary, normalise


def run(text, self_k="K999999"):
    return {h["k"]: h for h in extract_from_summary({"pages": [text]}, self_k)}


def test_ocr_variants_are_normalised():
    assert normalise("113068") == "K113068"
    assert normalise("1 31982") == "K131982"
    assert normalise("I12345") == "K112345"
    assert normalise("O7l234") == "K071234"
    assert normalise("12345") is None


def test_predicate_section_with_ocr_noise():
    hits = run("Predicate Device(s) Respironics REMstar Auto A-Flex HT [K(113068) Reason for Submission")
    assert hits["K113068"]["kind"] == "predicate"


def test_split_digits_and_reference_device():
    hits = run("Primary Predicate Device: DreamStation 2 - K200480 Common Name: CPAP\n"
               "Reference Device: Heated Tubing - K241268 Common/Usual Name: Hose")
    assert hits["K200480"]["kind"] == "predicate"
    assert hits["K241268"]["kind"] == "reference"


def test_self_number_and_non_k_tokens_ignored():
    hits = run("510(k) Number: K999999 Device Name: X. Model K12345 and BK123456 and K1234567 are not numbers.",
               self_k="K999999")
    assert hits == {}


def test_unlabelled_mention_is_low_confidence():
    hits = run("The accessory kit (K050505) can be used with the device.")
    assert hits["K050505"]["kind"] == "mention"
    assert hits["K050505"]["confidence"] < 0.5


def test_evidence_has_page_and_snippet():
    rec = {"pages": ["cover page", "The device is substantially equivalent to K101010."]}
    h = extract_from_summary(rec, "K999999")[0]
    assert h["page"] == 2 and "K101010" in h["snippet"]


def test_empty_or_malformed_summary():
    assert extract_from_summary({"pages": []}, "K1") == []
    assert extract_from_summary({}, "K1") == []
    assert extract_from_summary({"pages": ["", "\x00\x00"]}, "K1") == []


def test_design_related_excludes_manufacturing_process():
    from forebear.config import is_design_related
    assert is_design_related("Device Design") and is_design_related("Software design")
    assert is_design_related("Component design/selection") and is_design_related("Labeling design")
    assert not is_design_related("Process design")
    assert not is_design_related("Software design (manufacturing process)")
    assert not is_design_related("Process control") and not is_design_related(None)


def test_reference_table_heading_persists():
    text = ("Predicate Device: Airvo 2 (K131895)\n• Reference Devices\nDevice Reason for Reference\n"
            "User Adjustable Pressure Support Settings K121623 BIPAP A 40 VENTILATORY SUPPORT SYSTEM "
            "Used to support claims of substantial equivalence with respect to pressure support")
    hits = run(text)
    assert hits["K131895"]["kind"] == "predicate"
    assert hits["K121623"]["kind"] == "reference"


def test_explicit_reference_label_beats_inferred_predicate_elsewhere():
    rec = {"pages": ["Predicate Device: K063806 Sleepnet Mojo Reference Devices: K101129 Respironics AF531",
                     "Comparison table ... Reference K101129 Predicate has elbow but we added the AAV"]}
    hits = {h["k"]: h for h in extract_from_summary(rec, "K999999")}
    assert hits["K063806"]["kind"] == "predicate"
    assert hits["K101129"]["kind"] == "reference"


def test_reference_colon_and_weak_cue_needs_proximity():
    hits = run("Predicate: K152356 Care Orchestrator. Reference: K083526 DirectView.")
    assert hits["K152356"]["kind"] == "predicate" and hits["K083526"]["kind"] == "reference"
    far = "substantially equivalent. " + "x" * 300 + " The accessory K050505 is compatible."
    assert run(far)["K050505"]["kind"] == "mention"
