"""Validate the ESM live-fetch path against Shahi & Baker (2014).

Pulls three near-fault events straight from the Engineering Strong Motion
database (esm-db.eu) -- no local files -- runs the full pipeline
(``CV`` uncorrected acceleration -> Kamai baseline correction -> Arias 5-95 %
window + 50 Hz decimation -> wavelet classifier) and compares Tp / PGV /
is_pulse for every SB2014 pulse record whose station we can name.

Reference: ``data/reference/table_SB2014.csv`` (git-ignored).

Outputs (``output/``, git-ignored):

    2009_LAquila/esm_pulses.csv      2009_LAquila/esm_vs_ShahiBaker2014.csv  ...
    esm_vs_ShahiBaker2014_all.csv    combined comparison
    esm_traces.png  esm_Tp_PGV_Rrup.png

Fetched + processed records cache to ``output/esm_cache.pkl``.

Usage:
    python tests/validate_esm.py                 # fetch (or reuse cache) + compare + plot
    python tests/validate_esm.py --refetch       # force re-download
    python tests/validate_esm.py --plots-only    # cache only, just redraw figures
"""

from __future__ import annotations

import argparse
import csv
import pickle
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from waveform.fetch import fetch_esm_event                        # noqa: E402
from waveform.pipeline import run_pulse                           # noqa: E402
from tests._pulse_validation import (compute_stats, plot_scaling,  # noqa: E402
                                     plot_traces, write_tables)

OUT = ROOT / "output"
CACHE = OUT / "esm_cache.pkl"
SB2014 = ROOT / "data" / "reference" / "table_SB2014.csv"
REF_LABEL, REF_SHORT = "Shahi & Baker (2014)", "S&B"

COLORS = {"2009 L'Aquila": "#1f77b4", "1980 Irpinia": "#d62728",
          "1979 Montenegro": "#2ca02c"}

# label -> (ESM event id, SB2014 "Earthquake Name", output dir,
#           station list, {SB2014 station name: ESM code})
EVENTS = {
    "2009 L'Aquila": (
        "IT-2009-0009", "L'Aquila, Italy", "2009_LAquila",
        ["AQV", "AQA", "AQK", "AQU", "AQG", "GSA", "MTR", "ANT",
         "CLN", "FMG", "SUL", "ORC", "AVZ", "CSO1"],
        {"L'Aquila - V. Aterno - Centro Valle": "AQV",
         "L'Aquila - V. Aterno -F. Aterno": "AQA",
         "L'Aquila - Parking": "AQK"}),
    "1980 Irpinia": (
        "IT-1980-0012", "Irpinia, Italy-01", "1980_Irpinia",
        ["STR", "BGI", "CLT", "BSC", "BRN", "MRT", "RCC", "TDG"],
        {"Sturno (STN)": "STR", "Bagnoli Irpinio": "BGI"}),
    "1979 Montenegro": (
        "ME-1979-0003", "Montenegro, Yugo.", "1979_Montenegro",
        ["BAR", "ULO", "ULA", "HRZ"],
        {"Bar-Skupstina Opstine": "BAR", "Ulcinj - Hotel Olimpic": "ULO"}),
}
DIRS = {k: v[2] for k, v in EVENTS.items()}


def _sb_rows(eqname, name2code):
    out = {}
    for r in csv.DictReader(open(SB2014, encoding="utf-8-sig")):
        if r["Earthquake Name"] == eqname and r["sta"] in name2code:
            out[name2code[r["sta"]]] = (float(r["rrup"]), float(r["Tp"]),
                                        float(r["PGV"]))
    return out


def collect(refetch: bool) -> dict:
    if CACHE.exists() and not refetch:
        return pickle.loads(CACHE.read_bytes())
    warnings.filterwarnings("ignore")
    data = {}
    for label, (eid, eqname, _, stations, name2code) in EVENTS.items():
        sb = _sb_rows(eqname, name2code)
        recs = []
        for sta in stations:
            try:
                acc = fetch_esm_event(eid, sta, processing="CV")
            except Exception as exc:            # noqa: BLE001
                print(f"  {label:16} {sta:5} SKIP  {str(exc).splitlines()[0][:70]}")
                continue
            res = run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt,
                            method="kamai", response=acc.meta["response"],
                            window="arias", decimate_to=50, include_waveforms=True)
            p = res["pulses"][res["primary"] - 1]
            s = sb.get(sta)
            recs.append(dict(
                sta=sta, dt=res["dt"], npts=res["npts"],
                dist_km=acc.meta.get("epicentral_distance_km"),
                vs30=acc.meta.get("vs30"),
                qc=(res["qc"] or {}).get("level", "off"),
                is_pulse=p["is_pulse"], primary=res["primary"],
                Tp=p["Tp"], PGV=p["PGV"], PGV_resid=p["PGV_resid"],
                PI=p["pulse_indicator"], PC=p["PC"], angle=p["angle_deg"],
                late=p["late"], any_pulse=res["any_pulse"],
                rotated=p["rotated_wave"], pulse=p["pulse_wave"],
                sb_rrup=s[0] if s else None, sb_Tp=s[1] if s else None,
                sb_PGV=s[2] if s else None))
            print(f"  {label:16} {sta:5} is_pulse={p['is_pulse']!s:5} "
                  f"Tp={p['Tp']:.2f} PGV={p['PGV']:.1f} PI={p['pulse_indicator']:.1f}")
        data[label] = recs
    OUT.mkdir(exist_ok=True)
    CACHE.write_bytes(pickle.dumps(data))
    print(f"cached {sum(len(v) for v in data.values())} records -> {CACHE}")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refetch", action="store_true",
                    help="force re-download even if output/esm_cache.pkl exists")
    ap.add_argument("--plots-only", action="store_true",
                    help="reuse the cache, only redraw the figures")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)

    data = collect(refetch=args.refetch and not args.plots_only)
    if not args.plots_only:
        write_tables(data, DIRS, OUT, prefix="esm", ref_label=REF_LABEL)
    stats = compute_stats(data)
    if not args.no_plots:
        plot_traces(data, COLORS, OUT, prefix="esm", ref_short=REF_SHORT,
                    xmax=40.0, title="ESM records — rotated velocity vs "
                    "extracted pulse (CV → Kamai → Arias + 50 Hz)")
        plot_scaling(data, COLORS, OUT, prefix="esm", ref_label=REF_LABEL,
                     stats=stats, title="ESM live-fetch validation — "
                     "pulse period & PGV vs rupture distance")


if __name__ == "__main__":
    main()
