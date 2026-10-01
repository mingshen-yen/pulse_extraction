"""Bundle one event's pipeline results into a single JSON for the showcase site.

``event_summary(event, stations)`` -> a dict the ``site/`` frontend reads
directly: event + finite-fault geometry, per-station pulse results with
coordinates and a downsampled pulse trace, and headline statistics.

No I/O and no heavy deps here -- the caller runs the pipeline and passes plain
dicts; :func:`event_summary` only reshapes and summarises.
"""

from __future__ import annotations

import math
import statistics as _st
from datetime import datetime, timezone

_R_EARTH_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km, or ``None`` if any coord is missing."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * _R_EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def _downsample(values, dt, n_out):
    """Return ``{"dt", "v"}`` -- ``values`` block-averaged to about ``n_out``
    samples (keeps the pulse shape, shrinks the payload)."""
    v = [float(x) for x in values]
    if len(v) <= n_out:
        return {"dt": round(dt, 5), "v": [round(x, 3) for x in v]}
    step = math.ceil(len(v) / n_out)
    out = [round(sum(v[i:i + step]) / len(v[i:i + step]), 3)
           for i in range(0, len(v), step)]
    return {"dt": round(dt * step, 5), "v": out}


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(_st.median(xs), 3) if xs else None


def _dist(s):
    """Distance used in every plot: Rrup, else Rhyp when Rrup is missing."""
    return s.get("rrup_km") if s.get("rrup_km") is not None else s.get("rhyp_km")


def _distance_bins(stations, edges=(0, 5, 10, 20, 40, 80, 160)):
    """Pulse fraction + median Tp per source-distance bin."""
    out = []
    for lo, hi in zip(edges, edges[1:]):
        grp = [s for s in stations
               if _dist(s) is not None and lo <= _dist(s) < hi]
        if not grp:
            continue
        npul = sum(1 for s in grp if s["is_pulse"])
        out.append({
            "r_lo": lo, "r_hi": hi, "n": len(grp), "n_pulse": npul,
            "pulse_fraction": round(npul / len(grp), 3),
            "Tp_median": _median([s["Tp"] for s in grp if s["is_pulse"]]),
        })
    return out


def event_summary(event: dict, stations: list, *, trace_points: int = 240,
                  pipeline: str = "kamai · Arias 5–95 % · 50 Hz") -> dict:
    """Assemble the site JSON.

    ``event``   -- ``{id, time, lat, lon, depth_km, mag, mag_type, name,
                   source, fault?}``.  ``fault`` (optional) is
                   ``{strike, dip, rake, length_km, width_km, top_km}`` or a
                   GeoJSON-ish ``{polygon: [[lon,lat], ...]}``.
    ``stations`` -- one dict per processed station with at least
                   ``code, network, lat, lon, is_pulse, Tp, PGV, PI,
                   angle_deg, late, qc, dt`` and the pulse waveform in
                   ``pulse`` (list); optional ``vs30``, ``rrup_km``,
                   ``rotated`` (list).
    """
    ev = dict(event)
    elat, elon = ev.get("lat"), ev.get("lon")

    edep = ev.get("depth_km")
    st_out = []
    for s in stations:
        slat, slon = s.get("lat"), s.get("lon")
        repi = haversine_km(elat, elon, slat, slon)
        rhyp = (round(math.hypot(repi, edep), 2)
                if repi is not None and edep is not None else None)
        rec = {
            "code": s["code"], "network": s.get("network"),
            "lat": slat, "lon": slon, "vs30": s.get("vs30"),
            "repi_km": round(repi, 2) if repi is not None else None,
            "rhyp_km": rhyp,
            "rrup_km": s.get("rrup_km"),
            "is_pulse": bool(s["is_pulse"]),
            "Tp": round(s["Tp"], 3), "PGV": round(s["PGV"], 2),
            "PI": round(s["PI"], 3), "angle_deg": round(s["angle_deg"], 1),
            "late": bool(s.get("late", False)), "qc": s.get("qc", "off"),
        }
        if s.get("pulse") is not None and len(s["pulse"]):
            rec["pulse_trace"] = _downsample(s["pulse"], s["dt"], trace_points)
        st_out.append(rec)

    pul = [s for s in st_out if s["is_pulse"]]
    stats = {
        "n": len(st_out),
        "n_pulse": len(pul),
        "pulse_fraction": round(len(pul) / len(st_out), 3) if st_out else None,
        "Tp_median": _median([s["Tp"] for s in pul]),
        "PGV_median": _median([s["PGV"] for s in pul]),
        "Tp_range": [min((s["Tp"] for s in pul), default=None),
                     max((s["Tp"] for s in pul), default=None)],
        "by_distance": _distance_bins(st_out),
        "scatter": [{"code": s["code"], "repi_km": s["repi_km"],
                     "rhyp_km": s["rhyp_km"], "rrup_km": s["rrup_km"],
                     "Tp": s["Tp"], "PGV": s["PGV"], "is_pulse": s["is_pulse"]}
                    for s in st_out if _dist(s) is not None],
    }

    return {
        "schema": "pulse-extraction/event/1",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline": pipeline,
        "event": ev,
        "stations": st_out,
        "stats": stats,
    }
