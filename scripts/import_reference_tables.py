#!/usr/bin/env python3
"""Build the showcase-site reference catalogs from the consolidated pulse table
``references/tables/pulse_records_with_coords.csv``.

    python scripts/import_reference_tables.py
    python scripts/import_reference_tables.py --no-net    # skip the USGS lookups

The master CSV merges several published pulse tables into one row-per-record
sheet with station coordinates already resolved (``latitude_deg`` /
``longitude_deg`` / ``coord_status``).  One catalog is emitted per source sheet
(``site/data/reference/<catalog>.json`` + ``index.json``):

* ``shahi_baker_2014`` -- ``Baker(2014)`` sheet: 243 records, NGA-West2, with
  fault-normal-pulse flags; each record links to its jackwbaker.com page.
* ``taiwan_ncree``     -- ``Taiwan database(NCREE)`` sheet: 340 records with
  event hypocentres.
* ``yen_2022``         -- ``Yen(2022)`` sheet: 84 near-fault pulse records.

Each event is also given a **schematic source model** from USGS ComCat (cached
in ``_cache/``): moment-tensor / focal-mechanism nodal planes, and a single
surface rupture trace (``fault["trace"] = [[lon,lat], [lon,lat]]``) -- the
along-strike extent of the USGS finite-fault slip model where one exists
(7 events), otherwise a line of the magnitude-scaled length (Wells &
Coppersmith 1994) through the epicentre, bearing nodal plane 1's strike.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from waveform.site_export import haversine_km                     # noqa: E402

MASTER = ROOT / "references" / "tables" / "pulse_records_with_coords.csv"
OUT = ROOT / "site" / "data" / "reference"
CACHE = OUT / "_cache"
JWB = "https://www.jackwbaker.com/pulse_classification_v2"

CATALOGS = {
    "shahi_baker_2014": dict(
        sheet="Baker(2014)", pulse_only=False,
        label="Shahi & Baker (2014)", short="S&B 2014",
        citation="Shahi, S.K. & Baker, J.W. (2014). An efficient algorithm to "
                 "identify strong-velocity pulses in multicomponent ground "
                 "motions. BSSA 104(5). Pulse-like-records list.",
        url=f"{JWB}/Pulse-like-records.html"),
    "taiwan_ncree": dict(
        sheet="Taiwan database(NCREE)", pulse_only=False,
        label="NCREE Taiwan pulse database", short="NCREE",
        citation="NCREE near-fault pulse-like ground-motion database, Taiwan "
                 "(updated). Hypocentre & station coordinates included.",
        url="https://www.ncree.org/"),
    "yen_2022": dict(
        sheet="Yen(2022)", pulse_only=True,
        label="Yen et al. (2022)", short="Yen 2022",
        citation="Yen et al. (2022) near-fault velocity-pulse catalog "
                 "(Darfield, Meinong, Hualien, Kumamoto, Iburi).",
        url=""),
}

# fallback epicentres for events with no hypocentre in the table and none in
# the NCREE sheet.  lat, lon, depth_km, mag
EXTRA_EPI = {
    "loma_prieta|1989": (37.04, -121.88, 17.5, 6.93),
    "chuetsu_oki|2007": (37.54, 138.45, 10.0, 6.8),
    "whittier_narrows_01|1987": (34.05, -118.08, 14.6, 5.99),
    "coalinga_02|1983": (36.23, -120.32, 10.0, 5.09),
    "coalinga_05|1983": (36.24, -120.28, 8.4, 5.77),
    "coalinga_07|1983": (36.17, -120.27, 9.6, 5.21),
    "wenchuan_china|2008": (31.00, 103.40, 19.0, 7.9),
    "iwate|2008": (39.03, 140.88, 7.8, 6.9),
    "niigata_japan|2004": (37.31, 138.83, 13.0, 6.63),
    "morgan_hill|1984": (37.31, -121.68, 8.4, 6.19),
    "san_fernando|1971": (34.44, -118.41, 8.4, 6.61),
    "tottori_japan|2000": (35.27, 133.35, 10.0, 6.61),
    "kalamata_greece_02|1986": (37.04, 22.14, 8.0, 5.4),
    "westmorland|1981": (33.10, -115.62, 2.4, 5.9),
    "n_palm_springs|1986": (33.99, -116.61, 11.0, 6.06),
    "joshua_tree_ca|1992": (33.96, -116.32, 12.3, 6.1),
    "mammoth_lakes_06|1980": (37.56, -118.83, 14.0, 5.94),
    "san_salvador|1986": (13.67, -89.16, 7.3, 5.8),
    "northern_calif_03|1954": (40.29, -124.05, 15.0, 6.5),
    "northwest_china_03|1997": (35.07, 87.33, 10.0, 6.1),
    "imperial_valley_07|1979": (32.93, -115.51, 8.0, 5.01),
    "taiwan_smart1_40|1986": (24.68, 121.77, 8.0, 6.32),
    "yountville|2000": (38.38, -122.41, 10.1, 5.0),
    "kumafore|2016": (32.74, 130.81, 11.4, 6.1),
    "iburi|2018": (42.69, 141.93, 37.0, 6.6),
}

# Shahi & Baker / Yen event key  ->  NCREE-sheet event key (for hypocentre join)
_NCREE_ALIASES = {
    "chi_chi_taiwan": "1999_chichi_taiwan", "chi_chi_taiwan_03": "1999_chichi_03_taiwan",
    "chi_chi_taiwan_04": "1999_chichi_07_taiwan", "chi_chi_taiwan_06": "1999_chichi_05_taiwan",
    "northridge_01": "1994_northridge_01_usa", "imperial_valley_06": "1979_imperialvalley_06_usa",
    "parkfield_02_ca": "2004_parkfield_02_ca", "darfield_new_zealand": "2010_darfield_newzealand",
    "christchurch_new_zealand": "2011_christchurch_newzealand", "kobe_japan": "1995_kobe_japan",
    "kocaeli_turkey": "1999_kocaeli_turkey", "duzce_turkey": "1999_duzce_turkey",
    "cape_mendocino": "1992_capemendocino_usa", "coyote_lake": "1979_coyotelake_usa",
    "landers": "1992_landers_usa", "el_mayor_cucapah": "2010_elmayor_cucapah_mexico",
    "superstition_hills_02": "1987_superstitionhills_02_usa", "l_aquila_italy": "2009_laquila_italy",
    "montenegro_yugo": "1979_montenegro_yugoslavia", "irpinia_italy_01": "1980_irpinia_01_italy",
    "denali_alaska": "2002_denali_alaska", "tabas_iran": "1978_tabas_iran", "bam_iran": "2003_bam_iran",
    "kumamoto": "2016_kumamoto_japan", "meinong": "2016_meinong_taiwan",
    "hualien": "2018_hualien_taiwan", "darfield": "2010_darfield_newzealand",
}


def key(name, year=""):
    s = re.sub(r"[^a-z0-9]+", "_", f"{name}".lower()).strip("_")
    return f"{s}|{year}" if year else s


def _f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _bool(x):
    v = str(x).strip().lower()
    return True if v in ("true", "1", "1.0") else False if v in ("false", "0", "0.0") else None


# --------------------------------------------------------------------------- #
# stats (unchanged frontend contract)
# --------------------------------------------------------------------------- #
def _dist(s):
    return s.get("rrup_km") if s.get("rrup_km") is not None else s.get("repi_km")


def _stats(stations):
    import statistics as st
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
                     "rrup_km": s.get("rrup_km"), "Tp": s.get("Tp"),
                     "PGV": s.get("PGV"), "is_pulse": s["is_pulse"]}
                    for s in stations if _dist(s) is not None],
    }


def _bins(stations, edges=(0, 5, 10, 20, 40, 80, 160)):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        g = [s for s in stations if _dist(s) is not None and lo <= _dist(s) < hi]
        if not g:
            continue
        npul = sum(1 for s in g if s["is_pulse"])
        tps = sorted(s["Tp"] for s in g if s["is_pulse"] and s.get("Tp"))
        out.append({"r_lo": lo, "r_hi": hi, "n": len(g), "n_pulse": npul,
                    "pulse_fraction": round(npul / len(g), 3),
                    "Tp_median": tps[len(tps) // 2] if tps else None})
    return out


# --------------------------------------------------------------------------- #
# USGS ComCat source model (moment tensor / focal mechanism / finite fault)
# --------------------------------------------------------------------------- #
USGS = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def _cached(name, fetch, no_net):
    p = CACHE / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if no_net and p.exists():
        return p.read_text()
    if not no_net:
        try:
            txt = fetch()
            p.write_text(txt)
            return txt
        except Exception as exc:                                  # noqa: BLE001
            print(f"  fetch {name} failed ({exc}); using cache")
    return p.read_text() if p.exists() else ""


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "pulse-extraction/site"})
    with urllib.request.urlopen(req, timeout=timeout) as r:       # noqa: S310
        return r.read().decode("utf-8", "replace")


def _trace_along_strike(lat, lon, strike, length_km):
    """A straight surface rupture trace: ``[[lon,lat], [lon,lat]]`` of
    ``length_km``, bearing ``strike``, centred on ``lat, lon``."""
    kmlat, kmlon = 111.32, 111.32 * math.cos(math.radians(lat))
    s = math.radians(strike)
    dx, dy = math.sin(s), math.cos(s)                 # unit strike vector (E, N)
    h = length_km / 2.0
    return [[round(lon - h * dx / kmlon, 5), round(lat - h * dy / kmlat, 5)],
            [round(lon + h * dx / kmlon, 5), round(lat + h * dy / kmlat, 5)]]


def _hull_trace(hull, strike, cen_lat):
    """Surface trace of a fault footprint = its extent projected onto the
    strike direction, drawn through the footprint centroid."""
    kmlat = 111.32
    kmlon = 111.32 * math.cos(math.radians(cen_lat))
    s = math.radians(strike)
    ux, uy = math.sin(s), math.cos(s)                 # unit strike (E, N)
    cx = sum(p[0] for p in hull[:-1]) / (len(hull) - 1)
    cy = sum(p[1] for p in hull[:-1]) / (len(hull) - 1)
    proj = [((p[0] - cx) * kmlon * ux + (p[1] - cy) * kmlat * uy)
            for p in hull[:-1]]
    lo, hi = min(proj), max(proj)
    return [[round(cx + lo * ux / kmlon, 5), round(cy + lo * uy / kmlat, 5)],
            [round(cx + hi * ux / kmlon, 5), round(cy + hi * uy / kmlat, 5)]]


def _mag_scaled_trace(lat, lon, mag, strike, dip):
    length = 10 ** (-2.44 + 0.59 * mag)              # Wells & Coppersmith (1994)
    width = 10 ** (-1.01 + 0.32 * mag)
    return dict(strike=strike, dip=dip, length_km=round(length, 1),
                width_km=round(width, 1),
                model="Wells & Coppersmith (1994) scaling",
                trace=_trace_along_strike(lat, lon, strike, length))


def _convex_hull(pts):
    """Andrew's monotone chain: outline of a [lon,lat] point cloud, closed ring."""
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(pts) < 3:
        return [list(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    ring = lo[:-1] + hi[:-1]
    return [list(p) for p in ring] + [list(ring[0])]


def ffm_outline(usgs_id, contents, no_net):
    """USGS finite-fault ``FFM.geojson`` -> a single **schematic footprint**
    polygon (convex hull of the subfaults with slip >= 15 % of the peak) plus
    the peak slip.  ``None`` if the model can't be read."""
    geo_key = next((k for k in contents if k.lower().endswith(".geojson")), None)
    if not geo_key:
        return None
    raw = _cached(f"ffm/{usgs_id}.geojson",
                  lambda: _get(contents[geo_key]["url"], timeout=90), no_net)
    if not raw:
        return None
    try:
        feats = json.loads(raw).get("features", [])
    except json.JSONDecodeError:
        return None
    quads, smax = [], 0.0
    for ft in feats:
        slip = _f(ft.get("properties", {}).get("slip"))
        ring = (ft.get("geometry") or {}).get("coordinates", [[]])[0]
        if slip is None or len(ring) < 4:
            continue
        smax = max(smax, slip)
        quads.append((slip, [(x, y) for x, y, *_ in ring]))
    if not quads:
        return None
    pts = [xy for slip, r in quads if slip >= 0.15 * smax for xy in r] \
        or [xy for _, r in quads for xy in r]
    return _convex_hull(pts), round(smax, 2)


def _np(props, i):
    try:
        return [float(props[f"nodal-plane-{i}-strike"]),
                float(props.get(f"nodal-plane-{i}-dip", 45)),
                float(props.get(f"nodal-plane-{i}-rake", 0))]
    except (KeyError, TypeError, ValueError):
        return None


def usgs_source_model(lat, lon, year, mag, no_net=False):
    if lat is None or year is None:
        return None
    # year-only window: a tight search radius pins the event by place so a
    # nearby larger event in the same year (Kocaeli vs Düzce 1999) is not matched.
    q = dict(format="geojson", orderby="magnitude", limit=3,
             latitude=lat, longitude=lon, maxradiuskm=60,
             minmagnitude=(mag or 5) - 0.5,
             starttime=f"{year}-01-01", endtime=f"{int(year) + 1}-01-01")
    tag = re.sub(r"\W+", "_", f"{lat}_{lon}_{year}_{mag}_r60m05")
    idx = _cached(f"usgs/find_{tag}.json",
                  lambda: _get(f"{USGS}?{urllib.parse.urlencode(q)}"), no_net)
    feats = json.loads(idx).get("features", []) if idx else []
    # keep the closest candidate within 55 km whose magnitude is within 0.6
    feats = sorted(
        (f for f in feats
         if haversine_km(lat, lon, f["geometry"]["coordinates"][1],
                         f["geometry"]["coordinates"][0]) <= 55
         and (not mag or not f["properties"].get("mag")
              or abs(f["properties"]["mag"] - mag) <= 0.6)),
        key=lambda f: haversine_km(lat, lon, f["geometry"]["coordinates"][1],
                                   f["geometry"]["coordinates"][0]))
    if not feats:
        return None
    p = feats[0]["properties"]
    c = feats[0]["geometry"]["coordinates"]
    det = None
    if p.get("detail"):
        dtag = "usgs/" + re.sub(r"\W+", "_", p["detail"].split("query")[-1])[:120] + ".json"
        dtxt = _cached(dtag, lambda: _get(p["detail"]), no_net)
        det = json.loads(dtxt) if dtxt else None
    prods = (det or feats[0]).get("properties", {}).get("products", {})

    mech = None
    for pk in ("moment-tensor", "focal-mechanism"):
        pr = (prods.get(pk) or [{}])[0].get("properties", {})
        if _np(pr, 1):
            mech = dict(np1=_np(pr, 1), np2=_np(pr, 2), source=f"USGS {pk}",
                        mag=_f(pr.get("derived-magnitude")) or p.get("mag"),
                        mag_type=(pr.get("derived-magnitude-type") or "Mww"))
            break

    ffp = (prods.get("finite-fault") or [{}])[0]
    ff = ffp.get("properties", {})
    if ff.get("model-length"):
        L, W = float(ff["model-length"]), float(ff["model-width"])
        strike = float(ff.get("segment-1-strike", ff.get("model-strike", 0)))
        dip = float(ff.get("segment-1-dip", ff.get("model-dip", 45)))
        fault = dict(strike=strike, dip=dip, rake=_f(ff.get("model-rake")),
                     length_km=round(L, 1), width_km=round(W, 1),
                     max_slip_m=_f(ff.get("maximum-slip")),
                     model="USGS finite-fault inversion",
                     url=f"https://earthquake.usgs.gov/earthquakes/eventpage/"
                         f"{feats[0]['id']}/finite-fault",
                     trace=_trace_along_strike(c[1], c[0], strike, L))
        # trace straight from the published slip-model footprint
        got = ffm_outline(feats[0]["id"], ffp.get("contents", {}), no_net)
        if got:
            hull, smax = got
            fault["trace"] = _hull_trace(hull, strike, c[1])
            fault["model"] = "USGS finite-fault (slip-model)"
            if smax:
                fault["max_slip_m"] = smax
    elif mech:
        fault = _mag_scaled_trace(c[1], c[0], p.get("mag") or mag or 6.0,
                                  mech["np1"][0], mech["np1"][1])
        fault["rake"] = mech["np1"][2]
    else:
        return None
    return dict(mechanism=mech, fault=fault, usgs_url=p.get("url"),
                usgs_id=feats[0]["id"], usgs_epi=(c[1], c[0]))


def attach_source_models(events, no_net=False):
    got = []
    for ev in events:
        sm = usgs_source_model(ev.get("lat"), ev.get("lon"), ev.get("year"),
                               ev.get("mag"), no_net=no_net)
        if not sm:
            continue
        if sm.get("mechanism"):
            ev["source_model"] = sm["mechanism"]
        ev["fault"] = sm["fault"]
        ev["usgs_url"] = sm.get("usgs_url")
        ev["_usgs_id"], ev["_usgs_epi"] = sm["usgs_id"], sm["usgs_epi"]
        got.append(ev)
        if not no_net:
            time.sleep(0.25)

    # one USGS event matched to several distinct catalog events (aftershock
    # sequences with no date in the source table) -> keep it only on the one
    # whose hypocentre is closest; drop it from the others as unreliable.
    by_id = {}
    for ev in got:
        by_id.setdefault(ev["_usgs_id"], []).append(ev)
    dropped = 0
    for evs in by_id.values():
        if len(evs) < 2:
            continue
        evs.sort(key=lambda e: haversine_km(e["lat"], e["lon"], *e["_usgs_epi"]))
        for ev in evs[1:]:
            for k in ("source_model", "fault", "usgs_url"):
                ev.pop(k, None)
            dropped += 1
    for ev in got:
        ev.pop("_usgs_id", None)
        ev.pop("_usgs_epi", None)
    kept = len(got) - dropped
    print(f"  source models: {kept}/{len(events)} events"
          + (f"  ({dropped} dropped as ambiguous)" if dropped else ""))


# --------------------------------------------------------------------------- #
# master CSV -> catalog
# --------------------------------------------------------------------------- #
def _rows(sheet):
    return [r for r in csv.DictReader(open(MASTER, encoding="utf-8-sig"))
            if r["source_sheet"] == sheet]


def _is_pulse(r, cid):
    if cid == "taiwan_ncree":
        return str(r["Ipulse_H"]).strip().lower() == "true"
    if cid == "yen_2022":
        return True
    return str(r["fault_normal_pulse"]).strip() == "1"          # Baker


def _station(r, cid):
    pgv = _f(r["PGV_cm_s"]) or (max(_f(r["PGV_EW_original"], 0),
                                    _f(r["PGV_NS_original"], 0)) or None)
    rsn = (r["NGA_RSN"] or "").strip()
    return dict(
        code=r["station_original"].strip() or r["station_key"],
        lat=_f(r["latitude_deg"]), lon=_f(r["longitude_deg"]),
        vs30=_f(r["vs30_original"]),
        rrup_km=_f(r["Rrup_km"]) if r["Rrup_km"] else _f(r["closest_distance_km"]),
        rhyp_km=_f(r["Rhyp_km"]),
        is_pulse=_is_pulse(r, cid),
        Tp=_f(r["Tp_s"]) or _f(r["Tp_H_s"]),
        PGV=pgv,
        ori_n=_f(r["orientation_north_deg"]),
        ori_fp=_f(r["orientation_fault_parallel_deg"]),
        fling=_bool(r["fling"]),
        directivity=True if str(r["directivity_effect"]).strip() == "1" else None,
        rsn=rsn or None,
        summary_url=f"{JWB}/{rsn}.html" if rsn and cid == "shahi_baker_2014" else None,
        quality_flag=r["quality_flag"] or None,
        coord_status=r["coord_status"] if r["coord_status"] != "matched" else None,
    )


def build_catalog(cid):
    events = {}
    for r in _rows(CATALOGS[cid]["sheet"]):
        nm, yr = r["event_original"].strip(), (r["year"] or "").strip()
        ek = key(nm, yr)
        ev = events.setdefault(ek, dict(
            key=ek, name=nm.replace("_", " "), year=yr or None,
            lat=_f(r["hypo_lat_deg"]), lon=_f(r["hypo_lon_deg"]),
            depth_km=_f(r["hypo_depth_original"]), mag=_f(r["Mw"]),
            fault_type=r["mechanism_original"] or None, stations=[]))
        ev["stations"].append(_station(r, cid))
    return list(events.values())


def _finish(events, ncree_hypo):
    for ev in events:
        if ev["lat"] is None:
            epi = (ncree_hypo.get(_NCREE_ALIASES.get(key(ev["name"]), ev["key"]))
                   or ncree_hypo.get(ev["key"]) or EXTRA_EPI.get(ev["key"]))
            if epi:
                ev["lat"], ev["lon"], ev["depth_km"], m = epi
                ev["mag"] = ev["mag"] or m
        for s in ev["stations"]:
            if s.get("lat") is not None and ev["lat"] is not None:
                s["repi_km"] = round(
                    haversine_km(ev["lat"], ev["lon"], s["lat"], s["lon"]), 2)
            for k in ("Tp", "PGV", "rrup_km", "rhyp_km", "repi_km", "vs30",
                      "ori_n", "ori_fp"):
                if isinstance(s.get(k), float):
                    s[k] = round(s[k], 3)
            for k in [k for k, v in list(s.items()) if v is None
                      and k not in ("lat", "lon")]:
                s.pop(k)
        ev["stats"] = _stats(ev["stations"])
        ev["n_mappable"] = sum(1 for s in ev["stations"] if s.get("lat"))
    events.sort(key=lambda e: (e.get("year") or "", e["name"]))
    return events


def write_catalog(cid, events):
    cfg = CATALOGS[cid]
    OUT.mkdir(parents=True, exist_ok=True)
    doc = dict(schema="pulse-extraction/reference/2", catalog=cid,
               label=cfg["label"], short=cfg["short"], citation=cfg["citation"],
               url=cfg["url"], pulse_only=cfg["pulse_only"],
               n_events=len(events),
               n_records=sum(e["stats"]["n"] for e in events), events=events)
    (OUT / f"{cid}.json").write_text(json.dumps(doc, indent=1))
    print(f"{cid:18} {len(events):3} events  {doc['n_records']:4} records  "
          f"{sum(e['n_mappable'] for e in events):4} mapped")
    return dict(id=cid, label=cfg["label"], short=cfg["short"], url=cfg["url"],
               n_events=len(events), n_records=doc["n_records"],
               pulse_only=cfg["pulse_only"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-net", action="store_true",
                    help="use cached USGS responses only")
    args = ap.parse_args(argv)
    if not MASTER.exists():
        raise SystemExit(f"missing {MASTER}")

    # hypocentres from the NCREE sheet, for Baker / Yen events that lack one
    ncree = _finish(build_catalog("taiwan_ncree"), {})
    ncree_hypo = {e["key"]: (e["lat"], e["lon"], e["depth_km"], e["mag"])
                  for e in ncree if e["lat"] is not None}

    index = []
    for cid in CATALOGS:
        events = ncree if cid == "taiwan_ncree" else _finish(build_catalog(cid), ncree_hypo)
        print(f"{cid}:")
        attach_source_models(events, no_net=args.no_net)
        index.append(write_catalog(cid, events))

    for stale in OUT.glob("*.json"):
        if stale.stem not in {"index", *CATALOGS}:
            stale.unlink()
    (OUT / "index.json").write_text(json.dumps({"catalogs": index}, indent=1))
    print(f"\nwrote {OUT}/index.json  ({len(index)} catalogs)")


if __name__ == "__main__":
    main()
