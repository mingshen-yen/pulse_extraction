"""scripts/build_d1_seed.py: the generated SQL loads into SQLite (what D1 runs)
and holds exactly what site/data/*.json holds."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_d1_seed  # noqa: E402

DATA = ROOT / "site" / "data"


def _load(tmp_path):
    out = tmp_path / "seed.sql"
    build_d1_seed.main(["-o", str(out)])
    db = sqlite3.connect(":memory:")
    db.executescript(out.read_text())
    return db


def test_counts_match_static_files(tmp_path):
    db = _load(tmp_path)
    for c in json.loads((DATA / "reference" / "index.json").read_text())["catalogs"]:
        n_ev, n_rec = db.execute(
            "SELECT (SELECT COUNT(*) FROM events WHERE catalog=?),"
            "       (SELECT COUNT(*) FROM records WHERE catalog=?)", (c["id"], c["id"])
        ).fetchone()
        assert (n_ev, n_rec) == (c["n_events"], c["n_records"])
    pipe = json.loads((DATA / "index.json").read_text())["events"]
    assert db.execute("SELECT COUNT(*) FROM events WHERE catalog='pipeline'"
                      ).fetchone()[0] == len(pipe)


def test_documents_round_trip(tmp_path):
    db = _load(tmp_path)
    ev = json.loads((DATA / "reference" / "yen.json").read_text())["events"][0]
    doc, = db.execute("SELECT doc FROM events WHERE catalog='yen' AND key=?",
                      (ev["key"],)).fetchone()
    doc = json.loads(doc)
    assert doc.pop("stats_all") == ev["stats"]
    rows = db.execute("SELECT doc FROM records WHERE catalog='yen' AND event_key=? "
                      "ORDER BY ord", (ev["key"],)).fetchall()
    assert {**doc, "stations": [json.loads(r[0]) for r in rows], "stats": ev["stats"]} == ev


def test_dist_is_rrup_else_rhyp(tmp_path):
    db = _load(tmp_path)
    for dist, doc in db.execute("SELECT dist_km, doc FROM records"):
        s = json.loads(doc)
        want = s.get("rrup_km") if s.get("rrup_km") is not None else s.get("rhyp_km")
        assert dist == want


def test_quotes_are_escaped():
    assert build_d1_seed.sql("Kahramanmaraş 'M7.8'") == "'Kahramanmaraş ''M7.8'''"
    assert build_d1_seed.sql(None) == "NULL" and build_d1_seed.sql(True) == "1"
