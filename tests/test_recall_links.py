"""Phase 1: evidence on device-recall links and recalls that name no 510(k)."""
from conftest import recall

from forebear import dataset


# ---------------------------------------------------------------- recall-link evidence
def test_recall_links_record_name_agreement_and_timing():
    recs = [{**recall("Z-1", ["K000001", "K000002"], "2004-01-01"), "product": "Acme CPAP Alpha",
             "reason": "foam"}]
    devices = {"K000001": {"name": "ALPHA CPAP", "decision_date": "2000-01-10"},
               "K000002": {"name": "BETA MASK", "decision_date": "2005-03-01"}}
    stats = dataset.link_recalls(recs, devices)
    links = {x["k"]: x for x in recs[0]["links"]}
    assert links["K000001"] == {"k": "K000001", "name_check": "match", "before_clearance": False}
    assert links["K000002"]["name_check"] == "mismatch" and links["K000002"]["before_clearance"] is True
    assert stats == {"links": 2, "name_mismatch": 1, "before_clearance": 1}


def test_recall_link_evidence_reaches_the_assessment(tiny):
    r = {**recall("Z-0002-2021", ["K000001"], "2021-06-14"), "links": [
        {"k": "K000001", "name_check": "mismatch", "before_clearance": False}]}
    tiny.upsert_recalls([r])
    tiny.upsert_recalls([recall("Z-0002-2021", ["K000001"], "2021-06-14")])      # re-ingest without evidence
    x = next(x for x in tiny.device("K000001")["recalls"] if x["id"] == "Z-0002-2021")
    assert x["link_name_check"] == "mismatch" and x["linked_before_clearance"] is False


def test_unattributed_recalls_are_kept_per_product_code():
    recs = [{"product_res_number": "Z-9", "k_numbers": [], "root_cause_description": "Device Design",
             "event_date_initiated": "2020-01-01", "product_code": "BZD"},
            {"product_res_number": "Z-8", "k_numbers": ["K000001"], "root_cause_description": "Device Design"}]
    un = dataset.unattributed_recalls(recs, {"K000001"})
    assert [u["id"] for u in un] == ["Z-9"] and un[0]["design_related"]
