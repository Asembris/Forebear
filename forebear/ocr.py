"""Local OCR fallback for image-only 510(k) summaries (status "no_text").

    python scripts/fetch_data.py ocr          # needs: pip install -r requirements-ocr.txt

For each summary whose PDF has no text layer, the PDF is downloaded again from the URL recorded
in data/raw/summaries/{K}.json and checked against the SHA-256 recorded there: OCR only runs on
the exact bytes the summary record describes. Pages are rendered at OCR_DPI with pypdfium2 and
read with RapidOCR (ONNX models bundled in the pinned wheel, no system binaries, CPU only).

The result goes to data/raw/ocr/{K}.json, separate from the text-layer record, with the engine,
version, render settings, per-page confidence and an outcome status. The offline build reads that
cache, so rebuilding never re-runs OCR and stays deterministic. The PDF itself is not kept.

OCR text is noisier than a text layer. Edges read from it are marked text_source="ocr", and every
cited K-number still has to resolve in openFDA and predate the citing clearance.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from pathlib import Path

from .config import OCR_CACHE

OCR_DPI = 300
MIN_CONFIDENCE = 0.80        # mean box confidence below this marks the page as low-confidence
ENGINE = "rapidocr-onnxruntime"


def cache_file(k: str) -> Path:
    return OCR_CACHE / f"{k}.json"


def load(k: str) -> dict | None:
    p = cache_file(k)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _engine():
    from importlib.metadata import version

    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(), {"engine": ENGINE, "engine_version": version("rapidocr-onnxruntime"),
                        "renderer": "pypdfium2", "renderer_version": version("pypdfium2"), "dpi": OCR_DPI}


def _lines(result) -> tuple[str, float, int]:
    """Group OCR boxes into text lines (top-to-bottom, then left-to-right) so table rows stay on one
    line, which is what the extractor's heading/table rules expect. Non-Latin glyphs (the bundled
    recogniser also knows CJK) are dropped: FDA summaries are English."""
    boxes = []
    for box, text, score in result or []:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        text = "".join(ch for ch in text if ord(ch) < 0x2E80)
        if text.strip():
            boxes.append((min(ys), max(ys), min(xs), text, float(score)))
    boxes.sort(key=lambda b: (b[0], b[2]))
    lines: list[list] = []
    for b in boxes:
        mid = (b[0] + b[1]) / 2
        if lines and abs(mid - lines[-1][0]) <= max(8.0, (b[1] - b[0]) * 0.5):
            lines[-1][1].append(b)
        else:
            lines.append([mid, [b]])
    text = "\n".join(" ".join(x[3] for x in sorted(ln[1], key=lambda x: x[2])) for ln in lines)
    scores = [b[4] for b in boxes]
    return text, (sum(scores) / len(scores) if scores else 0.0), len(boxes)


def ocr_pdf_bytes(data: bytes, engine=None, meta: dict | None = None) -> dict:
    import pypdfium2 as pdfium
    if engine is None:
        engine, meta = _engine()
    pdf = pdfium.PdfDocument(io.BytesIO(data))
    pages, conf, boxes = [], [], []
    for i in range(len(pdf)):
        img = pdf[i].render(scale=OCR_DPI / 72).to_pil()
        result, _ = engine(img)
        text, c, n = _lines(result)
        pages.append(text)
        conf.append(round(c, 3))
        boxes.append(n)
    return {"pages": pages, "page_confidence": conf, "page_boxes": boxes, **(meta or {})}


def attachment_text(data: bytes) -> dict | None:
    """Some FDA "summaries" are PDF Portfolios: the visible page only says to open the portfolio in
    Acrobat, and the real 510(k) summary is an embedded PDF. If an attachment whose name mentions the
    summary has a text layer, return its text (no OCR needed) with the attachment's name and SHA-256."""
    from importlib.metadata import version

    from pypdf import PdfReader
    try:
        attachments = PdfReader(io.BytesIO(data)).attachments
    except Exception:  # no attachment table, or an unreadable one
        return None
    for name in sorted(attachments):
        if "summary" not in name.lower():
            continue
        for blob in attachments[name]:
            if blob[:4] != b"%PDF":
                continue
            try:
                pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(blob)).pages]
            except Exception:  # encrypted or malformed attachment
                continue
            if sum(len(p.strip()) for p in pages) > 200:
                return {"pages": pages, "engine": "pypdf-embedded-attachment", "engine_version": version("pypdf"),
                        "attachment": name, "attachment_sha256": hashlib.sha256(blob).hexdigest()}
    return None


def run(summary: dict, client, engine=None, meta: dict | None = None) -> dict:
    """Recover the text of one no_text summary record: from an embedded summary PDF if the file is a
    portfolio, otherwise by OCR. Returns the record written to data/raw/ocr/{K}.json."""
    k = summary["k"]
    out = {"k": k, "source_url": summary.get("url"), "source_sha256": summary.get("sha256"),
           "ocr_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "download_failed",
           "pages": []}
    try:
        r = client.get(summary["url"])
        data = r.content if r.status_code == 200 else b""
    except Exception as e:  # network
        out["error"] = f"{type(e).__name__}: {e}"[:300]
        return out
    if data[:4] != b"%PDF":
        out["error"] = f"HTTP {r.status_code}, not a PDF"
        return out
    sha = hashlib.sha256(data).hexdigest()
    if not summary.get("sha256") or sha != summary["sha256"]:
        out.update(status="sha_mismatch", downloaded_sha256=sha,
                   error="FDA now serves different bytes than the summary record describes; not OCR'd")
        return out
    att = attachment_text(data)
    if att:                         # a PDF Portfolio: the summary is an embedded PDF with a text layer
        out.update(att, status="attachment_text", low_confidence_pages=[])
        return out
    try:
        res = ocr_pdf_bytes(data, engine, meta)
    except Exception as e:  # malformed PDF / renderer failure
        out.update(status="ocr_error", error=f"{type(e).__name__}: {e}"[:300])
        return out
    out.update(res)
    chars = sum(len(p.strip()) for p in res["pages"])
    low = [i + 1 for i, c in enumerate(res["page_confidence"]) if c and c < MIN_CONFIDENCE]
    out["low_confidence_pages"] = low
    out["status"] = "ocr_ok" if chars > 200 else "ocr_empty"
    return out


def save(rec: dict) -> None:
    p = cache_file(rec["k"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=0), encoding="utf-8")
