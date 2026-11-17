"""Paths and constants shared by ingestion, graph and API layers."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
OPENFDA_CACHE = RAW / "openfda"
SUMMARY_CACHE = RAW / "summaries"      # extracted text + metadata JSON per K-number (PDFs are not kept)
OCR_CACHE = RAW / "ocr"                # OCR text for image-only summaries (scripts/fetch_data.py ocr)
# Live-ingest cache (gitignored). The committed raw cache is only written by scripts/fetch_data.py,
# so the shipped build stays reproducible no matter what users ingest in the app.
LIVE = DATA / "live"
LIVE_OPENFDA_CACHE = LIVE / "openfda"
LIVE_SUMMARY_CACHE = LIVE / "summaries"

# Cache mode: "raw" (build/fetch scripts: read+write data/raw) or "live" (app: read raw+live, write live).
CACHE_MODE = {"mode": "raw", "offline": False}


def use_live_cache() -> None:
    CACHE_MODE["mode"] = "live"
    CACHE_MODE["offline"] = False


def use_raw_cache(offline: bool = False) -> None:
    """offline=True (the shipped build): a cache miss raises instead of calling openFDA, so the
    build can never depend on whatever the network returns today."""
    CACHE_MODE["mode"] = "raw"
    CACHE_MODE["offline"] = offline


DB_PATH = Path(os.environ.get("FOREBEAR_DB", DATA / "forebear.rl"))

# Device families in the shipped dataset (FDA product codes).
#   BZD  Ventilator, non-continuous (CPAP / BiPAP sleep-therapy devices)
#   MNS  Ventilator, continuous, non-life-supporting (home ventilators)
#   MNT  Ventilator, continuous, minimal ventilatory support, facility use
#   CBK  Ventilator, continuous, facility use
DEFAULT_PRODUCT_CODES = ["BZD", "MNS", "MNT", "CBK"]

# 510(k) summaries became routine after the Safe Medical Devices Act (1990s);
# earlier records rarely have a machine-readable summary.
SUMMARY_MIN_YEAR = 1996

USER_AGENT = "Forebear-research-prototype/0.1 (public FDA data)"


def is_design_related(root_cause: str | None) -> bool:
    """openFDA `root_cause_description` values that name design, e.g. "Device Design",
    "Software design", "Component design/selection", "Labeling design".

    FDA's 2023 draft guidance on predicate selection recommends choosing predicates
    that have not been subject to a design-related recall. openFDA's root-cause field
    is the only structured signal available; it is coarse, and we say so in the UI.
    """
    if not root_cause:
        return False
    rc = root_cause.lower()
    # "Process design" and "Software design (manufacturing process)" are manufacturing-process
    # causes, not device design, so they do not count.
    return "design" in rc and "process" not in rc
