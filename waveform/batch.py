"""Batch pulse extraction over many records -> one CSV row per record.

Two sources:

* a directory of CWA "FreeField" ``.txt`` records (:func:`batch_cwa_freefield`)
* a list of stations for one event on the Engineering Strong Motion database
  (:func:`batch_esm_event`, esm-db.eu)

    python -m waveform.batch --cwa data/.../FreeField/Record --out pulses.csv
    python -m waveform.batch --esm-event IT-2009-0009 --esm-stations AQV,AQK,AQA \
        --out laquila.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from pathlib import Path

_COLS = ["record", "station", "network", "dt_in", "dt_out", "npts_out",
         "win_t0_s", "win_t1_s", "qc", "response",
         "is_pulse", "primary", "Tp", "PGV", "PGV_resid", "pulse_indicator",
         "PC", "angle_deg", "late", "split", "split_dt", "any_pulse",
         "Mw", "Repi_km", "vs30", "ec8", "error"]


def _row(record, acc, out):
    prep = out.get("preprocess") or {}
    win = prep.get("window") or {}
    pk = out.get("picks") or {}
    m = acc.meta
    p = out["pulses"][out["primary"] - 1]

    def _rnd(v, n):
        return round(v, n) if isinstance(v, (int, float)) else ""

    return {
        "record": record, "station": m.get("station"),
        "network": m.get("network") or m.get("instrument_kind") or "",
        "dt_in": prep.get("dt_in", acc.dt), "dt_out": out["dt"],
        "npts_out": out["npts"],
        "win_t0_s": round(win["t0_s"], 2) if win else "",
        "win_t1_s": round(win["t1_s"], 2) if win else "",
        "qc": (out["qc"] or {}).get("level", "off"),
        "response": (m.get("response") or {}).get("source", ""),
        "is_pulse": int(p["is_pulse"]), "primary": out["primary"],
        "Tp": round(p["Tp"], 3), "PGV": round(p["PGV"], 2),
        "PGV_resid": round(p["PGV_resid"], 2),
        "pulse_indicator": round(p["pulse_indicator"], 3),
        "PC": round(p["PC"], 4), "angle_deg": round(p["angle_deg"], 2),
        "late": int(p["late"]), "split": pk.get("split", ""),
        "split_dt": (round(pk["split_dt"], 3)
                     if pk.get("split_dt") is not None else ""),
        "any_pulse": int(out["any_pulse"]),
        "Mw": _rnd(m.get("magnitude"), 2),
        "Repi_km": _rnd(m.get("epicentral_distance_km"), 1),
        "vs30": _rnd(m.get("vs30"), 0), "ec8": m.get("ec8") or "",
        "error": "",
    }


def _log(rec, row):
    if row["error"]:
        print(f"  {rec:<16} FAIL  {row['error']}")
    else:
        print(f"  {rec:<16} {row['station'] or '':<8} "
              f"is_pulse={row['is_pulse']} Tp={row['Tp']:<6} "
              f"PGV={row['PGV']:<7} PI={row['pulse_indicator']:<7} qc={row['qc']}")


def _write(rows, out_csv, verbose):
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLS)
        w.writeheader()
        w.writerows(rows)
    ok = [r for r in rows if not r["error"]]
    if verbose:
        npul = sum(r["is_pulse"] == 1 for r in ok)
        print(f"\n{len(ok)}/{len(rows)} processed, {npul} pulse-like.  "
              f"wrote {out_csv}")


def _pulse_json(json_dir, name, row, out):
    summary = {k: row[k] for k in _COLS if k != "error"}
    summary["pulses"] = [{k: q[k] for k in
                          ("index", "is_pulse", "angle_deg", "Tp", "PGV",
                           "pulse_indicator", "PC", "late")}
                         for q in out["pulses"]]
    (Path(json_dir) / f"{name}_pulse.json").write_text(json.dumps(summary, indent=2))


def _run_one(acc, *, window, decimate_to, method, select, qc, want_waveforms):
    from .pipeline import run_pulse
    return run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt,
                     method=method, response=acc.meta.get("response"),
                     window=window, decimate_to=decimate_to,
                     select=select, qc=qc, include_waveforms=want_waveforms)


def batch_cwa_freefield(record_dir, out_csv, *, window="arias", decimate_to=50.0,
                        method="kamai", select="strongest", qc="attach",
                        json_dir=None, verbose=True):
    """Run the pipeline over every ``*.txt`` in ``record_dir``; write ``out_csv``.
    Returns the list of row dicts."""
    from .fetch import read_cwa_freefield
    from .qc import QCError

    record_dir = Path(record_dir)
    files = sorted(record_dir.glob("*.txt"))
    if not files:
        raise SystemExit(f"no .txt records in {record_dir}")
    if json_dir:
        Path(json_dir).mkdir(parents=True, exist_ok=True)

    rows = []
    for f in files:
        rec = f.stem
        try:
            acc = read_cwa_freefield(f)
            out = _run_one(acc, window=window, decimate_to=decimate_to,
                           method=method, select=select, qc=qc,
                           want_waveforms=bool(json_dir))
            row = _row(rec, acc, out)
            if json_dir:
                _pulse_json(json_dir, row["station"] or rec, row, out)
        except (QCError, ValueError, OSError, KeyError) as exc:  # noqa: BLE001
            row = {c: "" for c in _COLS}
            row.update(record=rec, error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
        if verbose:
            _log(rec, row)

    _write(rows, out_csv, verbose)
    return rows


def batch_esm_event(eventid, stations, out_csv, *, processing="CV",
                    network=None, token=None,
                    window="arias", decimate_to=50.0, method="kamai",
                    select="strongest", qc="attach", json_dir=None, verbose=True):
    """Pull each station in ``stations`` for ESM event ``eventid``, run the
    pipeline, write ``out_csv``.  ``stations`` is a list or a comma string.
    Returns the row dicts."""
    from .fetch import fetch_esm_event
    from .qc import QCError

    if isinstance(stations, str):
        stations = [s.strip() for s in stations.split(",") if s.strip()]
    if json_dir:
        Path(json_dir).mkdir(parents=True, exist_ok=True)

    rows = []
    for sta in stations:
        try:
            acc = fetch_esm_event(eventid, sta, processing=processing,
                                  network=network, token=token)
            out = _run_one(acc, window=window, decimate_to=decimate_to,
                           method=method, select=select, qc=qc,
                           want_waveforms=bool(json_dir))
            row = _row(sta, acc, out)
            if json_dir:
                _pulse_json(json_dir, sta, row, out)
        except (QCError, ValueError, OSError, KeyError) as exc:  # noqa: BLE001
            row = {c: "" for c in _COLS}
            row.update(record=sta, station=sta,
                       error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
        if verbose:
            _log(sta, row)

    _write(rows, out_csv, verbose)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--cwa", help="directory of CWA FreeField .txt")
    src.add_argument("--esm-event", metavar="EVENTID",
                     help="ESM/EMSC event id (needs --esm-stations)")
    ap.add_argument("--esm-stations", help="comma-separated station codes")
    ap.add_argument("--esm-processing", default="CV", choices=["CV", "MP", "AP"])
    ap.add_argument("--esm-token", help="ESM/ORFEUS auth token file")
    ap.add_argument("--net", help="ESM: network code to disambiguate")
    ap.add_argument("--out", required=True, help="output CSV path")
    ap.add_argument("--json-dir", help="also write a per-record pulse JSON here")
    ap.add_argument("--method", default="kamai", choices=["kamai", "ebasco"])
    ap.add_argument("--select", default="strongest",
                    choices=["strongest", "earliest"])
    ap.add_argument("--qc", default="attach", choices=["gate", "attach", "off"])
    ap.add_argument("--no-window", action="store_true",
                    help="do not Arias-trim (default: window='arias')")
    ap.add_argument("--decimate", type=float, default=50.0,
                    help="target rate in Hz before classification (0 = off)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    warnings.filterwarnings("ignore")
    common = dict(
        window=None if args.no_window else "arias",
        decimate_to=None if args.decimate == 0 else args.decimate,
        method=args.method, select=args.select, qc=args.qc,
        json_dir=args.json_dir, verbose=not args.quiet)

    if args.cwa:
        batch_cwa_freefield(args.cwa, args.out, **common)
    else:
        if not args.esm_stations:
            ap.error("--esm-event needs --esm-stations")
        batch_esm_event(args.esm_event, args.esm_stations, args.out,
                        processing=args.esm_processing, network=args.net,
                        token=args.esm_token, **common)


if __name__ == "__main__":
    sys.exit(main())
