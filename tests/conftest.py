import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forebear.graph import open_graph  # noqa: E402

SHIPPED = ROOT / "data" / "forebear.rl"


def dev(k, date, name=None, in_scope=True, lineage_known=True, code="BZD"):
    return {"k": k, "name": name or f"Device {k}", "applicant": "Acme Inc.", "company": "ACME",
            "decision_date": date, "received_date": date, "product_code": code, "decision": "SE",
            "clearance_type": "Traditional", "summary_status": "ok" if lineage_known else "missing",
            "summary_url": f"https://example.invalid/{k}.pdf", "summary_sha256": None,
            "in_scope": in_scope, "lineage_known": lineage_known}


def cite(src, dst, kind="predicate", page=1):
    return {"src": src, "dst": dst, "kind": kind, "confidence": 0.9, "page": page,
            "snippet": f"Predicate device: X ({dst})", "method": "test", "source_url": None}


def recall(rid, ks, date, design=True, cls="Class I", event="1"):
    return {"id": rid, "recall_number": rid, "event": event, "classification": cls,
            "root_cause": "Device Design" if design else "Process control", "design_related": design,
            "initiated": date, "status": "Open", "firm": "Acme", "reason": "test reason",
            "product": "p", "url": None, "product_code": "BZD", "k_numbers": ks}


def build_tiny(path):
    """
    K000001 (2000) <- K000002 (2005) <- K000003 (2010) <- K000004 (2015) <- K000005 (2020)
                                          \\                                   K000006 (2021) cites K000004
    K000002 has a design-related Class I recall (2008).
    K000007 (2016) cites K000004 only as a 'mention'.
    K000008 (2012) has no predicates read (lineage unknown) and is cited by K000004 too.
    K000009 (2018) cites K000001 only: a clean lineage with no recalls anywhere.
    """
    g = open_graph(path)
    g.upsert_product_codes([{"code": "BZD", "name": "CPAP", "device_class": "2", "regulation": "868.5905"}])
    g.upsert_devices([dev("K000001", "2000-01-10"), dev("K000002", "2005-03-01"), dev("K000003", "2010-06-01"),
                      dev("K000004", "2015-02-01"), dev("K000005", "2020-05-05"), dev("K000006", "2021-07-01"),
                      dev("K000007", "2016-01-01"), dev("K000008", "2012-01-01", lineage_known=False),
                      dev("K000009", "2018-01-01")])
    g.upsert_citations([cite("K000002", "K000001"), cite("K000003", "K000002"), cite("K000004", "K000003"),
                        cite("K000005", "K000004"), cite("K000006", "K000004"), cite("K000004", "K000008"),
                        cite("K000007", "K000004", kind="mention"), cite("K000009", "K000001")])
    g.upsert_recalls([recall("Z-0001-2008", ["K000002"], "2008-04-01")])
    return g


@pytest.fixture
def tiny(tmp_path):
    g = build_tiny(tmp_path / "tiny.rl")
    yield g
    g.close()


@pytest.fixture
def real_copy(tmp_path):
    if not SHIPPED.exists():
        pytest.skip("shipped store missing; run scripts/build_graph.py")
    p = tmp_path / "forebear.rl"
    shutil.copy(SHIPPED, p)
    return p


@pytest.fixture
def live_api(real_copy, monkeypatch):
    """A real uvicorn server on a free port, serving a copy of the shipped store.
    Yields an env dict with FOREBEAR_URL set (plus .port for raw-socket tests)."""
    import importlib
    import os
    import socket
    import threading
    import time

    import uvicorn

    monkeypatch.setenv("FOREBEAR_DB", str(real_copy))
    from forebear import api
    importlib.reload(api)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    env = dict(os.environ, FOREBEAR_URL=f"http://127.0.0.1:{port}")
    env["_PORT"] = str(port)
    yield env
    server.should_exit = True
    t.join(timeout=10)
