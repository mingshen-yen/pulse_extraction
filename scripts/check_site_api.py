#!/usr/bin/env python3
"""Sanity-check the live data API (D1 is the source of truth, so this is where
the data is checked): every catalog and event loads, coordinates are valid,
no negative distances / Tp / PGV, no duplicate event-station pairs, no local
file paths reach the public responses, and the filters behave.

    python scripts/check_site_api.py https://mingslab.com/pulse_database
    python scripts/check_site_api.py http://localhost:8788       # wrangler pages dev
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

LEAKS = ("/Users/", "/Volumes/", "/home/", "file://", "C:\\")


def get(base: str, path: str, **params) -> tuple[dict, str]:
    q = urllib.parse.urlencode(params)
    # Cloudflare turns away urllib's default User-Agent with a 403
    req = urllib.request.Request(f"{base}/api/{path}?{q}",
                                 headers={"User-Agent": "pulse-extraction-site-check"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
    return json.loads(raw), raw


def coords_ok(lat, lon) -> bool:
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def check_event(cid: str, kind: str, doc: dict, problems: list[str]) -> None:
    ev = doc["event"] if kind == "pipeline" else doc
    where = f"{cid}/{doc['key']}"
    if not coords_ok(ev.get("lat"), ev.get("lon")):
        problems.append(f"{where}: invalid event coordinates")
    seen = set()
    for s in doc["stations"]:
        if kind == "reference" and s["code"] in seen:
            problems.append(f"{where}: duplicate station {s['code']}")
        seen.add(s["code"])
        if kind == "reference" and not coords_ok(s.get("lat"), s.get("lon")):
            problems.append(f"{where}/{s['code']}: missing or invalid coordinates")
        for f in ("rrup_km", "rhyp_km", "repi_km", "Tp", "PGV"):
            if (s.get(f) or 0) < 0:
                problems.append(f"{where}/{s['code']}: negative {f}")
    url = doc.get("usgs_url")
    if url and not url.startswith("https://earthquake.usgs.gov/"):
        problems.append(f"{where}: unexpected usgs_url {url}")


def main(base: str) -> int:
    base = base.rstrip("/")
    problems: list[str] = []
    cats, raw = get(base, "catalogs")
    for c in cats["catalogs"]:
        lst, raw_list = get(base, "events", catalog=c["id"])
        if lst["n_events"] != c["n_events"] or lst["n_records"] != c["n_records"]:
            problems.append(f"{c['id']}: list counts differ from /api/catalogs")
        if c["n_events"] == 0:
            problems.append(f"{c['id']}: no events")
        texts = [raw, raw_list]
        for e in lst["events"]:
            doc, raw_doc = get(base, "event", catalog=c["id"], key=e["key"])
            texts.append(raw_doc)
            check_event(c["id"], c["kind"], doc, problems)
        problems += [f"{c['id']}: response contains {leak!r}"
                     for leak in LEAKS if any(leak in t for t in texts)]

        # filters only ever narrow, and every kept record satisfies them
        for f in ({"tp_min": 3}, {"dist_max": 10}, {"mag_min": 7}):
            sub, _ = get(base, "events", catalog=c["id"], **f)
            if sub["n_records"] > c["n_records"]:
                problems.append(f"{c['id']} {f}: filter widened the result")
            for e in sub["events"][:3]:
                d, _ = get(base, "event", catalog=c["id"], key=e["key"], **f)
                for s in d["stations"]:
                    dist = s.get("rrup_km") if s.get("rrup_km") is not None else s.get("rhyp_km")
                    if ("tp_min" in f and (s.get("Tp") is None or s["Tp"] < f["tp_min"])) or \
                       ("dist_max" in f and (dist is None or dist > f["dist_max"])):
                        problems.append(f"{c['id']} {f}: {e['key']}/{s['code']} slipped through")
        print(f"{c['id']:<10} {c['n_events']:4d} events {c['n_records']:5d} records")

    for p in problems:
        print("FAIL", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8788"))
