"""Download FDA 510(k) summary PDFs and keep only their extracted text.

The PDF itself is discarded after extraction; we keep the text per page, the
source URL, the SHA-256 of the downloaded bytes and the fetch time, so every
predicate edge can point at the exact page it was read from.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from pathlib import Path

import httpx
from pypdf import PdfReader

from .config import CACHE_MODE, LIVE_SUMMARY_CACHE, SUMMARY_CACHE, USER_AGENT


def candidate_urls(k: str) -> list[str]:
    yy = int(k[1:3])
    base = "https://www.accessdata.fda.gov/cdrh_docs"
    if yy >= 2 and yy < 90:
        return [f"{base}/pdf{yy}/{k}.pdf", f"{base}/pdf/{k}.pdf"]
    return [f"{base}/pdf/{k}.pdf", f"{base}/pdf1/{k}.pdf"]


def cache_file(k: str) -> Path:
    """Committed cache first; in live mode, anything not in it lives in data/live (gitignored)."""
    raw = SUMMARY_CACHE / f"{k}.json"
    if CACHE_MODE["mode"] == "live" and not raw.exists():
        return LIVE_SUMMARY_CACHE / f"{k}.json"
    return raw


def load(k: str) -> dict | None:
    p = cache_file(k)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_text(k: str) -> dict | None:
    """The readable text of k's summary: the PDF text layer when it has one, otherwise the local OCR
    of the same PDF (data/raw/ocr), used only if it was run on bytes with the recorded SHA-256.
    For a PDF Portfolio the recovered text is the embedded summary PDF's own text layer instead.
    The returned record carries `ocr` metadata (with `method` "ocr" or "embedded_pdf_attachment")
    when the text did not come from the PDF's text layer; None if unreadable."""
    rec = load(k)
    if not rec:
        return None
    if rec["status"] == "ok":
        return rec
    if rec["status"] != "no_text":
        return None
    from . import ocr
    o = ocr.load(k)
    if not o or o.get("status") not in ("ocr_ok", "attachment_text") or o.get("source_sha256") != rec.get("sha256"):
        return None
    meta = {key: o.get(key) for key in ("engine", "engine_version", "dpi", "page_confidence",
                                        "low_confidence_pages", "ocr_at", "attachment", "attachment_sha256")}
    meta["method"] = "embedded_pdf_attachment" if o["status"] == "attachment_text" else "ocr"
    return {**rec, "pages": o["pages"], "ocr": meta}


def fetch(k: str, client: httpx.Client | None = None, force: bool = False) -> dict:
    """Return {k, status, url, sha256, pages:[text], fetched_at}. status in ok|missing|no_text|error."""
    if not force:
        cached = load(k)
        if cached is not None:
            return cached
    own = client is None
    client = client or httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    rec = {"k": k, "status": "missing", "url": None, "sha256": None, "pages": [],
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        for url in candidate_urls(k):
            r = client.get(url)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                rec["url"] = url
                rec["sha256"] = hashlib.sha256(r.content).hexdigest()
                try:
                    reader = PdfReader(io.BytesIO(r.content))
                    rec["pages"] = [(p.extract_text() or "") for p in reader.pages]
                except Exception as e:  # malformed PDF
                    rec["status"] = "error"
                    rec["error"] = f"pdf parse: {e}"[:300]
                    break
                text_chars = sum(len(t.strip()) for t in rec["pages"])
                rec["status"] = "ok" if text_chars > 200 else "no_text"   # scanned image PDFs
                break
    except httpx.HTTPError as e:
        rec["status"] = "error"
        rec["error"] = str(e)[:300]
    finally:
        if own:
            client.close()
    if rec["status"] != "error":          # transient errors are not cached
        cache_file(k).parent.mkdir(parents=True, exist_ok=True)
        cache_file(k).write_text(json.dumps(rec), encoding="utf-8")
    return rec
