"""Waveform retrieval + instrument-response removal.

* :func:`read_cwa_freefield` -- read a CWA "FreeField" ASCII record
  (``.txt``): already 3-component acceleration in gal, no ObsPy needed.
* :func:`read_three_component` -- load a local 3-component record (MiniSEED,
  SAC, ...), resolve a response (see :mod:`waveform.response`), return
  acceleration in cm/s**2 ready for :func:`waveform.pipeline.acc_to_velocity`.
* :func:`fetch_event_acc` -- pull a near-fault 3-component record from an FDSN
  data centre for an origin time, same output.

The returned :class:`ThreeComponentAcc.meta` carries ``response`` -- how the
response was obtained (``file`` / ``cache`` / ``fdsn`` / ``fdsn-other-epoch`` /
``fdsn-routed`` / ``nominal`` / ``assumed-physical``) and a QC-style level.

ObsPy is imported lazily so the BASC / classification code stays import-light.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .response import DEFAULT_CACHE, apply_response, resolve_response

_COMP_ORDER = ("E", "N", "Z")


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


def _finish(tr_e, tr_n, tr_z, info, base_meta) -> ThreeComponentAcc:
    dt = float(tr_e.stats.delta)
    n = min(tr_e.stats.npts, tr_n.stats.npts, tr_z.stats.npts)
    meta = dict(base_meta)
    meta.update(
        sampling_rate=tr_e.stats.sampling_rate,
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
