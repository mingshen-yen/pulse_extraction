"""Run the full acc -> BASC -> pulse pipeline on the 2023-02-06 Turkiye M7.8
strong-motion records and compare against the EarthScope published pulse table
(``ES_published_pulse_table.csv``: uncorrected vs corrected Tp / PGV / PI).

Usage:
    python validation/historical_2023_turkey.py [--mseed DIR] [--es CSV] [--method both]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.pipeline import run_pulse                          # noqa: E402
from validation._data import es_csv, read_three, records_dir         # noqa: E402


def load_es(path):
    rows = list(csv.reader(open(path)))
    out = {}
    for r in rows[3:]:
        if len(r) < 14 or not r[1].strip():
            continue
        sta = r[1].strip()
        out[sta] = dict(
            Rrup=float(r[3]),
            unc=dict(Tp=float(r[6]), PGV=float(r[7]), PI=float(r[8])),
            cor=dict(Tp=float(r[11]), PGV=float(r[12]), PI=float(r[13])),
        )
    return out


def read_acc(mseed_dir, sta):
    return read_three(sta, mseed_dir)


def best_pulse(out):
    """The pulse the classifier would report: first is_pulse, else strongest."""
    for p in out["pulses"]:
        if p["is_pulse"]:
            return p
    return max(out["pulses"], key=lambda p: p["pulse_indicator"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mseed", help="directory of 3-component mseed")
    ap.add_argument("--es", help="ES_published_pulse_table.csv")
    ap.add_argument("--method", choices=["kamai", "ebasco", "both"], default="both")
    args = ap.parse_args(argv)

    args.mseed = records_dir(args.mseed)
    es = load_es(es_csv(args.es))
    methods = ["kamai", "ebasco"] if args.method == "both" else [args.method]

    hdr = (f"{'sta':>5} {'Rrup':>5} {'is_p':>5} │ "
           f"{'Tp':>6}{'ΔTp_u':>7}{'ΔTp_c':>7} │ "
           f"{'PGV':>7}{'ΔPGV_c':>8} │ {'PI':>6}{'ΔPI_c':>7}")

    for m in methods:
        print(f"\n{'='*92}\nmethod = {m}   (Δ*_u vs ES uncorrected, Δ*_c vs ES corrected)\n{'='*92}")
        print(hdr)
        print("-" * 92)
        err = {"Tp": [], "PGV": [], "PI": []}
        for sta, ref in es.items():
            try:
                ae, an, az, dt = read_acc(args.mseed, sta)
            except Exception as exc:                       # noqa: BLE001
                print(f"{sta:>5}  (skip: {exc})")
                continue
            try:
                out = run_pulse(ae, an, az, dt, method=m)
            except Exception as exc:                       # noqa: BLE001
                print(f"{sta:>5}  (fail: {exc})")
                continue
            p = best_pulse(out)
            tp, pgv, pi = p["Tp"], p["PGV"], p["pulse_indicator"]
            dtp_u = tp - ref["unc"]["Tp"]
            dtp_c = tp - ref["cor"]["Tp"]
            dpgv_c = pgv - ref["cor"]["PGV"]
            dpi_c = pi - ref["cor"]["PI"]
            err["Tp"].append(abs(dtp_c))
            err["PGV"].append(abs(dpgv_c))
            err["PI"].append(abs(dpi_c))
            print(f"{sta:>5} {ref['Rrup']:>5.1f} {str(p['is_pulse']):>5} │ "
                  f"{tp:>6.2f}{dtp_u:>+7.2f}{dtp_c:>+7.2f} │ "
                  f"{pgv:>7.1f}{dpgv_c:>+8.1f} │ {pi:>6.2f}{dpi_c:>+7.2f}")
        n = len(err["Tp"])
        if n:
            print("-" * 92)
            print(f"  median |Δ| vs ES corrected  (n={n}):  "
                  f"Tp {np.median(err['Tp']):.2f} s   "
                  f"PGV {np.median(err['PGV']):.1f} cm/s   "
                  f"PI {np.median(err['PI']):.1f}")


if __name__ == "__main__":
    main()
