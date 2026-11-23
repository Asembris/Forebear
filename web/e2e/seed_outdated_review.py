"""Give the throwaway e2e store one genuinely outdated review: a person's confirmation of K251889 -> K251661
recorded against an earlier version of K251889's summary PDF. This is the state a summary refresh leaves behind
when the PDF changed (tests/test_summary_refresh.py); the browser suite cannot fetch FDA, so it is set directly.
Usage: python seed_outdated_review.py <path to e2e .rl copy>. Never run it on data/forebear.rl."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forebear.graph import open_graph  # noqa: E402

SRC, DST = "K251889", "K251661"
EARLIER_SHA256 = "0" * 64

db = Path(sys.argv[1]).resolve()
if db.name == "forebear.rl" and db.parent.name == "data":
    sys.exit("refusing to seed the shipped store")
g = open_graph(db)
rows = g.q("""MATCH (:Device {k:$src})-[r:CITES]->(:Device {k:$dst})
    SET r.review = 'confirmed', r.reviewer = 'user', r.review_note = 'e2e seed: reviewed an earlier PDF',
        r.reviewed_at = datetime(), r.reviewed_source_sha256 = $old
    RETURN r.source_sha256 AS current""", {"src": SRC, "dst": DST, "old": EARLIER_SHA256})
g.close()
if not rows or not rows[0]["current"] or rows[0]["current"] == EARLIER_SHA256:
    sys.exit(f"could not seed an outdated review on {SRC} -> {DST}")
