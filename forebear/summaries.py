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
    """Where k's summary is read from. In live mode a record in data/live (gitignored) wins: it is either a summary
    the committed cache never had, or an explicit refresh() of one it has. Otherwise the committed data/raw cache."""
    raw = SUMMARY_CACHE / f"{k}.json"
    live = LIVE_SUMMARY_CACHE / f"{k}.json"
    if CACHE_MODE["mode"] == "live" and (live.exists() or not raw.exists()):
        return live
    return raw


def write_file(k: str) -> Path:
    """Where a fetched summary is written: data/live in live mode, so the app never rewrites the committed
    data/raw cache (only scripts/fetch_data.py, in raw mode, does)."""
    return (LIVE_SUMMARY_CACHE if CACHE_MODE["mode"] == "live" else SUMMARY_CACHE) / f"{k}.json"


def _store(k: str, rec: dict) -> None:
    """Write atomically: a crash mid-write never leaves a truncated record that would shadow the committed one."""
    p = write_file(k)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    tmp.replace(p)


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
    if (not o or o.get("status") not in ("ocr_ok", "attachment_text") or not rec.get("sha256")
            or o.get("source_sha256") != rec["sha256"]):
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
    rec = download(k, client)
    if rec["status"] != "error":          # transient errors are not cached
        _store(k, rec)
    return rec


class RefreshError(Exception):
    pass


def refresh(k: str, client: httpx.Client | None = None) -> dict:
    """Explicitly re-download k's summary PDF from FDA to detect a changed document. Live mode only: the refreshed
    record goes to data/live and supersedes the committed data/raw record for the app, which is never modified.

    The cached record is replaced only by genuinely readable evidence: a PDF with a text layer whose SHA-256 differs
    from the cached one. A download error, a missing PDF or an image-only PDF (whose OCR, if any, was made from other
    bytes) raises RefreshError and leaves the cache untouched, so existing lineage is never reconciled against
    unreadable evidence. Returns the current record with `refresh` metadata: {changed, previous_sha256}."""
    if CACHE_MODE["mode"] != "live":
        raise RefreshError("refresh writes the live cache only; call config.use_live_cache() first")
    prev = load(k)
    rec = download(k, client)
    prev_sha = (prev or {}).get("sha256")
    if rec["status"] == "error":
        raise RefreshError(f"download failed: {rec.get('error')}; the cached summary is kept")
    if rec["status"] == "missing":
        raise RefreshError("FDA returned no summary PDF for this clearance; the cached summary is kept")
    if prev_sha and rec["sha256"] == prev_sha:
        return prev | {"refresh": {"changed": False, "previous_sha256": prev_sha, "checked_at": rec["fetched_at"]}}
    if rec["status"] != "ok":
        raise RefreshError(f"the refreshed PDF (sha256 {str(rec['sha256'])[:12]}) has no readable text layer; "
                           "the cached summary is kept and nothing was reconciled")
    _store(k, rec)
    return rec | {"refresh": {"changed": True, "previous_sha256": prev_sha, "checked_at": rec["fetched_at"]}}


def download(k: str, client: httpx.Client | None = None) -> dict:
    """One download attempt over the candidate URLs; never touches the cache."""
    own = client is None
    client = client or httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    rec = {"k": k, "status": "missing", "url": None, "sha256": None, "pages": [],
           "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        for url in candidate_urls(k):
            r = client.get(url)
            if r.status_code == 429 or r.status_code >= 500:     # transient: never cached, never read as "missing"
                rec["status"] = "error"
                rec["error"] = f"HTTP {r.status_code} from {url}"
                break
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
    return rec
