"""Phase 1: OCR fallback provenance (no OCR engine needed for these tests)."""
import json

from forebear import ocr, summaries


# ---------------------------------------------------------------- OCR provenance
def test_ocr_text_is_used_only_for_the_recorded_pdf_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(summaries, "SUMMARY_CACHE", tmp_path / "s")
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path / "o")
    (tmp_path / "s").mkdir()
    (tmp_path / "o").mkdir()
    rec = {"k": "K011714", "status": "no_text", "url": "https://x/K011714.pdf", "sha256": "abc", "pages": ["", ""]}
    (tmp_path / "s" / "K011714.json").write_text(json.dumps(rec))
    o = {"k": "K011714", "status": "ocr_ok", "source_sha256": "abc", "pages": ["Predicate Device(s) X (K000994)"],
         "engine": "rapidocr-onnxruntime", "engine_version": "1.4.4", "dpi": 300, "page_confidence": [0.97]}
    (tmp_path / "o" / "K011714.json").write_text(json.dumps(o))
    t = summaries.load_text("K011714")
    assert t["pages"] == o["pages"] and t["ocr"]["engine_version"] == "1.4.4"
    (tmp_path / "o" / "K011714.json").write_text(json.dumps({**o, "source_sha256": "different"}))
    assert summaries.load_text("K011714") is None                   # OCR of other bytes is never used


def test_ocr_refuses_bytes_that_do_not_match_the_record():
    class Resp:
        status_code = 200
        content = b"%PDF-1.4 other bytes"

    class Client:
        def get(self, url):
            return Resp()
    out = ocr.run({"k": "K1", "url": "https://x", "sha256": "0" * 64}, Client(), engine=object(), meta={})
    assert out["status"] == "sha_mismatch" and out["pages"] == []


def test_ocr_line_grouping_keeps_table_rows_together():
    boxes = [([[0, 100], [50, 100], [50, 120], [0, 120]], "Predicate Device(s)", 0.99),
             ([[300, 102], [400, 102], [400, 121], [300, 121]], "BiPAP Duet (K000994)", 0.97),
             ([[0, 160], [50, 160], [50, 180], [0, 180]], "Reason for submission", 0.98),
             ([[0, 200], [50, 200], [50, 220], [0, 220]], "口", 0.5)]          # CJK noise is dropped
    text, conf, n = ocr._lines(boxes)
    assert text.splitlines() == ["Predicate Device(s) BiPAP Duet (K000994)", "Reason for submission"]
    assert n == 3 and conf > 0.9


def test_pdf_portfolio_summary_is_read_from_its_embedded_attachment():
    import io

    from pypdf import PdfWriter
    inner = PdfWriter()
    inner.add_blank_page(612, 792)
    buf = io.BytesIO()
    inner.write(buf)
    outer = PdfWriter()
    outer.add_blank_page(612, 792)
    outer.add_attachment("K163127.510kSummary.Final.pdf", buf.getvalue())
    out = io.BytesIO()
    outer.write(out)
    # a blank embedded page has no text layer: nothing is recovered, so OCR would run instead
    assert ocr.attachment_text(out.getvalue()) is None
    assert ocr.attachment_text(b"%PDF-1.4 not really a pdf") is None


def test_ocr_is_never_used_when_no_sha256_was_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(summaries, "SUMMARY_CACHE", tmp_path / "s")
    monkeypatch.setattr(ocr, "OCR_CACHE", tmp_path / "o")
    (tmp_path / "s").mkdir()
    (tmp_path / "o").mkdir()
    (tmp_path / "s" / "K1.json").write_text(json.dumps({"k": "K1", "status": "no_text", "sha256": None, "pages": [""]}))
    (tmp_path / "o" / "K1.json").write_text(json.dumps({"k": "K1", "status": "ocr_ok", "source_sha256": None,
                                                        "pages": ["Predicate: X (K000994)"]}))
    assert summaries.load_text("K1") is None

    class Resp:
        status_code = 200
        content = b"%PDF-1.4 bytes"

    class Client:
        def get(self, url):
            return Resp()
    assert ocr.run({"k": "K1", "url": "u", "sha256": None}, Client(), engine=object(), meta={})["status"] == "sha_mismatch"
