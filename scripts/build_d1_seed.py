#!/usr/bin/env python3
"""site/data/*.json  ->  db/seed.sql  (Cloudflare D1, served by functions/api/)

The static JSON stays the build output of the pipeline (build_site_data.py)
and of the reference catalogs (build_reference_catalogs.py); this script loads
exactly those files into D1, so the API and the static fallback cannot drift.

    python scripts/build_d1_seed.py
    wrangler d1 execute pulse_db --remote --file db/seed.sql --yes

The seed starts with db/schema.sql (DROP + CREATE), so every load is a full
rebuild.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
SCHEMA = ROOT / "db" / "schema.sql"
OUT = ROOT / "db" / "seed.sql"

# list-entry fields kept for a reference event (the rest lives in `doc`)
REF_SUMMARY = ("key", "name", "year", "lat", "lon", "depth_km", "mag")


def sql(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    if not isinstance(v, str):
        v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return "'" + v.replace("'", "''") + "'"


def dist(s: dict):
    """Rrup, else Rhyp -- same rule as build_reference_catalogs._dist."""
    return s.get("rrup_km") if s.get("rrup_km") is not None else s.get("rhyp_km")


def insert(table: str, row: dict) -> str:
    cols = ", ".join(row)
    vals = ", ".join(sql(v) for v in row.values())
    return f"INSERT INTO {table} ({cols}) VALUES ({vals});"


def event_rows(catalog: str, ord_: int, key: str, mag, doc: dict,
               summary: dict, stations: list[dict]) -> list[str]:
    out = [insert("events", {"catalog": catalog, "key": key, "ord": ord_,
                             "mag": mag, "doc": doc, "summary": summary})]
    for i, s in enumerate(stations):
        out.append(insert("records", {
            "catalog": catalog, "event_key": key, "ord": i,
            "is_pulse": bool(s.get("is_pulse")), "Tp": s.get("Tp"),
            "PGV": s.get("PGV"), "dist_km": dist(s), "doc": s}))
    return out


def build() -> tuple[list[str], dict]:
    stmts: list[str] = []
    counts: dict[str, tuple[int, int]] = {}

    # pipeline: data/index.json (list order) + data/events/<key>.json (detail)
    pipe = json.loads((DATA / "index.json").read_text())
    stmts.append(insert("catalogs", {
        "id": "pipeline", "ord": 0, "kind": "pipeline",
        "doc": {"label": "Pipeline results", "generated": pipe.get("generated")}}))
    n_rec = 0
    for i, row in enumerate(pipe["events"]):
        d = json.loads((DATA / "events" / f"{row['key']}.json").read_text())
        stations = d.pop("stations")
        d["stats_all"] = d.pop("stats")
        stmts += event_rows("pipeline", i, row["key"], d["event"].get("mag"),
                            d, row, stations)
        n_rec += len(stations)
    counts["pipeline"] = (len(pipe["events"]), n_rec)

    # reference catalogs: data/reference/index.json + one file per catalog
    ref_idx = json.loads((DATA / "reference" / "index.json").read_text())
    for c_ord, meta in enumerate(ref_idx["catalogs"], start=1):
        doc = json.loads((DATA / "reference" / f"{meta['id']}.json").read_text())
        cat = {**meta, "citation": doc.get("citation")}
        stmts.append(insert("catalogs", {"id": meta["id"], "ord": c_ord,
                                         "kind": "reference", "doc": cat}))
        n_rec = 0
        for i, e in enumerate(doc["events"]):
            e = dict(e)
            stations = e.pop("stations")
            e["stats_all"] = e.pop("stats")
            summary = {k: e.get(k) for k in REF_SUMMARY}
            stmts += event_rows(meta["id"], i, e["key"], e.get("mag"),
                                e, summary, stations)
            n_rec += len(stations)
        counts[meta["id"]] = (len(doc["events"]), n_rec)
    return stmts, counts


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    stmts, counts = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(SCHEMA.read_text() + "\n" + "\n".join(stmts) + "\n")
    for cid, (ne, nr) in counts.items():
        print(f"{cid:<10} {ne:4d} events {nr:5d} records")
    print(f"wrote {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}"
          f"  ({len(stmts)} statements)")


if __name__ == "__main__":
    main()
