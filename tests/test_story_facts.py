"""The opening film states facts about one real case. Each must match the shipped Relate store, so the
presentation can never drift from the evidence it dramatises."""
import json

import pytest

from conftest import ROOT

from forebear.graph import open_graph
from forebear.lineage import assess

FACTS = json.loads((ROOT / "web" / "src" / "story" / "facts.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def story(tmp_path_factory):
    import shutil
    from conftest import SHIPPED
    if not SHIPPED.exists():
        pytest.skip("shipped store missing; run scripts/build_graph.py")
    p = tmp_path_factory.mktemp("story") / "forebear.rl"
    shutil.copy(SHIPPED, p)
    g = open_graph(p, read_only=True)
    yield assess(g, FACTS["candidate"]["k"], 4)
    g.close()


def test_candidate_matches_store(story):
    c, d = FACTS["candidate"], story["device"]
    assert d["name"].startswith(c["name"])
    assert d["applicant"] == c["applicant"]
    assert d["decision_date"] == c["decision_date"]
    assert d["summary_url"] == c["summary_url"]
    assert story["verdict"] == c["verdict"]


def test_citation_page_and_quote_match_store(story):
    cit = FACTS["citation"]
    pred = next(a for a in story["ancestors"] if a["k"] == cit["dst"])
    assert pred["gen"] == 1
    hop = pred["hops"][0]
    assert (hop["src"], hop["dst"], hop["page"]) == (cit["src"], cit["dst"], cit["page"])
    assert cit["quote"] in hop["quote"]
    assert hop["kind"] == "predicate"


def test_predicate_and_recall_match_store(story):
    p, r = FACTS["predicate"], FACTS["recall"]
    pred = next(a for a in story["ancestors"] if a["k"] == p["k"])
    assert pred["name"].lower().replace(" ", "") == p["name"].lower().replace(" ", "")
    assert pred["applicant"] == p["applicant"] and pred["decision_date"] == p["decision_date"]
    recs = {x["id"]: x for x in pred["recalls"]}
    for rid in r["ids"]:
        x = recs[rid]
        assert x["event"] == r["event"] and x["classification"] == r["classification"]
        assert x["root_cause"] == r["root_cause"] and x["design_related"]
        assert x["initiated"] == r["initiated"] and x["reason"].startswith(r["reason"])
    assert r["initiated"] < FACTS["candidate"]["decision_date"]


def test_grand_predicates_match_store(story):
    gen = {a["k"]: a for a in story["ancestors"]}
    for gp in FACTS["grand_predicates"]:
        a = gen[gp["k"]]
        assert a["gen"] == 2 and a["decision_date"] == gp["decision_date"]
        assert a["chain"][:2] == [FACTS["candidate"]["k"], FACTS["predicate"]["k"]]
