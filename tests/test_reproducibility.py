"""Fresh setup: rebuilding the store from the committed raw cache (no network) must
reproduce the shipped graph's counts exactly."""
import json
import os

import pytest

from conftest import ROOT


@pytest.mark.skipif(os.environ.get("FOREBEAR_SKIP_SLOW") == "1", reason="slow rebuild skipped")
def test_rebuild_from_raw_cache_matches_shipped_report(tmp_path, monkeypatch):
    import scripts.build_graph as bg

    # forbid network: any uncached openFDA call would raise
    import forebear.openfda as of
    real_get = of._get

    def cached_only(endpoint, search, limit=1000, skip=0, use_cache=True):
        if not of._cache_path(endpoint, search, skip).exists():
            raise AssertionError(f"uncached openFDA call during rebuild: {endpoint} {search}")
        return real_get(endpoint, search, limit, skip, use_cache)
    monkeypatch.setattr(of, "_get", cached_only)

    shipped = json.loads((ROOT / "data" / "build_report.json").read_text())
    rep = bg.build(tmp_path / "rebuilt.rl", shipped["product_codes"])
    for key in ("in_family_devices", "out_of_family_predicates", "citation_extraction",
                "recall_records_linked", "graph"):
        assert rep[key] == shipped[key], key
