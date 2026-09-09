#!/usr/bin/env python3
"""Build the showcase-site data: run the pulse pipeline per event, write
``site/data/events/<key>.json`` + ``site/data/index.json``.

    python scripts/build_site_data.py --curated              # rebuild all curated events
    python scripts/build_site_data.py --event 2010_darfield  # just one
    python scripts/build_site_data.py --poll --min-mag 5.8   # append new live events

Curated events use a hand-picked near-fault station list; ``--poll`` queries
USGS for recent shallow events and auto-selects nearby strong-motion stations.
Event parameters (and a finite-fault rectangle from the moment tensor) come
from USGS where available, else from the record headers.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from waveform.pipeline import run_pulse                           # noqa: E402
from waveform.site_export import event_summary, haversine_km      # noqa: E402

SITE = ROOT / "site" / "data"
EVENTS_DIR = SITE / "events"
USGS = "https://earthquake.usgs.gov/fdsnws/event/1/query"

PIPE = dict(method="kamai", window="arias", decimate_to=50,
            include_waveforms=True, qc="attach")

# key -> event config.  kind "fdsn": obspy client + origin + station list;
#                       kind "esm":  ESM event id + station list.
CURATED = {
    "2010_darfield": dict(
        kind="fdsn", net="NZ", client="GEONET", origin="2010-09-03T16:35:41",
        name="Darfield, New Zealand", region="Canterbury, NZ",
        sb_name="Darfield, New Zealand",
        stations="GDLC,LINC,HORC,ROLC,TPLC,DSLC,RHSC,SMTC,SHLC,NNBS,LPCC,REHS,CBGS,DFHS"),
    "2011_christchurch": dict(
        kind="fdsn", net="NZ", client="GEONET", origin="2011-02-21T23:51:42",
        name="Christchurch, New Zealand", region="Canterbury, NZ",
        sb_name="Christchurch, New Zealand",
        stations="CCCC,CHHC,HPSC,PRPC,REHS,SHLC,LPCC,D14C,CBGS,RHSC,SMTC"),
    "2009_laquila": dict(
        kind="esm", eventid="IT-2009-0009", name="L'Aquila, Italy",
        region="Central Italy", sb_name="L'Aquila, Italy",
        stations="AQV,AQA,AQK,AQU,AQG,GSA,MTR,ANT,CLN,FMG,AVZ,ORC"),
    "1980_irpinia": dict(
        kind="esm", eventid="IT-1980-0012", name="Irpinia, Italy",
        region="Southern Italy", sb_name="Irpinia, Italy-01",
        stations="STR,BGI,CLT,BSC,BRN,MRT,RCC,TDG"),
    "1979_montenegro": dict(
        kind="esm", eventid="ME-1979-0003", name="Montenegro",
        region="Adriatic coast", sb_name="Montenegro, Yugo.",
        stations="BAR,ULO,ULA,HRZ"),
    "2016_amatrice": dict(
        kind="esm", eventid="EMSC-20160824_0000006", name="Amatrice, Italy",
        region="Central Italy",
        stations="AMT,NRC,MSCT,ASP,LSS,RQT,TERO,MNF,CLF,SNO,FEMA,PCB,ACC,SPM"),
}

_SB2014 = ROOT / "data" / "reference" / "table_SB2014.csv"
# SB2014 station name -> our station code, for the events where they differ
_SB_ALIAS = {
    "L'Aquila - V. Aterno - Centro Valle": "AQV",
    "L'Aquila - V. Aterno -F. Aterno": "AQA",
    "L'Aquila - Parking": "AQK",
    "Sturno (STN)": "STR", "Bagnoli Irpinio": "BGI",
    "Bar-Skupstina Opstine": "BAR", "Ulcinj - Hotel Olimpic": "ULO",
}


def sb2014_rrup(sb_name):
    """{station code: Rrup km} from table_SB2014.csv for one event (or {})."""
    if not sb_name or not _SB2014.exists():
        return {}
    import csv
    out = {}
    for r in csv.DictReader(open(_SB2014, encoding="utf-8-sig")):
        if r["Earthquake Name"] != sb_name:
            continue
        code = _SB_ALIAS.get(r["sta"].strip(), r["sta"].strip())
        try:
            out[code] = float(r["rrup"])
        except (KeyError, ValueError):
            pass
    return out


# --------------------------------------------------------------------------- #
# USGS event parameters + finite-fault rectangle
# --------------------------------------------------------------------------- #
def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pulse-extraction/site"})
    with urllib.request.urlopen(req, timeout=60) as r:            # noqa: S310
        return json.load(r)


def usgs_event(origin_iso, lat=None, lon=None, radius_km=250, dmag=1.5):
    """Largest USGS event within +-90 s of ``origin_iso`` (and ``radius_km`` of
    lat/lon when given).  Returns ``(event_dict, fault_or_None)`` or ``(None, None)``."""
    t = datetime.fromisoformat(origin_iso.replace("Z", "")).replace(tzinfo=timezone.utc)
    q = {"format": "geojson", "orderby": "magnitude",
         "starttime": (t - timedelta(seconds=90)).isoformat(),
         "endtime": (t + timedelta(seconds=90)).isoformat(), "limit": 5}
    if lat is not None:
        q.update(latitude=lat, longitude=lon, maxradiuskm=radius_km)
    try:
        feats = _get_json(f"{USGS}?{urllib.parse.urlencode(q)}").get("features", [])
    except Exception as exc:                                      # noqa: BLE001
        print(f"  USGS lookup failed: {exc}")
        return None, None
    if not feats:
        return None, None
    f = feats[0]
    if f["properties"].get("detail"):                 # full products (moment tensor)
        try:
            f = _get_json(f["properties"]["detail"])
        except Exception:                                        # noqa: BLE001
            pass
    p, c = f["properties"], f["geometry"]["coordinates"]
    ev = {
        "id": f["id"], "source": "USGS",
        "time": datetime.fromtimestamp(p["time"] / 1000, timezone.utc)
                        .isoformat(timespec="seconds"),
        "lat": c[1], "lon": c[0], "depth_km": c[2],
        "mag": p["mag"], "mag_type": (p.get("magType") or "M").capitalize(),
        "name": p.get("place"),
        "url": p.get("url"),
    }
    fault = _fault_from_products(p.get("products", {}), ev)
    return ev, fault


def _fault_from_products(products, ev):
    mt = (products.get("moment-tensor") or products.get("focal-mechanism") or [{}])[0]
    mp = mt.get("properties", {})
    try:
        strike = float(mp["nodal-plane-1-strike"])
        dip = float(mp.get("nodal-plane-1-dip", 45.0))
        rake = float(mp.get("nodal-plane-1-rake", 0.0))
    except (KeyError, ValueError, TypeError):
        return None
    return wells_coppersmith_rect(ev["lat"], ev["lon"], ev["depth_km"],
                                  ev["mag"], strike, dip, rake)


def wells_coppersmith_rect(lat, lon, depth_km, mag, strike, dip, rake):
    """A rough finite-fault rectangle: Wells & Coppersmith (1994) subsurface
    rupture length/width for the magnitude, centred on the hypocentre, oriented
    by ``strike`` and projected to the surface using ``dip``."""
    length = 10 ** (-2.44 + 0.59 * mag)           # km
    width = 10 ** (-1.01 + 0.32 * mag)            # km
    half_l = length / 2.0
    surf_half_w = (width / 2.0) * math.cos(math.radians(dip))
    kmlat = 111.32
    kmlon = 111.32 * math.cos(math.radians(lat))
    s = math.radians(strike)
    # along-strike unit vector and (right-hand) across-strike vector, in km
    ax, ay = math.sin(s), math.cos(s)                 # strike direction (E, N)
    px, py = math.cos(s), -math.sin(s)                # dip-projection direction
    corners = []
    for dl, dw in ((-half_l, -surf_half_w), (half_l, -surf_half_w),
                   (half_l, surf_half_w), (-half_l, surf_half_w)):
        ex = dl * ax + dw * px
        ny = dl * ay + dw * py
        corners.append([round(lon + ex / kmlon, 5), round(lat + ny / kmlat, 5)])
    return {"strike": strike, "dip": dip, "rake": rake,
            "length_km": round(length, 1), "width_km": round(width, 1),
            "model": "Wells & Coppersmith (1994) scaling",
            "polygon": corners + [corners[0]]}


# --------------------------------------------------------------------------- #
# station processing
# --------------------------------------------------------------------------- #
def _station_record(acc, out, code):
    p = out["pulses"][out["primary"] - 1]
    m = acc.meta
    return dict(
        code=code, network=m.get("network"),
        lat=m.get("station_lat"), lon=m.get("station_lon"),
        vs30=m.get("vs30"), dt=out["dt"],
        is_pulse=p["is_pulse"], Tp=p["Tp"], PGV=p["PGV"],
        PI=p["pulse_indicator"], angle_deg=p["angle_deg"], late=p["late"],
        qc=(out["qc"] or {}).get("level", "off"),
        pulse=p.get("pulse_wave"),
    )


def _run(acc, code):
    out = run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt,
                    response=acc.meta.get("response"), **PIPE)
    return _station_record(acc, out, code)


def process_fdsn(cfg):
    from obspy.clients.fdsn import Client
    from waveform.fetch import fetch_event_acc

    stations = [s.strip() for s in cfg["stations"].split(",") if s.strip()]
    recs = []
    for sta in stations:
        try:
            acc = fetch_event_acc(cfg["net"], sta, cfg["origin"],
                                  channel=cfg.get("channel", "HN?"),
                                  client=cfg["client"],
                                  pre_seconds=30, post_seconds=150)
            recs.append(_run(acc, sta))
            print(f"  {sta:6} is_pulse={recs[-1]['is_pulse']!s:5} "
                  f"Tp={recs[-1]['Tp']:.2f} PGV={recs[-1]['PGV']:.1f}")
        except Exception as exc:                                  # noqa: BLE001
            print(f"  {sta:6} SKIP {str(exc).splitlines()[0][:70]}")
    ev, fault = usgs_event(cfg["origin"])
    if ev is None:                                                # fall back
        ev = {"id": cfg.get("key"), "source": "config", "time": cfg["origin"],
              "lat": None, "lon": None, "depth_km": None,
              "mag": cfg.get("mag"), "mag_type": "M", "name": cfg["name"]}
    return ev, fault, recs


def process_esm(cfg):
    from waveform.fetch import fetch_esm_event

    stations = [s.strip() for s in cfg["stations"].split(",") if s.strip()]
    recs, hdr = [], None
    for sta in stations:
        try:
            acc = fetch_esm_event(cfg["eventid"], sta, processing="CV")
            recs.append(_run(acc, sta))
            hdr = hdr or acc.meta
            print(f"  {sta:6} is_pulse={recs[-1]['is_pulse']!s:5} "
                  f"Tp={recs[-1]['Tp']:.2f} PGV={recs[-1]['PGV']:.1f}")
        except Exception as exc:                                  # noqa: BLE001
            print(f"  {sta:6} SKIP {str(exc).splitlines()[0][:70]}")
    ev = {"id": cfg["eventid"], "source": "ESM", "name": cfg["name"]}
    if hdr:
        ev.update(time=hdr.get("event_time"), lat=hdr.get("event_lat"),
                  lon=hdr.get("event_lon"), depth_km=hdr.get("event_depth_km"),
                  mag=hdr.get("magnitude"), mag_type="Mw")
    fault = None
    if ev.get("lat") and ev.get("mag") and ev.get("mag", 0) >= 6.0:
        u_ev, u_fault = usgs_event(_iso(ev.get("time")), ev["lat"], ev["lon"])
        fault = u_fault
    return ev, fault, recs


def _iso(esm_time):
    """'20090406_013239' -> '2009-04-06T01:32:39'."""
    if not esm_time or "_" not in esm_time:
        return "1970-01-01T00:00:00"
    d, t = esm_time.split("_")
    t = (t + "000000")[:6]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}"


# --------------------------------------------------------------------------- #
# poll USGS for new events
# --------------------------------------------------------------------------- #
def poll_new(min_mag, hours, max_depth, known):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    q = {"format": "geojson", "starttime": since, "minmagnitude": min_mag,
         "maxdepth": max_depth, "orderby": "time"}
    feats = _get_json(f"{USGS}?{urllib.parse.urlencode(q)}").get("features", [])
    cfgs = {}
    for f in feats:
        if f["id"] in known:
            continue
        c = f["geometry"]["coordinates"]
        p = f["properties"]
        cfgs[f["id"]] = dict(
            kind="poll", usgs_id=f["id"], name=p.get("place"),
            time=datetime.fromtimestamp(p["time"] / 1000, timezone.utc)
                         .isoformat(timespec="seconds"),
            lat=c[1], lon=c[0], depth_km=c[2], mag=p["mag"])
    return cfgs


def process_poll(cfg):
    """Auto-pick strong-motion stations within 60 km and run them."""
    from obspy import UTCDateTime
    from obspy.clients.fdsn import Client
    from waveform.fetch import fetch_event_acc

    lat, lon, t0 = cfg["lat"], cfg["lon"], cfg["time"]
    picked = []
    for cid in ("IRIS", "GEOFON"):
        try:
            inv = Client(cid).get_stations(
                latitude=lat, longitude=lon, maxradius=60 / 111.2,
                channel="HN?,HG?", level="station",
                starttime=UTCDateTime(t0) - 60, endtime=UTCDateTime(t0) + 60)
        except Exception:                                        # noqa: BLE001
            continue
        for n in inv:
            for s in n:
                d = haversine_km(lat, lon, s.latitude, s.longitude)
                picked.append((d, n.code, s.code, cid))
        if picked:
            break
    picked.sort()
    recs = []
    for d, net, sta, cid in picked[:18]:
        try:
            acc = fetch_event_acc(net, sta, t0, channel="HN?", client=cid,
                                  pre_seconds=30, post_seconds=150)
            recs.append(_run(acc, sta))
            print(f"  {net}.{sta:6} ({d:.0f} km) is_pulse={recs[-1]['is_pulse']}")
        except Exception as exc:                                  # noqa: BLE001
            print(f"  {net}.{sta:6} SKIP {str(exc).splitlines()[0][:60]}")
    ev = {"id": cfg["usgs_id"], "source": "USGS", "time": t0, "lat": lat,
          "lon": lon, "depth_km": cfg["depth_km"], "mag": cfg["mag"],
          "mag_type": "M", "name": cfg["name"]}
    _, fault = usgs_event(t0, lat, lon)
    return ev, fault, recs


# --------------------------------------------------------------------------- #
def build_one(key, cfg):
    print(f"\n=== {key}  ({cfg.get('name')}) ===")
    kind = cfg["kind"]
    cfg.setdefault("key", key)
    ev, fault, recs = (process_fdsn if kind == "fdsn" else
                       process_esm if kind == "esm" else process_poll)(cfg)
    if not recs:
        print("  no records — skipped")
        return None
    rrup = sb2014_rrup(cfg.get("sb_name"))
    for r in recs:
        if r["code"] in rrup:
            r["rrup_km"] = rrup[r["code"]]
    if fault:
        ev["fault"] = fault
    if cfg.get("name"):
        ev["place"] = ev.get("name")             # keep the USGS description too
        ev["name"] = cfg["name"]
    ev.setdefault("region", cfg.get("region"))
    summary = event_summary(ev, recs)
    summary["key"] = key
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    (EVENTS_DIR / f"{key}.json").write_text(json.dumps(summary, indent=1))
    s = summary["stats"]
    print(f"  wrote {key}.json  —  {s['n']} stations, {s['n_pulse']} pulse-like")
    return summary


def write_index():
    rows = []
    for p in sorted(EVENTS_DIR.glob("*.json")):
        d = json.loads(p.read_text())
        e, s = d["event"], d["stats"]
        rows.append({
            "key": d["key"], "name": e.get("name"), "region": e.get("region"),
            "time": e.get("time"), "lat": e.get("lat"), "lon": e.get("lon"),
            "depth_km": e.get("depth_km"), "mag": e.get("mag"),
            "mag_type": e.get("mag_type"), "source": e.get("source"),
            "n": s["n"], "n_pulse": s["n_pulse"],
            "pulse_fraction": s["pulse_fraction"],
            "Tp_median": s["Tp_median"], "has_fault": "fault" in e,
        })
    rows.sort(key=lambda r: (r["time"] or ""), reverse=True)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "index.json").write_text(json.dumps(
        {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "events": rows}, indent=1))
    print(f"\nindex.json — {len(rows)} events")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--curated", action="store_true", help="rebuild all curated events")
    ap.add_argument("--event", action="append", default=[],
                    help="rebuild one curated event by key (repeatable)")
    ap.add_argument("--poll", action="store_true",
                    help="query USGS for recent events and append new ones")
    ap.add_argument("--min-mag", type=float, default=5.8)
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--max-depth", type=float, default=50)
    args = ap.parse_args(argv)
    warnings.filterwarnings("ignore")

    for k in args.event:
        build_one(k, CURATED[k])
    if args.curated:
        for k, cfg in CURATED.items():
            try:
                build_one(k, cfg)
            except Exception as exc:                             # noqa: BLE001
                print(f"  {k}: FAILED {exc}")
    if args.poll:
        known = {json.loads(p.read_text())["event"].get("id")
                 for p in EVENTS_DIR.glob("*.json")} if EVENTS_DIR.exists() else set()
        new = poll_new(args.min_mag, args.hours, args.max_depth, known)
        print(f"poll: {len(new)} new event(s)")
        for eid, cfg in new.items():
            key = "live_" + eid.replace(":", "_")
            try:
                build_one(key, cfg)
            except Exception as exc:                             # noqa: BLE001
                print(f"  {key}: FAILED {exc}")

    if args.curated or args.event or args.poll:
        write_index()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
