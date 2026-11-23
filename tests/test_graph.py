"""Relate persistence, MERGE idempotence, lineage queries and graph writes."""
from conftest import build_tiny, cite, dev, recall

from forebear.graph import open_graph
from forebear.lineage import assess, recall_reach


def test_persists_and_reopens_read_only(tmp_path):
    p = tmp_path / "t.rl"
    g = build_tiny(p)
    before = g.stats()
    g.close()
    assert p.exists() and p.stat().st_size > 0
    r = open_graph(p, read_only=True)
    try:
        assert r.stats() == before
        assert [a["k"] for a in r.ancestors("K000004")][:1] == ["K000003"]
    finally:
        r.close()


def test_upserts_are_idempotent(tiny):
    before = tiny.stats()
    tiny.upsert_devices([dev("K000003", "2010-06-01")])
    tiny.upsert_citations([cite("K000004", "K000003")])
    tiny.upsert_recalls([recall("Z-0001-2008", ["K000002"], "2008-04-01")])
    assert tiny.stats() == before


def test_ancestors_generations_and_chain(tiny):
    anc = {a["k"]: a for a in tiny.ancestors("K000005", depth=6)}
    assert anc["K000004"]["gen"] == 1
    assert anc["K000002"]["gen"] == 3
    assert anc["K000002"]["chain"] == ["K000005", "K000004", "K000003", "K000002"]
    assert anc["K000002"]["recalls"][0]["id"] == "Z-0001-2008"
    assert all(h["snippet"] for h in anc["K000002"]["hops"])
    # depth limit is respected
    assert "K000001" not in {a["k"] for a in tiny.ancestors("K000005", depth=3)}


def test_descendants(tiny):
    desc = {d["k"]: d["gen"] for d in tiny.descendants("K000003", depth=3)}
    assert desc == {"K000004": 1, "K000005": 2, "K000006": 2}   # K000007 is only a 'mention'


def test_reject_removes_edge_from_lineage(tiny):
    assert "K000002" in {a["k"] for a in tiny.ancestors("K000004")}
    tiny.review_citation("K000004", "K000003", "rejected", "wrong number, OCR")
    assert tiny.ancestors("K000004") == [a for a in tiny.ancestors("K000004") if a["k"] == "K000008"]
    tiny.review_citation("K000004", "K000003", "", None)
    assert "K000002" in {a["k"] for a in tiny.ancestors("K000004")}


def test_confirm_or_ai_label_promotes_mention(tiny):
    assert tiny.ancestors("K000007") == []
    tiny.set_triage("K000007", "K000004", "predicate", "Predicate device", "test-model")
    assert "K000004" in {a["k"] for a in tiny.ancestors("K000007")}
    tiny.review_citation("K000007", "K000004", "rejected", None)   # humans override AI
    assert tiny.ancestors("K000007") == []


def test_cited_after_recall_is_temporal(tiny):
    # K000003 (2010) cites K000002 whose recall started 2008 -> flagged; K000004 is gen 2
    rows = tiny.cited_after_recall(design_only=True)
    got = {(r["k"], r["ancestor"], r["gen"]) for r in rows}
    assert ("K000003", "K000002", 1) in got
    assert ("K000004", "K000002", 2) in got
    assert not any(r["k"] == "K000005" for r in rows)              # 3 generations away


def test_recall_event_reach_splits_before_after(tiny):
    r = recall_reach(tiny, "1", depth=3)
    assert [x["k"] for x in r["recalled"]] == ["K000002"]
    after = {d["k"] for d in r["descendants"] if d["after_recall"]}
    assert after == {"K000003", "K000004", "K000005", "K000006"}       # K000007 cites only as 'mention'
    assert {d["k"] for d in r["descendants"]} == after               # K000001 (older ancestor) excluded


def test_assessment_saved_and_survives_reopen(tmp_path):
    p = tmp_path / "t.rl"
    g = build_tiny(p)
    a = assess(g, "K000003")
    aid = g.save_assessment("K000003", a["verdict"], {"x": 1}, "memo", "template", ["Z-0001-2008"])
    g.close()
    g = open_graph(p)
    try:
        rows = g.assessments("K000003")
        assert rows[0]["id"] == aid and rows[0]["flagged"] == ["Z-0001-2008"]
    finally:
        g.close()


def test_search_by_k_prefix_and_text(tiny):
    assert tiny.search("K00000")[0]["k"] == "K000001"
    assert tiny.search("Device")
    assert tiny.search("   ") == []
    assert tiny.search("!!!") == []


def test_multi_event_reach_uses_each_lineages_own_recall_date(tiny):
    # event 9 starts in 2019 on K000004; event 1 started 2008 on K000002.
    tiny.upsert_recalls([recall("Z-0009-2019", ["K000004"], "2019-06-01", event="9")])
    r = {d["k"]: d for d in recall_reach(tiny, "1,9", depth=3)["descendants"]}
    # K000005 (2020) and K000006 (2021) descend from both; earliest relevant start is 2008 -> after
    assert r["K000005"]["after_recall"] and r["K000006"]["after_recall"]
    only9 = {d["k"]: d for d in recall_reach(tiny, "9", depth=3)["descendants"]}
    assert only9["K000005"]["after_recall"] and only9["K000005"]["recall_started"] == "2019-06-01"


def test_multi_event_reach_does_not_borrow_another_events_start(tiny):
    """K000010 (2017) descends only from K000004, whose recall (event 9) began 2019. Event 1
    began 2008 on a different device; a global-minimum comparison would wrongly say 'after'."""
    tiny.upsert_devices([dev("K000010", "2017-03-01")])
    tiny.upsert_citations([cite("K000010", "K000004")])
    tiny.upsert_recalls([recall("Z-0009-2019", ["K000004"], "2019-06-01", event="9")])
    r = {d["k"]: d for d in recall_reach(tiny, "1,9", depth=1)["descendants"]}
    assert r["K000010"]["via"] == ["K000004"]
    assert r["K000010"]["after_recall"] is False
