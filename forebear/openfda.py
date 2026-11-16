"""Thin, cached client for the public openFDA device endpoints (no API key needed).

Raw API responses are cached as JSON under data/raw/openfda so the dataset can be
rebuilt offline and every fact in the graph can be traced to a fetched record.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterable

import httpx

from .config import CACHE_MODE, LIVE_OPENFDA_CACHE, OPENFDA_CACHE, USER_AGENT

BASE = "https://api.fda.gov/device"
_last_call = 0.0


# Bulky fields we never use (serial-number lists, distribution text, derived openfda block).
_DROP = {"openfda", "code_info", "more_code_info", "distribution_pattern", "action", "address_1",
         "address_2", "postal_code", "firm_fei_number"}


def _slim(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _DROP}


def _cache_path(endpoint: str, search: str, skip: int) -> Path:
    key = hashlib.sha1(f"{endpoint}|{search}|{skip}".encode()).hexdigest()[:16]
    name = f"{endpoint}_{key}.json"
    if CACHE_MODE["mode"] == "live" and not (OPENFDA_CACHE / name).exists():
        return LIVE_OPENFDA_CACHE / name
    return OPENFDA_CACHE / name


def _get(endpoint: str, search: str, limit: int = 1000, skip: int = 0, use_cache: bool = True) -> dict:
    global _last_call
    path = _cache_path(endpoint, search, skip)
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    wait = 0.3 - (time.time() - _last_call)       # stay well under 240 req/min
    if wait > 0:
        time.sleep(wait)
    params = {"search": search, "limit": limit, "skip": skip}
    for attempt in range(3):
        _last_call = time.time()
        r = httpx.get(f"{BASE}/{endpoint}.json", params=params, timeout=60,
                      headers={"User-Agent": USER_AGENT})
        if r.status_code == 404:                       # openFDA: "No matches found"
            data = {"meta": {"results": {"total": 0}}, "results": []}
            break
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        data = r.json()
        break
    else:
        raise RuntimeError(f"openFDA {endpoint} failed after retries: {search}")
    data["results"] = [_slim(row) for row in data.get("results", [])]
    data["_fetched"] = {"endpoint": endpoint, "search": search, "skip": skip,
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def _all(endpoint: str, search: str, use_cache: bool = True) -> list[dict]:
    out, skip = [], 0
    while True:
        d = _get(endpoint, search, skip=skip, use_cache=use_cache)
        rows = d.get("results", [])
        out.extend(rows)
        total = d.get("meta", {}).get("results", {}).get("total", 0)
        skip += len(rows)
        if not rows or skip >= total or skip >= 25000:
            return out


def clearances_for_product_code(code: str, use_cache: bool = True) -> list[dict]:
    return _all("510k", f"product_code:{code}", use_cache)


def clearances_by_k(k_numbers: Iterable[str], use_cache: bool = True) -> list[dict]:
    ks = sorted(set(k_numbers))
    out = []
    for i in range(0, len(ks), 40):
        chunk = ks[i:i + 40]
        out.extend(_all("510k", "k_number:(" + " OR ".join(chunk) + ")", use_cache))
    return out


def recalls_for_product_code(code: str, use_cache: bool = True) -> list[dict]:
    return _all("recall", f"product_code:{code}", use_cache)


def recalls_by_k(k_numbers: Iterable[str], use_cache: bool = True) -> list[dict]:
    ks = sorted(set(k_numbers))
    out = []
    for i in range(0, len(ks), 40):
        chunk = ks[i:i + 40]
        out.extend(_all("recall", "k_numbers:(" + " OR ".join(chunk) + ")", use_cache))
    return out


def classification(code: str, use_cache: bool = True) -> dict | None:
    rows = _all("classification", f"product_code:{code}", use_cache)
    return rows[0] if rows else None


def enforcement_by_event(event_ids: Iterable[str], use_cache: bool = True) -> list[dict]:
    """Enforcement reports carry the recall classification (Class I/II/III) that the
    recall endpoint lacks; they join on recall_number == product_res_number."""
    ids = sorted(set(e for e in event_ids if e))
    out = []
    for i in range(0, len(ids), 40):
        chunk = ids[i:i + 40]
        out.extend(_all("enforcement", "event_id:(" + " OR ".join(chunk) + ")", use_cache))
    return out
