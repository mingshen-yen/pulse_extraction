"""Stability of the CORRECTED ACCELERATION trace under input perturbations.

For each station / method (E component) we baseline-correct the record, then
re-correct it under small perturbations and ask how much the corrected
acceleration moves:

  FIDELITY   how far the corrected acceleration sits from the raw one, best-lag
             aligned on the overlap:
                relL2%   = 100 * ||acc_corr - acc_raw|| / ||acc_raw||
                hi-frac  = share of that change above 0.25 Hz (the pulse band);
                           ~0 means the correction only touched the drift
             (eBASCO also cuts to the strong-motion window + 35 Hz low-pass +
             tapers, so a large relL2 there is expected -- it is a different
             trace by construction; read its *stability* columns, not fidelity.)

  STABILITY  perturb the input, re-correct, compare to the unperturbed
             correction:
                shapeDrift% = 100 * (1 - max-lag normalised cross-correlation)
                PGA CV%     = 100 * std(PGA) / mean(PGA)
             (a) additive noise: `reps` realisations at 1% RMS
             (b) start trim:     cut 0 / 0.5 / 1 / 2 s off the front

Usage:  python tests/compare_corrected_acc.py [--reps N]
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform import basc                                        # noqa: E402
from waveform.ebasco import ebasco_correct                       # noqa: E402

MSEED = Path("/Volumes/WD/work/pulse/00_BASC_Fling_rm/BASC/TK_unprocess")
EVID = "INT-20230206_0000008"
STATIONS = ["3123", "2712", "3145", "4615", "NAR", "3137", "2716", "3116"]


def read_acc(sta):
    import obspy
    net = "KO" if sta == "KHMN" else "TK"
    b = str(MSEED / f"{net}.{sta}..HN{{}}.{EVID}.ACC.CV.mseed")
    tr = [obspy.read(b.format(c))[0] for c in "ENZ"]
    return (tr[0].data.astype(float), tr[1].data.astype(float),
            tr[2].data.astype(float), float(tr[0].stats.delta))


def corrected_acc_e(ae, an, az, dt, method):
    if method == "kamai":
        n = min(ae.size, an.size, az.size)
        t = np.arange(n) * dt
        de = basc.detrend_poly(ae[:n], 6)
        dn = basc.detrend_poly(an[:n], 6)
        dz = basc.detrend_poly(az[:n], 6)
        *_r, (ace, _acn) = basc.baseline_ka(de, dn, dz, t, dt, return_acc=True)
        return ace
    kw = dict(ref=dict(arias_cut=True, t1_count="t3"),
              legacy=dict(arias_cut=False, t1_count="t1"))[method.split("-")[1]]
    res = ebasco_correct(ae, an, az, dt, **kw)
    if not res.e.ok:
        raise RuntimeError("eBASCO: no E solution")
    return np.asarray(res.e.acc, float)


def _best_lag_ncc(a, b, max_lag=200):
    """max over |lag|<=max_lag of the normalised cross-correlation of a,b."""
    a = a - a.mean()
    b = b - b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    m = min(a.size, b.size)
    a, b = a[:m], b[:m]
    best = -1.0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = a[:lag], b[-lag:]
        elif lag > 0:
            x, y = a[lag:], b[:-lag]
        else:
            x, y = a, b
        if x.size < m // 2:
            continue
        v = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-30))
        best = max(best, v)
    return best


def _rel_l2_and_hifrac(acc_raw, acc_corr, dt, fc=0.25, max_lag=400):
    """best-lag aligned ||corr-raw||/||raw|| and the >fc Hz share of the diff."""
    m = min(acc_raw.size, acc_corr.size)
    r0, c0 = acc_raw[:m], acc_corr[:m]
    # align by best lag (corr may be shifted by an arias cut)
    best, blag = -1.0, 0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            x, y = r0[:lag], c0[-lag:]
        elif lag > 0:
            x, y = r0[lag:], c0[:-lag]
        else:
            x, y = r0, c0
        if x.size < m // 2:
            continue
        v = np.dot(x - x.mean(), y - y.mean()) / (
            np.linalg.norm(x - x.mean()) * np.linalg.norm(y - y.mean()) + 1e-30)
        if v > best:
            best, blag = v, lag
    if blag < 0:
        r, c = r0[:blag], c0[-blag:]
    elif blag > 0:
        r, c = r0[blag:], c0[:-blag]
    else:
        r, c = r0, c0
    d = c - r
    f = np.fft.rfftfreq(d.size, dt)
    D = np.fft.rfft(d)
    d_lo = np.fft.irfft(D * (f <= fc), d.size)
    d_hi = d - d_lo
    rel = 100 * np.linalg.norm(d) / (np.linalg.norm(r) + 1e-30)
    hi_frac = np.linalg.norm(d_hi) / (np.linalg.norm(d) + 1e-30)
    return rel, hi_frac


def analyse(sta, method, reps, rng):
    ae, an, az, dt = read_acc(sta)
    try:
        base = corrected_acc_e(ae, an, az, dt, method)
    except RuntimeError:
        return None
    rel, hifrac = _rel_l2_and_hifrac(ae[:min(ae.size, an.size, az.size)],
                                     base, dt)

    rms = np.sqrt(np.mean(ae ** 2))
    # (a) noise
    n_drift, n_pga = [], []
    for _ in range(reps):
        s = 0.01 * rms
        try:
            c = corrected_acc_e(ae + rng.normal(0, s, ae.size),
                                an + rng.normal(0, s, an.size),
                                az + rng.normal(0, s, az.size), dt, method)
        except RuntimeError:
            continue
        n_drift.append(100 * (1 - _best_lag_ncc(base, c)))
        n_pga.append(np.max(np.abs(c)))
    # (b) start trim
    t_drift, t_pga = [], []
    for tsec in (0.0, 0.5, 1.0, 2.0):
        k = int(tsec / dt)
        try:
            c = corrected_acc_e(ae[k:], an[k:], az[k:], dt, method)
        except RuntimeError:
            continue
        t_drift.append(100 * (1 - _best_lag_ncc(base, c)))
        t_pga.append(np.max(np.abs(c)))

    def cv(v):
        v = np.array(v, float)
        return 100 * v.std() / v.mean() if len(v) >= 3 and v.mean() else np.nan

    return dict(
        rel=rel, hifrac=hifrac,
        n_drift=np.median(n_drift) if len(n_drift) >= 3 else np.nan,
        n_pga_cv=cv(n_pga),
        t_drift=np.median(t_drift) if len(t_drift) >= 3 else np.nan,
        t_pga_cv=cv(t_pga))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=8)
    args = ap.parse_args(argv)
    methods = ["kamai", "ebasco-ref", "ebasco-legacy"]
    rng = np.random.default_rng(0)

    acc = {m: [] for m in methods}
    hdr = (f"{'sta':>6}  {'method':14s}{'relL2%':>9}{'hiFrac':>8} │ "
           f"{'noiseDrift%':>12}{'nPGA CV%':>10} │ {'trimDrift%':>12}{'tPGA CV%':>10}")
    for sta in STATIONS:
        print("\n" + hdr)
        for m in methods:
            r = analyse(sta, m, args.reps, rng)
            if r is None:
                print(f"{sta:>6}  {m:14s}{'  (no eBASCO solution)':>40}")
                continue
            acc[m].append(r)
            print(f"{sta:>6}  {m:14s}{r['rel']:9.2f}{r['hifrac']:8.2f} │ "
                  f"{r['n_drift']:12.3f}{r['n_pga_cv']:10.3f} │ "
                  f"{r['t_drift']:12.3f}{r['t_pga_cv']:10.3f}")

    print("\n" + "=" * 92)
    print(f"{'MEDIAN':22s}{'relL2%':>9}{'hiFrac':>8} │ {'noiseDrift%':>12}{'nPGA CV%':>10}"
          f" │ {'trimDrift%':>12}{'tPGA CV%':>10}")
    print("=" * 92)
    for m in methods:
        if not acc[m]:
            continue
        g = lambda k: np.nanmedian([d[k] for d in acc[m]])
        print(f"{m:22s}{g('rel'):9.2f}{g('hifrac'):8.2f} │ "
              f"{g('n_drift'):12.3f}{g('n_pga_cv'):10.3f} │ "
              f"{g('t_drift'):12.3f}{g('t_pga_cv'):10.3f}   (n={len(acc[m])})")


if __name__ == "__main__":
    main()
