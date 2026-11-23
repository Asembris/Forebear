"""The two-hop showcase (K251770 -> K200480 -> REMstar -> Z-1974-2021) makes claims in the UI and README.
Each must match the shipped Relate store and the cached FDA evidence, and the depth-1 / depth-2 contrast it
demonstrates must stay true: a one-generation lookup finds no design-recall signal, two generations find one."""
import glob
import json
import re

import pytest

from conftest import ROOT

from forebear.graph import open_graph
from forebear.lineage import assess, provisional

FACTS = json.loads((ROOT / "web" / "src" / "story" / "two-hop.json").read_text(encoding="utf-8"))
RAW = ROOT / "data" / "raw"
norm = lambda s: re.sub(r"\s+", " ", s or "").strip()  # noqa: E731


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    import shutil
    from conftest import SHIPPED
    if not SHIPPED.exists():
        pytest.skip("shipped store missing; run scripts/build_graph.py")
    p = tmp_path_factory.mktemp("two-hop") / "forebear.rl"
    shutil.copy(SHIPPED, p)
    g = open_graph(p, read_only=True)
    k = FACTS["candidate"]["k"]
    yield {1: assess(g, k, 1), 2: assess(g, k, 2), 4: assess(g, k, 4)}
    g.close()


def _anc(a, k):
    return next(x for x in a["ancestors"] if x["k"] == k)


def test_depth_one_finds_no_design_signal(runs):
    a, f = runs[1], FACTS["depth1"]
    assert a["depth"] == f["generations"]
    assert a["verdict"] == f["verdict"] and provisional(a) is f["provisional"]
    assert "shallow_traversal" in a["coverage"]["evidence_reasons"]
    assert [x["k"] for x in a["ancestors"]] == [FACTS["predicate"]["k"]]
    assert not [s for s in a["signals"] if s["severity"] in ("high", "medium")]


@pytest.mark.parametrize("depth", [2, 4])
def test_depth_two_reveals_the_design_recall(runs, depth):
    a = runs[depth]
    assert a["verdict"] == FACTS["depth2"]["verdict"] and provisional(a) is FACTS["depth2"]["provisional"]
    assert a["coverage"]["evidence"] == "complete"
    r = FACTS["recall"]
    raised = [s for s in a["signals"] if s["severity"] in ("high", "medium")]
    holders = {s["chain"][-1] for s in raised if any(e.get("id") == r["id"] for e in s["evidence"])}
    assert holders == set(r["holders"])
    for s in raised:
        assert s["gen"] == 2 and s["chain"][:2] == [FACTS["candidate"]["k"], FACTS["predicate"]["k"]]


def test_candidate_and_predicate_match_store(runs):
    a, c, p = runs[2], FACTS["candidate"], FACTS["predicate"]
    d = a["device"]
    assert (d["name"], d["applicant"], d["decision_date"]) == (c["name"], c["applicant"], c["decision_date"])
    assert (d["summary_url"], d["summary_sha256"]) == (c["summary_url"], c["summary_sha256"])
    pred = _anc(a, p["k"])
    assert pred["gen"] == 1 and pred["name"].startswith(p["name"])
    assert (pred["applicant"], pred["decision_date"]) == (p["applicant"], p["decision_date"])
    assert len(pred["recalls"]) == p["recalls"]
    for gp in FACTS["grand_predicates"]:
        x = _anc(a, gp["k"])
        assert x["gen"] == 2 and x["name"] == gp["name"]
        assert (x["applicant"], x["decision_date"]) == (gp["applicant"], gp["decision_date"])


def test_hops_match_store_and_cached_pdf_text(runs):
    a = runs[2]
    urls = {FACTS["candidate"]["k"]: FACTS["candidate"], FACTS["predicate"]["k"]: FACTS["predicate"]}
    for h in FACTS["hops"]:
        hop = next(x for x in _anc(a, h["dst"])["hops"] if x["src"] == h["src"] and x["dst"] == h["dst"])
        assert hop["page"] == h["page"] and hop["kind"] == "predicate" and hop["trust"] == "extracted"
        assert h["quote"] in norm(hop["snippet"])
        assert hop["source_url"] == urls[h["src"]]["summary_url"]
        assert hop["source_sha256"] == urls[h["src"]]["summary_sha256"]
        # the quote is on the cited page of the cached FDA summary, whose hash is the one the graph records
        raw = json.loads((RAW / "summaries" / f"{h['src']}.json").read_text(encoding="utf-8"))
        assert raw["sha256"] == hop["source_sha256"] and raw["url"] == hop["source_url"]
        assert h["quote"] in norm(raw["pages"][h["page"] - 1])


def test_recall_matches_store(runs):
    r, cand = FACTS["recall"], FACTS["candidate"]
    for k in r["holders"]:
        x = next(rec for rec in _anc(runs[2], k)["recalls"] if rec["id"] == r["id"])
        assert (x["event"], x["classification"], x["root_cause"]) == (r["event"], r["classification"], r["root_cause"])
        assert x["design_related"] and x["initiated"] == r["initiated"] and x["url"] == r["url"]
        assert x["reason"].startswith(r["reason"])
    assert FACTS["predicate"]["decision_date"] < r["initiated"] < cand["decision_date"]


def test_recall_matches_cached_openfda_records():
    """FDA itself lists the grand-predicates, not the direct predicate, on the recall record: the signal can
    only be found by walking a second generation."""
    r, pk = FACTS["recall"], FACTS["predicate"]["k"]
    seen, names_pred = [], False
    for f in glob.glob(str(RAW / "openfda" / "recall_*.json")):
        for rec in json.loads(open(f, encoding="utf-8").read()).get("results", []):
            ks = rec.get("k_numbers") or []
            names_pred |= pk in ks
            if rec.get("product_res_number") == r["id"]:
                seen.append(rec)
    assert seen, "recall missing from the cached openFDA records"
    for rec in seen:
        assert set(r["holders"]) <= set(rec["k_numbers"]) and pk not in rec["k_numbers"]
        assert rec["root_cause_description"] == r["root_cause"] and rec["event_date_initiated"] == r["initiated"]
    assert not names_pred, f"a cached recall record now names {pk}; the two-hop framing needs revisiting"


def test_api_serves_both_depths(real_copy, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("FOREBEAR_DB", str(real_copy))
    from forebear import api
    importlib.reload(api)
    k = FACTS["candidate"]["k"]
    with TestClient(api.app) as c:
        one = c.get(f"/api/assess/{k}", params={"depth": 1}).json()
        two = c.get(f"/api/assess/{k}", params={"depth": 2}).json()
    assert (one["verdict"], one["depth"]) == (FACTS["depth1"]["verdict"], 1)
    assert (two["verdict"], two["depth"]) == (FACTS["depth2"]["verdict"], 2)


README_QUERY = """MATCH path = (d:Device {k: $k})-[:CITES*1..%d]->(a:Device)
WHERE all(c IN relationships(path) WHERE c.kind = 'predicate')
MATCH (a)-[:SUBJECT_OF]->(r:Recall)
WHERE r.classification = 'Class I' AND r.root_cause = 'Device Design'
  AND r.initiated < d.decision_date
RETURN [n IN nodes(path) | n.k] AS chain, r.id AS recall"""


def test_readme_query_depth_one_empty_depth_two_finds_recall(real_copy):
    """The simplified Cypher shown in the README returns nothing at depth 1 and the REMstar rows at depth 2."""
    g = open_graph(real_copy, read_only=True)
    try:
        k = FACTS["candidate"]["k"]
        assert g.q(README_QUERY % 1, {"k": k}) == []
        rows = g.q(README_QUERY % 2, {"k": k})
    finally:
        g.close()
    chains = sorted(tuple(x["chain"]) for x in rows)
    assert chains == sorted((k, FACTS["predicate"]["k"], h) for h in FACTS["recall"]["holders"])
    assert {x["recall"] for x in rows} == {FACTS["recall"]["id"]}
