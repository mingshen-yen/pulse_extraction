#!/usr/bin/env python3
"""Check the D1-backed /api/* against site/data/*.json.

* No filters: every catalog's event list and every event document must match
  the static files exactly.
* With filters: the matching events, their record counts and the recomputed
  stats must equal what the same filters give on the static records.

    wrangler pages dev                       # serves site/ + functions/ locally
    python scripts/check_api_parity.py http://localhost:8788
    python scripts/check_api_parity.py https://pulse-extraction.pages.dev
"""

from __future__ import annotations

import json
import statistics as st
import sys
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "site" / "data"

FILTER_CASES = [
    {"mag_min": 7},
    {"mag_min": 6, "mag_max": 6.9},
    {"tp_min": 2, "tp_max": 5},
    {"dist_max": 10},
    {"dist_min": 20, "tp_min": 1},
    {"mag_min": 7, "tp_min": 3, "dist_max": 15},
    {"mag_min": 9.5},                         # nothing matches
]
STAT_KEYS = ("n", "n_pulse", "pulse_fraction", "Tp_median", "PGV_median", "Tp_range")


def get(base: str, path: str, **params):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{base}/api/{path}?{q}", timeout=30) as r:
        return json.load(r)


def static_catalogs() -> dict[str, dict]:
    """catalog id -> {'list': [...], 'docs': {key: event doc with stations}}"""
    out = {}
    pipe = json.loads((DATA / "index.json").read_text())
    out["pipeline"] = {
        "list": pipe["events"],
        "docs": {e["key"]: json.loads((DATA / "events" / f"{e['key']}.json").read_text())
                 for e in pipe["events"]},
    }
    for c in json.loads((DATA / "reference" / "index.json").read_text())["catalogs"]:
        doc = json.loads((DATA / "reference" / f"{c['id']}.json").read_text())
        out[c["id"]] = {"list": doc["events"], "docs": {e["key"]: e for e in doc["events"]}}
    return out


def mag_of(doc: dict):
    return doc["event"].get("mag") if "event" in doc else doc.get("mag")


def dist(s):
    return s.get("rrup_km") if s.get("rrup_km") is not None else s.get("rhyp_km")


def keep(s: dict, f: dict) -> bool:
    for name, val, lo in (("tp", s.get("Tp"), True), ("tp", s.get("Tp"), False),
                          ("dist", dist(s), True), ("dist", dist(s), False)):
        bound = f.get(f"{name}_{'min' if lo else 'max'}")
        if bound is None:
            continue
        if val is None or (val < bound if lo else val > bound):
            return False
    return True


def expected_stats(stations: list[dict]) -> dict:
    pul = [s for s in stations if s["is_pulse"]]
    tps = sorted(s["Tp"] for s in pul if s.get("Tp"))
    pgv = sorted(s["PGV"] for s in pul if s.get("PGV"))
    return {
        "n": len(stations), "n_pulse": len(pul),
        "pulse_fraction": round(len(pul) / len(stations), 3) if stations else None,
        "Tp_median": round(st.median(tps), 3) if tps else None,
        "PGV_median": round(st.median(pgv), 2) if pgv else None,
        "Tp_range": [tps[0], tps[-1]] if tps else [None, None],
    }


def close(a, b) -> bool:
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(map(close, a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-3 * max(1, abs(a))
    return a == b


def main(base: str) -> int:
    base = base.rstrip("/")
    static = static_catalogs()
    errors: list[str] = []

    api_ids = [c["id"] for c in get(base, "catalogs")["catalogs"]]
    if api_ids != list(static):
        errors.append(f"catalogs: api {api_ids} != static {list(static)}")

    for cid, s in static.items():
        # unfiltered: list and documents identical to the static files
        api_list = get(base, "events", catalog=cid)["events"]
        want = [e["key"] for e in s["list"]]
        if [e["key"] for e in api_list] != want:
            errors.append(f"{cid}: unfiltered event order differs")
        for key, doc in s["docs"].items():
            got = get(base, "event", catalog=cid, key=key)
            got.pop("filters", None)
            if got != doc:
                errors.append(f"{cid}/{key}: unfiltered document differs")

        # filtered: same answer as filtering the static records
        for f in FILTER_CASES:
            exp = {}
            for e in s["list"]:
                doc = s["docs"][e["key"]]
                m = mag_of(doc)
                if "mag_min" in f and (m is None or m < f["mag_min"]):
                    continue
                if "mag_max" in f and (m is None or m > f["mag_max"]):
                    continue
                hit = [x for x in doc["stations"] if keep(x, f)]
                if hit:
                    exp[e["key"]] = hit
            got = get(base, "events", catalog=cid, **f)["events"]
            if [e["key"] for e in got] != list(exp):
                errors.append(f"{cid} {f}: events {len(got)} != expected {len(exp)}")
                continue
            for e in got:
                if (e["n"], e["n_pulse"]) != (len(exp[e["key"]]),
                                              sum(x["is_pulse"] for x in exp[e["key"]])):
                    errors.append(f"{cid} {f} {e['key']}: counts differ")
            for key in list(exp)[:5]:
                d = get(base, "event", catalog=cid, key=key, **f)
                if [x["code"] for x in d["stations"]] != [x["code"] for x in exp[key]]:
                    errors.append(f"{cid} {f} {key}: stations differ")
                if any(("tp_min" in f or "tp_max" in f or "dist_min" in f
                        or "dist_max" in f) and not close(d["stats"][k], v)
                       for k, v in expected_stats(exp[key]).items()):
                    errors.append(f"{cid} {f} {key}: stats differ "
                                  f"{ {k: d['stats'][k] for k in STAT_KEYS} }")
        print(f"{cid:<10} checked {len(s['docs'])} events, {len(FILTER_CASES)} filter sets")

    for e in errors:
        print("FAIL", e)
    print("OK" if not errors else f"{len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8788"))
