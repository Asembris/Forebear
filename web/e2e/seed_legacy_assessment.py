"""Give the throwaway e2e store one saved assessment of K251770 as it was stored before the query depth was kept on
the node: no `depth` property, the depth only inside its payload. It was computed at depth 1, where K251770 reports
no design-recall signal (depth 2 and deeper report REVIEW_LINEAGE), so rechecking it at any other depth would wrongly
call it stale. Run by e2e/server.mjs startIsolatedApi on a fresh store copy before its API opens it; never on
data/forebear.rl."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forebear.graph import open_graph  # noqa: E402

K, AID, VERDICT = "K251770", "A-e2elegacy1", "NO_DESIGN_RECALL_SIGNAL"

db = Path(sys.argv[1]).resolve()
if db.name == "forebear.rl" and db.parent.name == "data":
    sys.exit("refusing to seed the shipped store")
g = open_graph(db)
rows = g.q("""MATCH (d:Device {k:$k})
    CREATE (a:Assessment {id:$id, created_at: datetime(), target_k:$k, verdict:$v, payload:$p,
                          memo:'e2e seed: saved before depth was stored', memo_source:'template'})-[:ASSESSED]->(d)
    RETURN a.id AS id""", {"k": K, "id": AID, "v": VERDICT, "p": json.dumps({"verdict": VERDICT, "depth": 1})})
g.close()
if not rows:
    sys.exit(f"could not seed a legacy assessment on {K}")
