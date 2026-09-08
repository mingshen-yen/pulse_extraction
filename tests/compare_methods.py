"""Accuracy + stability comparison: Kamai vs eBASCO baseline correction,
feeding the same wavelet pulse-extraction stage.

Accuracy  -- 23 stations of the 2023 Turkiye M7.8, pulse Tp/PGV/PI vs the
             EarthScope published table (``ES_published_pulse_table.csv``).
Stability -- on a representative subset, resample the record under
             (a) additive noise and (b) start-window trims, and report the
             scatter of Tp / PGV / PI.

Usage:  python tests/compare_methods.py [--quick]
"""

from __future__ import annotations

import argparse
import csv
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.pipeline import run_pulse                          # noqa: E402
from tests._data import es_csv, read_three, records_dir          # noqa: E402

SUBSET = ["3123", "2712", "3145", "4615", "NAR", "3137", "2716", "3116"]

METHODS = {
    "kamai":        dict(method="kamai"),
    "ebasco-ref":   dict(method="ebasco", ebasco_fallback=False,
                         ebasco_kwargs=dict(arias_cut=True, t1_count="t3")),
    "ebasco-legacy": dict(method="ebasco", ebasco_fallback=False,
                          ebasco_kwargs=dict(arias_cut=False, t1_count="t1")),
}


def load_es(path):
    rows = list(csv.reader(open(path)))
    out = {}
    for r in rows[3:]:
        if len(r) < 14 or not r[1].strip():
            continue
        out[r[1].strip()] = dict(Tp=float(r[11]), PGV=float(r[12]), PI=float(r[13]),
                                 Rrup=float(r[3]))
    return out


def pulse_of(out):
    for p in out["pulses"]:
        if p["is_pulse"]:
            return p
    return max(out["pulses"], key=lambda p: p["pulse_indicator"])


def run(ae, an, az, dt, cfg):
    out = run_pulse(ae, an, az, dt, **cfg)
    p = pulse_of(out)
    return p["Tp"], p["PGV"], p["pulse_indicator"], p["is_pulse"], out["method"]


# ------------------------------------------------------------------ accuracy
def accuracy(es, mseed_dir):
    print("\n" + "=" * 78)
    print("ACCURACY  — |Δ| of pulse Tp / PGV / PI vs ES published 'corrected'")
    print("=" * 78)
    for name, cfg in METHODS.items():
        dtp, dpgv, dpi, nfail, nflip = [], [], [], 0, 0
        for sta, ref in es.items():
            try:
                ae, an, az, dt = read_three(sta, mseed_dir)
                tp, pgv, pi, isp, meth = run(ae, an, az, dt, cfg)
            except Exception:                                    # noqa: BLE001
                nfail += 1
                continue
            dtp.append(abs(tp - ref["Tp"]))
            dpgv.append(abs(pgv - ref["PGV"]))
            dpi.append(abs(pi - ref["PI"]))
            if (ref["PI"] >= 6) != isp:
                nflip += 1
        n = len(dtp)
        print(f"\n  {name:14s}  (n={n}, failed={nfail}, pulse-flag disagreements={nflip})")
        for label, arr in (("Tp  [s]", dtp), ("PGV [cm/s]", dpgv), ("PI", dpi)):
            a = np.array(arr)
            print(f"     {label:11s} median {np.median(a):6.2f}   "
                  f"mean {a.mean():6.2f}   p90 {np.percentile(a, 90):6.2f}   "
                  f"max {a.max():6.2f}")


# ---------------------------------------------------------------- stability
def _cv(vals):
    v = np.array(vals, float)
    return 100.0 * v.std() / abs(v.mean()) if v.mean() else np.nan


def stability(quick, mseed_dir):
    reps = 5 if quick else 10
    trims_s = [0.0, 1.0, 2.0, 3.0, 5.0]
    rng = np.random.default_rng(0)

    print("\n" + "=" * 78)
    print(f"STABILITY  — CV%% of Tp/PGV/PI  (noise: {reps} reps @ ~1%% RMS; "
          f"trim: starts {trims_s} s)")
    print("=" * 78)

    for name, cfg in METHODS.items():
        if name == "ebasco-legacy":
            continue
        noise_cv = {"Tp": [], "PGV": [], "PI": []}
        trim_cv = {"Tp": [], "PGV": [], "PI": []}
        fails = 0
        for sta in SUBSET:
            try:
                ae, an, az, dt = read_three(sta, mseed_dir)
            except Exception:                                    # noqa: BLE001
                continue

            # (a) additive noise
            base_rms = np.sqrt(np.mean(ae ** 2))
            tps, pgvs, pis = [], [], []
            for _ in range(reps):
                s = 0.01 * base_rms
                try:
                    tp, pgv, pi, *_ = run(ae + rng.normal(0, s, ae.size),
                                          an + rng.normal(0, s, an.size),
                                          az + rng.normal(0, s, az.size), dt, cfg)
                    tps.append(tp); pgvs.append(pgv); pis.append(pi)
                except Exception:                                # noqa: BLE001
                    fails += 1
            if len(tps) >= 3:
                noise_cv["Tp"].append(_cv(tps))
                noise_cv["PGV"].append(_cv(pgvs))
                noise_cv["PI"].append(_cv(pis))

            # (b) start-window trim
            tps, pgvs, pis = [], [], []
            for t in trims_s:
                k = int(t / dt)
                try:
                    tp, pgv, pi, *_ = run(ae[k:], an[k:], az[k:], dt, cfg)
                    tps.append(tp); pgvs.append(pgv); pis.append(pi)
                except Exception:                                # noqa: BLE001
                    fails += 1
            if len(tps) >= 3:
                trim_cv["Tp"].append(_cv(tps))
                trim_cv["PGV"].append(_cv(pgvs))
                trim_cv["PI"].append(_cv(pis))

        print(f"\n  {name:14s}  (run failures during perturbation: {fails})")
        print(f"     {'':12s}{'Tp':>10s}{'PGV':>10s}{'PI':>10s}")
        print(f"     noise CV%   "
              f"{np.median(noise_cv['Tp']):10.2f}{np.median(noise_cv['PGV']):10.2f}"
              f"{np.median(noise_cv['PI']):10.2f}")
        print(f"     trim  CV%   "
              f"{np.median(trim_cv['Tp']):10.2f}{np.median(trim_cv['PGV']):10.2f}"
              f"{np.median(trim_cv['PI']):10.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--mseed", help="directory of 3-component mseed")
    ap.add_argument("--es", help="ES_published_pulse_table.csv")
    args = ap.parse_args(argv)
    mseed_dir = records_dir(args.mseed)
    es = load_es(es_csv(args.es))
    accuracy(es, mseed_dir)
    stability(args.quick, mseed_dir)


if __name__ == "__main__":
    main()
