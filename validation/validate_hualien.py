"""Validate waveform.classify_velocity against the 2018 Hualien reference set.

Inputs (``data/records/2018_Hualien_records/``, git-ignored):

    <STA>.<INST>.E.v.txt / .N.v.txt   2 cols (time, velocity cm/s), dt = 0.005 s
                                      -- already baseline-corrected
    <STA>.<INST>_pulse.txt            reference extracted-pulse waveform (1 col)
    pulseData_db4.txt                 reference table, one row per station:
                                      sta  angle_deg  Tp  PGV  is_pulse  late  PI

This is the classifier-only path -- no fetch / QC / baseline correction.

Usage:  python validation/validate_hualien.py [--data DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform import classify_velocity                            # noqa: E402

DT = 0.005
DEFAULT_DIR = (Path(__file__).resolve().parents[1]
               / "data" / "records" / "2018_Hualien_records")


def load_reference(data_dir: Path):
    rows = {}
    for line in (data_dir / "pulseData_db4.txt").read_text().split("\n"):
        f = line.split()
        if len(f) < 7:
            continue
        rows[f[0]] = dict(angle=float(f[1]), Tp=float(f[2]), PGV=float(f[3]),
                          is_pulse=int(f[4]), late=int(f[5]), PI=float(f[6]))
    return rows


def load_velocity(data_dir: Path, sta: str):
    e = np.loadtxt(data_dir / f"{sta}.E.v.txt")
    n = np.loadtxt(data_dir / f"{sta}.N.v.txt")
    ve = e[:, 1] if e.ndim == 2 else e
    vn = n[:, 1] if n.ndim == 2 else n
    return vn, ve


def best_pulse(res):
    for p in res["pulses"]:
        if p["is_pulse"]:
            return p
    return max(res["pulses"], key=lambda p: p["pulse_indicator"])


def rel_l2(a, b):
    m = min(len(a), len(b))
    a, b = np.asarray(a[:m]), np.asarray(b[:m])
    return float(np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-30))


def best_lag(a, b):
    """Integer lag k such that ``a[k:]`` aligns with ``b`` (>=0 only).

    Some Hualien ``.v.txt`` files carry a whole-second lead-in that the
    ``_ori.txt`` / ``_pulse.txt`` reference does not; cross-correlation
    recovers it so the pulse waveforms can be compared.
    """
    from numpy import correlate
    a = np.asarray(a, float) - np.mean(a)
    b = np.asarray(b, float) - np.mean(b)
    xc = correlate(a, b, mode="full")
    lag = int(np.arange(-len(b) + 1, len(a))[int(np.argmax(xc))])
    return max(lag, 0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--dt", type=float, default=DT)
    args = ap.parse_args(argv)
    if not args.data.is_dir():
        raise SystemExit(f"no such directory: {args.data}")

    ref = load_reference(args.data)
    if not ref:
        raise SystemExit("pulseData_db4.txt not found or empty")

    hdr = (f"{'station':<12}{'angle':>8}{'Δang':>7} {'Tp':>7}{'ΔTp':>7} "
           f"{'PGV':>8}{'ΔPGV':>7} {'PI':>7}{'ΔPI':>7} {'is_p':>5}{'ref':>4} "
           f"{'lead-in':>8}{'pulseL2':>9}")
    print(hdr)
    print("-" * len(hdr))

    e_ang, e_tp, e_pgv, e_pi, e_wave, flip, miss = [], [], [], [], [], 0, 0
    for sta, r in ref.items():
        try:
            vn, ve = load_velocity(args.data, sta)
        except OSError:
            print(f"{sta:<12}  (missing .v.txt)")
            miss += 1
            continue
        res = classify_velocity(vn, ve, args.dt)
        p = best_pulse(res)

        d_ang = p["angle_deg"] - r["angle"]
        d_ang = (d_ang + 90) % 180 - 90            # fold into (-90, 90]
        d_tp = p["Tp"] - r["Tp"]
        d_pgv = p["PGV"] - r["PGV"]
        d_pi = p["pulse_indicator"] - r["PI"]
        e_ang.append(abs(d_ang)); e_tp.append(abs(d_tp))
        e_pgv.append(abs(d_pgv)); e_pi.append(abs(d_pi))
        if int(p["is_pulse"]) != r["is_pulse"]:
            flip += 1

        pl2 = np.nan
        lead = 0.0
        of = args.data / f"{sta}_ori.txt"
        pf = args.data / f"{sta}_pulse.txt"
        if of.is_file() and pf.is_file():
            ori = np.loadtxt(of)
            pref = np.loadtxt(pf)
            k = best_lag(np.asarray(p["rotated_wave"]), ori)  # whole-second lead-in
            lead = k * args.dt
            pw = np.asarray(p["pulse_wave"])[k:] if k else np.asarray(p["pulse_wave"])
            pl2 = rel_l2(pw, pref)
            if np.isfinite(pl2):
                e_wave.append(pl2)

        print(f"{sta:<12}{p['angle_deg']:8.2f}{d_ang:+7.2f} "
              f"{p['Tp']:7.2f}{d_tp:+7.2f} {p['PGV']:8.2f}{d_pgv:+7.2f} "
              f"{p['pulse_indicator']:7.2f}{d_pi:+7.2f} "
              f"{int(p['is_pulse']):>5}{r['is_pulse']:>4} {lead:+7.1f}s{pl2:9.4f}")

    n = len(e_tp)
    print("-" * len(hdr))
    print(f"n = {n}   is_pulse disagreements = {flip}   missing = {miss}")
    if n:
        for lbl, arr in (("|Δangle|", e_ang), ("|ΔTp|", e_tp),
                         ("|ΔPGV|", e_pgv), ("|ΔPI|", e_pi)):
            a = np.array(arr)
            print(f"  {lbl:9s} median {np.median(a):7.3f}   mean {a.mean():7.3f}"
                  f"   max {a.max():7.3f}")
        if e_wave:
            a = np.array(e_wave)
            print(f"  pulse rel-L2 (vs *_pulse.txt, lead-in aligned): "
                  f"median {np.median(a):.4f}   max {a.max():.4f}   (n={len(a)})")


if __name__ == "__main__":
    main()
