"""scripts/d1_pipeline.py: pipeline results as SQL against db/schema.sql."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import d1_pipeline  # noqa: E402


def _db():
    db = sqlite3.connect(":memory:")
    db.executescript((ROOT / "db" / "schema.sql").read_text())
    return db


def _summary(codes, name="Kahramanmaraş 'M7.8'"):
    return {"schema": "s", "generated": "g", "pipeline": {"method": "kamai"},
            "event": {"id": "us6000jllz", "name": name, "time": "2023-02-06T01:17:34",
                      "mag": 7.8},
            "stations": [{"code": c, "is_pulse": True, "Tp": 5.0} for c in codes],
            "stats": {"n": len(codes)}, "key": "ignored"}


def test_event_round_trip():
    db = _db()
    db.executescript("\n".join(d1_pipeline.event_statements("live_x", _summary(["A", "B"]),
                                                            updated="2026-10-02")))
    key, usgs, mag, doc = db.execute(
        "SELECT key, usgs_id, mag, doc FROM pipeline_events").fetchone()
    doc = json.loads(doc)
    assert (key, usgs, mag) == ("live_x", "us6000jllz", 7.8)
    assert doc["event"]["name"] == "Kahramanmaraş 'M7.8'"
    assert not {"stations", "stats", "key"} & set(doc)
    codes = [r[0] for r in db.execute("SELECT code FROM pipeline_records ORDER BY ord")]
    assert codes == ["A", "B"]
    assert db.execute("SELECT updated FROM site_catalogs WHERE id='pipeline'"
                      ).fetchone()[0] == "2026-10-02"


def test_saving_again_replaces_the_records():
    db = _db()
    for codes in (["A", "B", "C"], ["D"]):
        db.executescript("\n".join(d1_pipeline.event_statements("k", _summary(codes))))
    assert db.execute("SELECT COUNT(*) FROM pipeline_events").fetchone()[0] == 1
    assert [r[0] for r in db.execute("SELECT code FROM pipeline_records")] == ["D"]


def test_schema_is_idempotent_and_keeps_edits():
    db = _db()
    db.execute("UPDATE site_catalogs SET label = 'edited' WHERE id = 'sb'")
    db.executescript((ROOT / "db" / "schema.sql").read_text())
    assert db.execute("SELECT label FROM site_catalogs WHERE id='sb'").fetchone()[0] == "edited"
    assert db.execute("SELECT COUNT(*) FROM site_catalogs").fetchone()[0] == 4
