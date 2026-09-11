#!/usr/bin/env python3
"""references/tables/pulse_table.xlsx  ->  site/data/reference/*.json

The workbook is the audited source of truth for the three published pulse
catalogs shown in the site's "Data source" selector. Unlike the older
scripts/import_reference_tables.py (which read a CSV export and re-derived
source models from live USGS lookups), everything here comes straight out of
the workbook's own consolidated sheets -- no network access, no CSV.

    python scripts/build_reference_catalogs.py

Key structure (see references/tables/README.md for the full audit trail):

* Pulse_records  -- fact table, one row per station record. `active_sheet`
  ('S&B' | 'NCREE' | 'YEN') marks the ~701 rows that belong to a site catalog;
  `event_source_key` = "<active_sheet>::<event_key>" joins to Event_sources.
* Event_sources   -- one row per (catalog, event): hypocentre, magnitude,
  mechanism, nodal planes, NGA representative plane, finite-fault summary.
  Keyed by event_source_key because the *same* earthquake can have slightly
  different preferred hypocentres per source (e.g. NGA vs NCREE).
* Finite_fault_segments -- multi-segment USGS finite-fault geometry, keyed by
  the plain event_key (physical model, not source-specific).
"""

from __future__ import annotations

import json
import math
import statistics as st
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "references" / "tables" / "pulse_table.xlsx"
OUT = ROOT / "site" / "data" / "reference"
JWB = "https://www.jackwbaker.com/pulse_classification_v2"
BIN_EDGES = (0, 5, 10, 20, 40, 80, 160)
R_EARTH_KM = 6371.0088

# active_sheet -> catalog id shown on the site (id = the workbook's own sheet
# tab name, lowercased; matches the S&B / NCREE / YEN sheets in pulse_table.xlsx)
ACTIVE_MAP = {"S&B": "sb", "NCREE": "ncree", "YEN": "yen"}

# Catalog display metadata (the workbook has no catalog-label sheet).
CATALOGS = {
    "sb": dict(
        label="S&B", short="S&B 2014",
        citation="Ground motions in the NGA-West2 database that were identified "
                 "as pulse-like using the Shahi and Baker (2014) model.",
        url=f"{JWB}/Pulse-like-records.html", pulse_only=False, sort_order=1),
    "ncree": dict(
        label="NCREE", short="NCREE",
        citation="Database of Near-Fault Strong Motions with Pulse-like "
                 "Velocity from NCREE, using the Shahi and Baker (2014) model.",
        url="https://nfpv.ncree.org.tw/", pulse_only=False, sort_order=2),
    "yen": dict(
        label="YEN", short="YEN",
        citation="Identified pulses from Yen et al.(2022), "
                 "Türker et al. (2024) and Yen et al. (2025), using the "
                 "Shahi and Baker (2014) model.",
        url="", pulse_only=True, sort_order=3),
}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _r(x, n):
    return None if x is None else round(x, n)


def _sheet(wb, name):
    ws = wb[name]
    it = ws.iter_rows(values_only=True)
    head = [str(h).strip() if h is not None else "" for h in next(it)]
    return [dict(zip(head, r)) for r in it]


def haversine_km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R_EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def key(name, year=""):
    import re
    s = re.sub(r"[^a-z0-9]+", "_", f"{name}".lower()).strip("_")
    return f"{s}|{year}" if year else s


def _dist(s):
    """Distance used in every plot: Rrup, else Rhyp when Rrup is missing."""
    return s.get("rrup_km") if s.get("rrup_km") is not None else s.get("rhyp_km")


def _stats(stations):
    pul = [s for s in stations if s["is_pulse"]]
    tps = sorted(s["Tp"] for s in pul if s.get("Tp"))
    pgv = sorted(s["PGV"] for s in pul if s.get("PGV"))
    return {
        "n": len(stations), "n_pulse": len(pul),
        "pulse_fraction": round(len(pul) / len(stations), 3) if stations else None,
        "Tp_median": round(st.median(tps), 3) if tps else None,
        "PGV_median": round(st.median(pgv), 2) if pgv else None,
        "Tp_range": [tps[0], tps[-1]] if tps else [None, None],
        "by_distance": _bins(stations),
        "scatter": [{"code": s["code"], "repi_km": s.get("repi_km"),
                     "rhyp_km": s.get("rhyp_km"), "rrup_km": s.get("rrup_km"),
                     "Tp": s.get("Tp"), "PGV": s.get("PGV"), "is_pulse": s["is_pulse"]}
                    for s in stations if _dist(s) is not None],
    }


def _bins(stations):
    out = []
    for lo, hi in zip(BIN_EDGES, BIN_EDGES[1:]):
        g = [s for s in stations if _dist(s) is not None and lo <= _dist(s) < hi]
        if not g:
            continue
        npul = sum(1 for s in g if s["is_pulse"])
        tps = sorted(s["Tp"] for s in g if s["is_pulse"] and s.get("Tp"))
        out.append({"r_lo": lo, "r_hi": hi, "n": len(g), "n_pulse": npul,
                    "pulse_fraction": round(npul / len(g), 3),
                    "Tp_median": tps[len(tps) // 2] if tps else None})
    return out


def _trace_along_strike(lat, lon, strike, length_km):
    if None in (lat, lon, strike, length_km):
        return None
    kmlat, kmlon = 111.32, 111.32 * math.cos(math.radians(lat))
    s = math.radians(strike)
    dx, dy = math.sin(s), math.cos(s)
    h = length_km / 2.0
    return [[round(lon - h * dx / kmlon, 5), round(lat - h * dy / kmlat, 5)],
            [round(lon + h * dx / kmlon, 5), round(lat + h * dy / kmlat, 5)]]


def _norm_rake(r):
    return None if r is None else ((r + 180) % 360) - 180


def _source_model(ev):
    if ev.get("strike1_deg") is None:
        return None
    two_planes = "nodal plane" in str(ev.get("plane_definition") or "").lower()
    np2 = None if ev.get("strike2_deg") is None else \
        [ev["strike2_deg"], ev.get("dip2_deg"), ev.get("rake2_deg")]
    return dict(np1=[ev["strike1_deg"], ev.get("dip1_deg"), ev.get("rake1_deg")],
                np2=np2,
                source="USGS moment-tensor" if two_planes else "NGA representative fault plane",
                mag=ev.get("catalog_magnitude"),
                mag_type=ev.get("magnitude_type") or "Mww")


def _fault_model(ev, segs):
    lat, lon = ev.get("hypo_latitude_deg"), ev.get("hypo_longitude_deg")
    if segs:
        s0 = segs[0]
        total = sum(s.get("model_length_km") or 0 for s in segs)
        widths = [s.get("model_width_km") or 0 for s in segs]
        width = max(widths) if widths else None
        rmin, rmax = s0.get("rake_min_deg"), s0.get("rake_max_deg")
        rake = _norm_rake((rmin + rmax) / 2) if rmin is not None and rmax is not None else None
        return dict(strike=s0.get("strike_deg"), dip=s0.get("dip_deg"),
                    length_km=_r(total, 1), width_km=_r(width, 1),
                    model="USGS finite-fault inversion",
                    trace=_trace_along_strike(lat, lon, s0.get("strike_deg"), total),
                    rake=_r(rake, 1), segments=len(segs))
    if ev.get("nga_length_km") is not None:
        return dict(strike=ev.get("nga_strike_deg"), dip=ev.get("nga_dip_deg"),
                    length_km=ev["nga_length_km"], width_km=ev.get("nga_width_km"),
                    model="NGA representative fault plane",
                    trace=_trace_along_strike(lat, lon, ev.get("nga_strike_deg"),
                                              ev["nga_length_km"]),
                    rake=ev.get("nga_rake_deg"))
    if ev.get("strike1_deg") is not None and ev.get("catalog_magnitude") is not None:
        m = ev["catalog_magnitude"]
        length = 10 ** (-2.44 + 0.59 * m)
        width = 10 ** (-1.01 + 0.32 * m)
        return dict(strike=ev["strike1_deg"], dip=ev.get("dip1_deg"),
                    length_km=_r(length, 1), width_km=_r(width, 1),
                    model="Wells & Coppersmith (1994) scaling",
                    trace=_trace_along_strike(lat, lon, ev["strike1_deg"], length),
                    rake=ev.get("rake1_deg"))
    return None


def _station(r, ev, cat):
    rsn = str(r["NGA_RSN"]).strip() if r.get("NGA_RSN") not in (None, "") else None
    pgv = _f(r.get("PGV_cm_s"))
    if pgv is None:
        ew, ns = _f(r.get("PGV_EW_original")), _f(r.get("PGV_NS_original"))
        vals = [v for v in (ew, ns) if v is not None]
        pgv = max(vals) if vals else None
    is_pulse = bool(r.get("fault_normal_pulse") == 1 or r.get("Ipulse_H") is True
                   or cat == "yen")
    lat, lon = _f(r.get("latitude_deg")), _f(r.get("longitude_deg"))
    s = dict(
        code=str(r["station_original"]).strip() if r.get("station_original") not in (None, "")
             else r.get("station_key"),
        lat=lat, lon=lon,
        rrup_km=_r(_f(r.get("Rrup_km")) if r.get("Rrup_km") is not None
                   else _f(r.get("closest_distance_km")), 3),
        rhyp_km=_r(_f(r.get("Rhyp_km")), 3),
        is_pulse=is_pulse,
        Tp=_r(_f(r.get("Tp_s")) if r.get("Tp_s") is not None else _f(r.get("Tp_H_s")), 3),
        PGV=_r(pgv, 3),
        vs30=_r(_f(r.get("vs30_original")), 3),
        ori_n=_r(_f(r.get("orientation_north_deg")), 3),
        ori_fp=_r(_f(r.get("orientation_fault_parallel_deg")), 3),
        fling={True: True, False: False}.get(r.get("fling")),
        directivity=True if r.get("directivity_effect") == 1 else None,
        rsn=rsn,
        summary_url=f"{JWB}/{rsn}.html" if rsn and cat == "sb" else None,
        quality_flag=str(r["quality_flag"]) if r.get("quality_flag") not in (None, "") else None,
        coord_status=r.get("coord_status") if r.get("coord_status") not in (None, "matched") else None,
        repi_km=_r(haversine_km(ev.get("hypo_latitude_deg"), ev.get("hypo_longitude_deg"),
                                 lat, lon), 2) if lat is not None else None,
    )
    return {k: v for k, v in s.items() if v is not None or k in ("lat", "lon", "code", "is_pulse")}


def build():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    pulse_rows = [r for r in _sheet(wb, "Pulse_records") if r.get("active_sheet")]
    ev_by_key = {r["event_source_key"]: r for r in _sheet(wb, "Event_sources")
                 if r.get("event_source_key")}
    segs_by_event = {}
    for r in _sheet(wb, "Finite_fault_segments"):
        if r.get("event_key"):
            segs_by_event.setdefault(r["event_key"], []).append(r)
    for segs in segs_by_event.values():
        segs.sort(key=lambda s: s.get("segment") or 0)

    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for cat_id, meta in sorted(CATALOGS.items(), key=lambda kv: kv[1]["sort_order"]):
        rows = [r for r in pulse_rows if ACTIVE_MAP.get(r["active_sheet"]) == cat_id]
        by_esk = {}
        for r in rows:
            by_esk.setdefault(r["event_source_key"], []).append(r)

        events = []
        for esk, recs in by_esk.items():
            ev = ev_by_key[esk]
            stations = [_station(r, ev, cat_id) for r in recs]
            segs = segs_by_event.get(ev["event_key"], [])
            fault = _fault_model(ev, segs)
            sm = _source_model(ev)
            names = ev.get("event_names") or ev["event_key"]
            out = dict(
                key=key(str(names).split("|")[0].strip(), ev["event_key"][:4]
                        if ev["event_key"][:4].isdigit() else ""),
                name=str(names).split("|")[0].strip(),
                year=ev["event_key"][:4] if ev["event_key"][:4].isdigit() else None,
                lat=ev.get("hypo_latitude_deg"), lon=ev.get("hypo_longitude_deg"),
                depth_km=ev.get("hypo_depth_km"), mag=ev.get("catalog_magnitude"),
                fault_type=ev.get("mechanism"),
                stations=stations, stats=_stats(stations),
                n_mappable=sum(1 for s in stations if s.get("lat") is not None),
            )
            if fault:
                out["fault"] = fault
            if sm:
                out["source_model"] = sm
            if ev.get("source_url"):
                out["usgs_url"] = ev["source_url"]
            events.append(out)
        events.sort(key=lambda e: (e.get("year") or "", e["name"]))

        doc = dict(schema="pulse-extraction/reference/2", catalog=cat_id,
                   label=meta["label"], short=meta["short"], citation=meta["citation"],
                   url=meta["url"], pulse_only=meta["pulse_only"],
                   n_events=len(events), n_records=sum(e["stats"]["n"] for e in events),
                   events=events)
        (OUT / f"{cat_id}.json").write_text(json.dumps(doc, indent=1) + "\n")
        n_rec = doc["n_records"]
        print(f"{cat_id:18} {len(events):3} events  {n_rec:4} records")
        index.append(dict(id=cat_id, label=meta["label"], short=meta["short"],
                          url=meta["url"], n_events=len(events), n_records=n_rec,
                          pulse_only=meta["pulse_only"]))

    (OUT / "index.json").write_text(json.dumps({"catalogs": index}, indent=1) + "\n")
    print(f"\nwrote {OUT}/index.json  ({len(index)} catalogs)")


def main():
    if not XLSX.exists():
        sys.exit(f"missing {XLSX}")
    build()


if __name__ == "__main__":
    main()
