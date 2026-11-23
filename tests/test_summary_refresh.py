"""Explicit summary refresh and evidence-bound human reviews, end to end through the real cache.

Only the FDA web server is simulated (an httpx transport serving real PDF bytes) and openFDA metadata is stubbed. The
summary download, PDF parsing, SHA-256, the committed (data/raw) and live (data/live) caches, predicate extraction,
the ingest transaction and the trust rules all run for real, on temporary cache directories.
"""
import httpx
import pytest

from forebear import ingest, summaries
from forebear.lineage import assess, doubt

K = "K261000"
URL_PATH = f"/cdrh_docs/pdf26/{K}.pdf"
BOILER = ("This summary of 510(k) safety and effectiveness information is submitted in accordance with the "
          "requirements of 21 CFR 807.92. The device is a continuous positive airway pressure system for home use.")
V1 = ["Primary Predicate Device: Device K000003 (K000003).",
      "Secondary predicate device: Device K000009 (K000009).", BOILER]
V2 = ["Primary Predicate Device: Device K000009 (K000009).", BOILER]
META = [{"k_number": K, "device_name": "New CPAP", "applicant": "NewCo", "decision_date": "2026-05-01",
         "date_received": "2026-01-01", "product_code": "BZD", "statement_or_summary": "Summary"}]


def make_pdf(lines: list[str], salt: str = "") -> bytes:
    """A real one-page PDF with a text layer (Helvetica). `salt` changes the bytes, not the text."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    content = "BT /F1 9 Tf 40 800 Td 12 TL " + " ".join(f"({esc(t)}) Tj T*" for t in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 5 0 R >> >> "
            "/Contents 4 0 R >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n%" + salt.encode() + b"\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class FDA:
    """The simulated accessdata.fda.gov: serves `pdf`, or `status`, or raises a connection error."""

    def __init__(self):
        self.pdf, self.status, self.down, self.requests = make_pdf(V1), 200, False, 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path != URL_PATH or self.status == 404:
            return httpx.Response(404)
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(200, content=self.pdf)


@pytest.fixture
def fda(tmp_path, monkeypatch):
    raw, live = tmp_path / "raw" / "summaries", tmp_path / "live" / "summaries"
    monkeypatch.setattr(summaries, "SUMMARY_CACHE", raw)
    monkeypatch.setattr(summaries, "LIVE_SUMMARY_CACHE", live)
    monkeypatch.setitem(summaries.CACHE_MODE, "mode", "raw")
    server = FDA()
    real_client = httpx.Client
    monkeypatch.setattr(summaries.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(server.handler), **kw))
    monkeypatch.setattr(ingest.openfda, "clearances_by_k",
                        lambda ks, use_cache=True: [m for m in META if m["k_number"] in ks])
    monkeypatch.setattr(ingest, "fetch_recalls_for", lambda ks, use_cache=True: [])
    # the committed cache: written once in raw mode (as scripts/fetch_data.py does), then the app runs in live mode
    assert summaries.fetch(K)["status"] == "ok"
    monkeypatch.setitem(summaries.CACHE_MODE, "mode", "live")
    server.raw_file, server.live_file = raw / f"{K}.json", live / f"{K}.json"
    server.raw_bytes = server.raw_file.read_bytes()
    return server


def _edges(g):
    return {c["dst"]: c for c in g.direct_citations(K)}


def _hop(g, dst):
    return next(h for h in g.lineage_edges_from([K]) if h["dst"] == dst)


# ---------------------------------------------------------------- refresh path
def test_plain_reingest_reuses_the_cache_and_cannot_see_a_changed_pdf(tiny, fda):
    ingest.add_clearance(tiny, K)
    n = fda.requests
    fda.pdf = make_pdf(V2)                                          # FDA replaced the document
    res = ingest.add_clearance(tiny, K)
    assert fda.requests == n and res["refresh"] is None            # no download: the cached text was reused
    assert _edges(tiny)["K000003"]["retired_at"] is None


def test_refresh_detects_a_changed_pdf_and_never_touches_the_committed_cache(tiny, fda):
    ingest.add_clearance(tiny, K)
    old_sha = _edges(tiny)["K000009"]["source_sha256"]
    fda.pdf = make_pdf(V2)
    res = ingest.add_clearance(tiny, K, refresh=True)
    assert res["refresh"]["changed"] is True and res["refresh"]["previous_sha256"] == old_sha
    assert res["summary_sha256"] != old_sha
    assert [r["dst"] for r in res["reconciliation"]["retired"]] == ["K000003"]
    assert fda.raw_file.read_bytes() == fda.raw_bytes              # data/raw is never rewritten by the app
    assert summaries.load(K)["sha256"] == res["summary_sha256"]    # the live record now supersedes it
    assert _edges(tiny)["K000009"]["source_sha256"] == res["summary_sha256"]
    n = fda.requests
    ingest.add_clearance(tiny, K)                                  # a later plain ingest reads the refreshed text
    assert fda.requests == n and _edges(tiny)["K000003"]["retired_at"] is not None


def test_refresh_of_an_unchanged_pdf_changes_nothing(tiny, fda):
    ingest.add_clearance(tiny, K)
    stats = tiny.stats()
    res = ingest.add_clearance(tiny, K, refresh=True)
    assert res["refresh"]["changed"] is False and res["reconciliation"]["retired"] == []
    assert tiny.stats() == stats and not fda.live_file.exists()


@pytest.mark.parametrize("failure", ["down", 503, 404, "image_only"])
def test_failed_or_unreadable_refresh_changes_neither_cache_nor_graph(tiny, fda, failure):
    ingest.add_clearance(tiny, K)
    tiny.review_citation(K, "K000003", "confirmed", "checked p.1", reviewer="user")
    before_edges, stats = _edges(tiny), tiny.stats()
    if failure == "down":
        fda.down = True
    elif failure == "image_only":
        fda.pdf = make_pdf([])                                     # a scan: no text layer, new SHA-256
    else:
        fda.status = failure
    with pytest.raises(ingest.IngestError, match="did not change the graph"):
        ingest.add_clearance(tiny, K, refresh=True)
    assert tiny.stats() == stats and _edges(tiny) == before_edges
    assert not fda.live_file.exists() and fda.raw_file.read_bytes() == fda.raw_bytes


def test_refresh_is_refused_outside_live_mode(tiny, fda, monkeypatch):
    monkeypatch.setitem(summaries.CACHE_MODE, "mode", "raw")
    with pytest.raises(ingest.IngestError, match="live cache only"):
        ingest.add_clearance(tiny, K, refresh=True)
    assert fda.raw_file.read_bytes() == fda.raw_bytes


def test_failed_graph_write_after_a_refresh_rolls_back(tiny, fda, monkeypatch):
    ingest.add_clearance(tiny, K)
    stats, before = tiny.stats(), _edges(tiny)
    fda.pdf = make_pdf(V2)

    def boom(rows):
        raise RuntimeError("disk full")
    real_upsert = tiny.upsert_recalls
    monkeypatch.setattr(tiny, "upsert_recalls", boom)
    with pytest.raises(RuntimeError):
        ingest.add_clearance(tiny, K, refresh=True)
    assert tiny.stats() == stats and _edges(tiny) == before
    # the refreshed (readable) text stays cached; retrying the refresh applies it
    monkeypatch.setattr(tiny, "upsert_recalls", real_upsert)
    res = ingest.add_clearance(tiny, K, refresh=True)
    assert res["refresh"]["changed"] is False and [r["dst"] for r in res["reconciliation"]["retired"]] == ["K000003"]


# ---------------------------------------------------------------- reviews are bound to the evidence version
def test_a_changed_summary_makes_a_persons_review_outdated(tiny, fda):
    ingest.add_clearance(tiny, K)
    tiny.review_citation(K, "K000009", "confirmed", "read v1 p.1", reviewer="user")
    assert _hop(tiny, "K000009")["reviewed_source_sha256"] == _hop(tiny, "K000009")["source_sha256"]
    assert assess(tiny, K)["coverage"]["evidence"] != "uncertain"

    fda.pdf = make_pdf(V2)
    ingest.add_clearance(tiny, K, refresh=True)
    h = _hop(tiny, "K000009")                                      # still a predicate in v2, so still in lineage ...
    assert (h["review"], h["reviewer"], h["review_note"]) == ("confirmed", "user", "read v1 p.1")   # history kept
    assert h["reviewed_source_sha256"] != h["source_sha256"]
    assert "review_outdated" in doubt(h)                           # ... but no longer person-verified
    a = assess(tiny, K)
    assert a["coverage"]["evidence"] == "uncertain"                # its only direct predicate needs re-review
    hop = next(x for x in a["ancestors"] if x["k"] == "K000009")["hops"][0]
    assert hop["trust"] == "uncertain"

    tiny.review_citation(K, "K000009", "confirmed", "read v2 p.1", reviewer="user")
    assert assess(tiny, K)["coverage"]["evidence"] != "uncertain"
    assert next(x for x in assess(tiny, K)["ancestors"] if x["k"] == "K000009")["hops"][0]["trust"] == "human_verified"


def test_an_outdated_rejection_does_not_keep_hiding_a_predicate(tiny, fda):
    ingest.add_clearance(tiny, K)
    tiny.review_citation(K, "K000009", "rejected", "not a predicate in v1", reviewer="user")
    assert "K000009" not in {x["k"] for x in tiny.ancestors(K, 1)}
    fda.pdf = make_pdf(V2)
    ingest.add_clearance(tiny, K, refresh=True)
    assert "K000009" in {x["k"] for x in tiny.ancestors(K, 1)}     # the new evidence is read again, flagged
    assert "review_outdated" in doubt(_hop(tiny, "K000009"))


def test_a_restored_citation_does_not_inherit_approval_from_a_different_pdf(tiny, fda):
    ingest.add_clearance(tiny, K)
    v1_sha = _edges(tiny)["K000003"]["source_sha256"]
    tiny.review_citation(K, "K000003", "confirmed", "checked v1", reviewer="user")
    fda.pdf = make_pdf(V2)
    ingest.add_clearance(tiny, K, refresh=True)                    # K000003 retired
    fda.pdf = make_pdf(V1, salt="reissued")                        # same words, different document
    res = ingest.add_clearance(tiny, K, refresh=True)
    assert res["reconciliation"]["restored"] == ["K000003"]
    e = _edges(tiny)["K000003"]
    assert e["retired_at"] is None and e["source_sha256"] not in (v1_sha, None)
    assert (e["review"], e["reviewed_source_sha256"]) == ("confirmed", v1_sha)
    assert "review_outdated" in doubt(_hop(tiny, "K000003"))


def test_a_citation_restored_from_the_reviewed_pdf_keeps_its_review(tiny, fda):
    ingest.add_clearance(tiny, K)
    tiny.review_citation(K, "K000003", "confirmed", "checked v1", reviewer="user")
    fda.pdf = make_pdf(V2)
    ingest.add_clearance(tiny, K, refresh=True)
    fda.pdf = make_pdf(V1)                                         # FDA reverted to the exact reviewed bytes
    ingest.add_clearance(tiny, K, refresh=True)
    h = _hop(tiny, "K000003")
    assert h["reviewed_source_sha256"] == h["source_sha256"] and doubt(h) == []
