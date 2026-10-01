"""Waveform retrieval + instrument-response removal.

* :func:`read_cwa_freefield` -- read a CWA "FreeField" ASCII record
  (``.txt``): already 3-component acceleration in gal, no ObsPy needed.
* :func:`read_three_component` -- load a local 3-component record (MiniSEED,
  SAC, ...), resolve a response (see :mod:`waveform.response`), return
  acceleration in cm/s**2 ready for :func:`waveform.pipeline.acc_to_velocity`.
* :func:`fetch_event_acc` -- pull a near-fault 3-component record from an FDSN
  data centre for an origin time, same output.
* :func:`esm_event_search` / :func:`fetch_esm_event` -- query the Engineering
  Strong Motion database (esm-db.eu) and pull one 3-component record as DYNA
  ``.ASC`` (already in cm/s**2); no ObsPy, no auth for open (e.g. IT/RAN) data.

The returned :class:`ThreeComponentAcc.meta` carries ``response`` -- how the
response was obtained (``file`` / ``cache`` / ``fdsn`` / ``fdsn-other-epoch`` /
``fdsn-routed`` / ``nominal`` / ``assumed-physical``) and a QC-style level.

ObsPy is imported lazily so the BASC / classification code stays import-light.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np

from .response import DEFAULT_CACHE, apply_response, resolve_response

_COMP_ORDER = ("E", "N", "Z")
_ESM_BASE = "https://esm-db.eu"


@dataclass
class ThreeComponentAcc:
    acc_e: np.ndarray            # cm/s**2
    acc_n: np.ndarray
    acc_z: np.ndarray
    dt: float
    meta: dict


def read_cwa_freefield(path) -> ThreeComponentAcc:
    """Read one CWA (Taiwan Central Weather Administration) FreeField ``.txt``
    record: a ``#``-commented header then 4 columns ``Time  U  N  E``, already
    3-component acceleration in **gal (= cm/s**2)**, DC-offset corrected.

    ``response`` is tagged ``assumed-physical`` (units are already gal); the
    station code is de-suffixed (``HWA057-ETL`` -> ``HWA057``).
    """
    p = Path(path)
    lines = p.read_text().splitlines()
    hdr, i = {}, 0
    for i, ln in enumerate(lines):
        if not ln.startswith("#"):
            break
        m = re.match(r"#\s*([^:]+):\s*(.*)", ln)
        if m:
            hdr[m.group(1).strip()] = m.group(2).strip()
    data = np.array([[float(x) for x in ln.split()]
                     for ln in lines[i:] if ln.strip()])
    if data.ndim != 2 or data.shape[1] < 4:
        raise ValueError(f"{p.name}: expected 4 columns (Time U N E), "
                         f"got shape {data.shape}")

    sr = float(hdr.get("SampleRate(Hz)", "0")) or None
    dt = (1.0 / sr) if sr else float(np.median(np.diff(data[:, 0])))
    u, n, e = data[:, 1], data[:, 2], data[:, 3]     # gal, U/N/E

    raw_code = hdr.get("StationCode", p.stem)
    sta = re.match(r"([A-Za-z]+\d+)", raw_code)
    unit = hdr.get("AmplitudeUnit", "")
    # CWA FreeField data is already DC-corrected gal; no StationXML exists for
    # these codes, so skip the network lookups and let the physical-units
    # heuristic tag it ``assumed-physical``.
    info = resolve_response("", sta.group(1) if sta else raw_code, "", "",
                            None, None, routing=False, data_sample=e)
    meta = {
        "format": "cwa-freefield", "path": str(p),
        "station": sta.group(1) if sta else raw_code,
        "station_code": raw_code,
        "instrument_kind": hdr.get("InstrumentKind", "").split()[0]
        if hdr.get("InstrumentKind") else None,
        "start_time": hdr.get("StartTime"),
        "record_length_s": float(hdr["RecordLength(sec)"])
        if "RecordLength(sec)" in hdr else data[-1, 0] - data[0, 0],
        "sampling_rate": 1.0 / dt,
        "amplitude_unit": unit or "gal",
        "response": info.to_dict(),
        "response_removed": False,
        "header": hdr,
    }
    return ThreeComponentAcc(
        acc_e=np.asarray(e, dtype=float), acc_n=np.asarray(n, dtype=float),
        acc_z=np.asarray(u, dtype=float), dt=float(dt), meta=meta,
    )


# --------------------------------------------------------------------------- #
# Engineering Strong Motion database (https://esm-db.eu)
# --------------------------------------------------------------------------- #
_DYNA_STREAM_ALIAS = {"E": "E", "N": "N", "Z": "Z",
                      "1": "N", "2": "E", "3": "Z"}   # HN1/HN2/HN3 -> N/E/Z


def _http(url, *, data=None, headers=None, timeout=120):
    h = {"User-Agent": "pulse-extraction/waveform"}
    h.update(headers or {})
    req = Request(url, data=data, headers=h)
    with urlopen(req, timeout=timeout) as r:          # noqa: S310 (fixed host)
        return r.read(), r.status, r.headers.get_content_type()


def _parse_dyna_asc(text):
    """Split one DYNA 1.x ``.ASC`` string into ``(data, header)``.

    ``header`` is the ``KEY: value`` block; ``data`` a float array.  Adds
    ``dt`` (from ``SAMPLING_INTERVAL_S``) and ``npts`` (from ``NDATA``).
    """
    header, data_start = {}, 0
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s and (s[0].isdigit() or s[0] in "+-.") and ":" not in s:
            data_start = i
            break
        key, _, val = ln.partition(":")
        if _:
            header[key.strip()] = val.strip()
    data = np.array([float(x) for x in lines[data_start:] if x.strip()], dtype=float)
    if "SAMPLING_INTERVAL_S" in header:
        header["dt"] = float(header["SAMPLING_INTERVAL_S"])
    if "NDATA" in header:
        header["npts"] = int(header["NDATA"])
    return data, header


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def esm_event_search(starttime, endtime=None, *, minmag=None, maxmag=None,
                     minlat=None, maxlat=None, minlon=None, maxlon=None,
                     base_url=_ESM_BASE, timeout=60) -> list[dict]:
    """Query the ESM FDSN ``event`` service; return a list of event dicts
    (``ev_id``, ``origin_time``, ``latitude``, ``longitude``, ``depth_km``,
    ``mag_value``, ``mag_type``, ``event_name``).  No auth required.

    ``ev_id`` is what :func:`fetch_esm_event` wants as ``eventid``.
    """
    q = {"starttime": str(starttime), "format": "text"}
    if endtime is not None:
        q["endtime"] = str(endtime)
    for k, v in (("minmag", minmag), ("maxmag", maxmag), ("minlat", minlat),
                 ("maxlat", maxlat), ("minlon", minlon), ("maxlon", maxlon)):
        if v is not None:
            q[k] = v
    url = f"{base_url}/fdsnws/event/1/query?" + urlencode(q)
    body, status, _ = _http(url, timeout=timeout)
    if status == 204 or not body.strip():
        return []
    text = body.decode("utf-8", "replace")
    rows = [ln for ln in text.splitlines() if ln.strip()
            and not ln.lstrip().startswith("#")]
    if rows and rows[0].lower().startswith("ev_id"):
        rows = rows[1:]
    out = []
    for ln in rows:
        f = ln.split("|")
        if len(f) < 8:
            continue
        out.append({"ev_id": f[0], "origin_time": f[1],
                    "latitude": float(f[2]), "longitude": float(f[3]),
                    "depth_km": float(f[4]) if f[4] else None,
                    "mag_value": float(f[6]) if f[6] else None,
                    "mag_type": f[7], "event_name": f[9] if len(f) > 9 else ""})
    return out


def _esm_zip_to_acc(zbytes, *, source_meta) -> ThreeComponentAcc:
    """Assemble the 3 DYNA ``.ASC`` members of an ESM eventdata ZIP into a
    :class:`ThreeComponentAcc` (cm/s**2, response ``assumed-physical``)."""
    zf = zipfile.ZipFile(io.BytesIO(zbytes))
    members = [n for n in zf.namelist() if n.lower().endswith(".asc")]
    if not members:
        raise ValueError("ESM ZIP has no .ASC members "
                         f"(got {zf.namelist()[:5]})")
    comps, headers, dts, units = {}, {}, [], set()
    for name in members:
        data, hdr = _parse_dyna_asc(zf.read(name).decode("utf-8", "replace"))
        stream = (hdr.get("STREAM") or name.split(".")[2] or "")[-1:].upper()
        key = _DYNA_STREAM_ALIAS.get(stream)
        if key is None or key in comps:
            continue
        comps[key] = data
        headers[key] = hdr
        dts.append(hdr.get("dt"))
        units.add((hdr.get("UNITS") or "").lower())
    missing = [c for c in _COMP_ORDER if c not in comps]
    if missing:
        raise ValueError(f"ESM record missing component(s) {missing}; "
                         f"streams present: {sorted(comps)}")
    dt = float(next(d for d in dts if d))
    n = min(len(comps["E"]), len(comps["N"]), len(comps["Z"]))
    e = np.asarray(comps["E"][:n], dtype=float)
    nn = np.asarray(comps["N"][:n], dtype=float)
    z = np.asarray(comps["Z"][:n], dtype=float)

    # ESM CV/MP/AP data is already in physical units (cm/s**2) -- no StationXML.
    info = resolve_response("", headers["E"].get("STATION_CODE", ""), "", "",
                            None, None, routing=False, data_sample=e)
    h = headers["E"]
    unit = next(iter(units)) if len(units) == 1 else "cm/s^2"
    meta = {
        "format": "esm-dyna-asc",
        "station": h.get("STATION_CODE"),
        "network": h.get("NETWORK"),
        "station_name": h.get("STATION_NAME"),
        "station_lat": _f(h.get("STATION_LATITUDE_DEGREE")),
        "station_lon": _f(h.get("STATION_LONGITUDE_DEGREE")),
        "vs30": _f(h.get("VS30_M/S")),
        "ec8": h.get("SITE_CLASSIFICATION_EC8"),
        "event_id": h.get("EVENT_ID"),
        "event_time": f"{h.get('EVENT_DATE_YYYYMMDD','')}_{h.get('EVENT_TIME_HHMMSS','')}",
        "event_lat": _f(h.get("EVENT_LATITUDE_DEGREE")),
        "event_lon": _f(h.get("EVENT_LONGITUDE_DEGREE")),
        "event_depth_km": _f(h.get("EVENT_DEPTH_KM")),
        "magnitude": _f(h.get("MAGNITUDE_W")) or _f(h.get("MAGNITUDE_L")),
        "epicentral_distance_km": _f(h.get("EPICENTRAL_DISTANCE_KM")),
        "start_time": h.get("DATE_TIME_FIRST_SAMPLE_YYYYMMDD_HHMMSS"),
        "sampling_rate": 1.0 / dt,
        "amplitude_unit": unit,
        "baseline_correction": h.get("BASELINE_CORRECTION"),
        "processing": h.get("PROCESSING"),
        "data_license": h.get("DATA_LICENSE"),
        "response": info.to_dict(),
        "response_removed": False,
        "component_map": "HN1/HN2/HN3 -> N/E/Z" if any(
            (headers[c].get("STREAM") or "")[-1] in "123" for c in comps) else "E/N/Z",
        "header": h,
    }
    meta.update(source_meta)
    return ThreeComponentAcc(acc_e=e, acc_n=nn, acc_z=z, dt=dt, meta=meta)


def read_esm_asc_zip(path) -> ThreeComponentAcc:
    """Assemble a locally-saved ESM eventdata ZIP (3 DYNA ``.ASC`` files) into a
    :class:`ThreeComponentAcc`.  Offline counterpart of :func:`fetch_esm_event`."""
    return _esm_zip_to_acc(Path(path).read_bytes(),
                           source_meta={"path": str(path)})


def fetch_esm_event(eventid, station, *, processing="CV", data_type="ACC",
                    network=None, base_url=_ESM_BASE, token=None,
                    timeout=180) -> ThreeComponentAcc:
    """Download one 3-component record from the Engineering Strong Motion
    database (https://esm-db.eu) and return acceleration in cm/s**2.

    ``eventid``    -- ESM/EMSC id, e.g. ``"EMSC-20161030_0000029"`` (see
                      :func:`esm_event_search`).
    ``station``    -- station code, e.g. ``"NRC"``.
    ``processing`` -- ``"CV"`` uncorrected (default; feed to ``run_pulse``),
                      ``"MP"`` manually processed, ``"AP"`` auto-processed.
    ``network``    -- optional FDSN network code to disambiguate.
    ``token``      -- ESM/ORFEUS auth token, a path or the token XML string;
                      only needed for access-restricted networks (IT/RAN and
                      most European strong-motion data are open).

    The returned ``meta`` carries the DYNA header (event + site parameters) and
    tags ``response`` as ``assumed-physical`` (ESM data is already in cm/s**2).
    """
    q = {"eventid": eventid, "data-type": data_type,
         "processing-type": processing, "station": station, "format": "ascii"}
    if network:
        q["network"] = network
    url = f"{base_url}/esmws/eventdata/1/query?" + urlencode(q)

    data, headers = None, None
    if token is not None:
        raw = (Path(token).read_bytes()
               if (isinstance(token, (str, Path)) and Path(str(token)).exists())
               else str(token).encode())
        boundary = "----esmtoken"
        data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"token\"; "
                f"filename=\"token.xml\"\r\nContent-Type: application/xml\r\n\r\n"
                ).encode() + raw + f"\r\n--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

    body, status, ctype = _http(url, data=data, headers=headers, timeout=timeout)
    if status == 204 or not body:
        raise ValueError(f"ESM returned no data for {eventid} / {station} "
                         f"/ processing-type={processing} (204). Try another "
                         f"processing-type (CV/MP/AP) or check the station code.")
    if "zip" not in (ctype or "") and not body[:2] == b"PK":
        raise ValueError(f"ESM did not return a ZIP (content-type {ctype!r}); "
                         f"first bytes {body[:80]!r}")
    return _esm_zip_to_acc(body, source_meta={
        "esm_query": url, "esm_processing": processing})


def _pick_components(st):
    """Return traces ordered E, N, Z, tolerating 1/2/3 and E/N/Z naming."""
    alias = {"1": "N", "2": "E", "3": "Z", "E": "E", "N": "N", "Z": "Z",
             "X": "E", "Y": "N"}
    picked = {}
    for tr in st:
        c = tr.stats.channel[-1].upper()
        key = alias.get(c)
        if key and key not in picked:
            picked[key] = tr
    missing = [c for c in _COMP_ORDER if c not in picked]
    if missing:
        raise ValueError(f"missing component(s): {missing}; have {[t.id for t in st]}")
    return picked["E"], picked["N"], picked["Z"]


def _prep(st):
    st = st.copy()
    st.merge(method=1, fill_value="interpolate")
    st.detrend("demean")
    return st


def _station_coords(inventory, net, sta):
    """``(lat, lon, elev_m)`` for ``net.sta`` from an ObsPy Inventory, or Nones."""
    if inventory is None:
        return None, None, None
    try:
        for n in inventory.select(network=net, station=sta):
            for s in n:
                return (float(s.latitude), float(s.longitude),
                        float(s.elevation) if s.elevation is not None else None)
    except Exception:                                    # noqa: BLE001
        pass
    return None, None, None


def _finish(tr_e, tr_n, tr_z, info, base_meta) -> ThreeComponentAcc:
    dt = float(tr_e.stats.delta)
    n = min(tr_e.stats.npts, tr_n.stats.npts, tr_z.stats.npts)
    meta = dict(base_meta)
    lat, lon, elev = _station_coords(
        info.inventory, base_meta.get("network"), base_meta.get("station"))
    meta.update(
        sampling_rate=tr_e.stats.sampling_rate,
        station_lat=lat, station_lon=lon, station_elev_m=elev,
        response=info.to_dict(),
        response_removed=info.inventory is not None,
    )
    return ThreeComponentAcc(
        acc_e=np.asarray(tr_e.data[:n], dtype=float),
        acc_n=np.asarray(tr_n.data[:n], dtype=float),
        acc_z=np.asarray(tr_z.data[:n], dtype=float),
        dt=dt, meta=meta,
    )


def read_three_component(paths, stationxml=None, *,
                         client=None, cache_dir=DEFAULT_CACHE, routing=False,
                         nominal_sensitivity=None,
                         pre_filt=(0.02, 0.05, 40.0, 50.0),
                         water_level=60.0) -> ThreeComponentAcc:
    """Load 1-or-3 local files into an E/N/Z acceleration triple in cm/s**2.

    ``stationxml`` -- explicit StationXML path (tried first).
    ``client`` -- optional obspy FDSN ``Client`` / id used to look up a missing
    response.  ``cache_dir`` -- local StationXML cache.  ``routing`` -- allow the
    federator / other nodes.  ``nominal_sensitivity`` -- fallback scalar
    (counts per m/s**2) or ``{"NET.STA.CHA": value}`` dict.
    """
    from obspy import read
    from obspy.clients.fdsn import Client

    if isinstance(paths, (str, bytes)):
        st = read(paths)
    else:
        st = None
        for p in paths:
            st = read(p) if st is None else (st + read(p))
    st = _prep(st)
    tr_e, tr_n, tr_z = _pick_components(st)

    cl = Client(client) if isinstance(client, str) else client
    s = tr_e.stats
    cha_glob = s.channel[:-1] + "?"
    info = resolve_response(
        s.network, s.station, s.location or "*", cha_glob,
        s.starttime, tr_e.stats.endtime,
        stationxml=stationxml, client=cl, cache_dir=cache_dir, routing=routing,
        nominal_sensitivity=nominal_sensitivity,
        data_sample=tr_e.data,
    )
    for tr in (tr_e, tr_n, tr_z):
        apply_response(tr, info, pre_filt=pre_filt, water_level=water_level)

    return _finish(tr_e, tr_n, tr_z, info, {
        "network": s.network, "station": s.station,
        "location": s.location, "channel": s.channel,
        "starttime": str(s.starttime),
    })


def fetch_event_acc(network, station, origin_time, *,
                    location="*", channel="HN?", client="IRIS",
                    cache_dir=DEFAULT_CACHE, routing=True,
                    nominal_sensitivity=None,
                    pre_seconds=20.0, post_seconds=120.0,
                    pre_filt=(0.02, 0.05, 40.0, 50.0),
                    water_level=60.0) -> ThreeComponentAcc:
    """Download and deconvolve one 3-component record around ``origin_time``.

    ``channel`` -- ``HN?`` strong-motion accel, ``HH?`` broadband.
    ``client``  -- FDSN id (``IRIS``, ``ORFEUS``, ...) or base URL.
    """
    from obspy import UTCDateTime
    from obspy.clients.fdsn import Client

    t0 = UTCDateTime(origin_time)
    cl = Client(client)
    start, end = t0 - pre_seconds, t0 + post_seconds

    st = _prep(cl.get_waveforms(network, station, location, channel, start, end))
    tr_e, tr_n, tr_z = _pick_components(st)

    info = resolve_response(
        network, station, location, channel, start, end,
        client=cl, cache_dir=cache_dir, routing=routing,
        nominal_sensitivity=nominal_sensitivity, data_sample=tr_e.data,
    )
    for tr in (tr_e, tr_n, tr_z):
        apply_response(tr, info, pre_filt=pre_filt, water_level=water_level)

    return _finish(tr_e, tr_n, tr_z, info, {
        "network": network, "station": station, "location": tr_e.stats.location,
        "channel": channel, "origin_time": str(t0), "client": client,
    })
