"""Strong-motion windowing and optional decimation for long, high-rate records.

Real accelerograms are often 100-200 s at 100-200 Hz.  Feeding the whole thing
to the wavelet classifier is slow and lets the CWT chase pre/post-event noise.
Two cheap fixes, both optional, applied to the raw acceleration before baseline
correction:

* :func:`arias_bounds` / :func:`strong_motion_window` -- trim to the
  Arias-intensity ``p_lo``-``p_hi`` window (default 5-95 %) plus lead/tail
  margins, computed on the combined horizontal energy so all three components
  keep the same span.
* :func:`decimate` -- low-pass + downsample.  Velocity pulses have periods of
  0.25-15 s, so 20-50 Hz is ample; going 200 -> 50 Hz cuts classifier time ~4x
  with no effect on Tp / PGV.
"""

from __future__ import annotations

import numpy as np

__all__ = ["arias_bounds", "strong_motion_window", "decimate", "prepare"]


def arias_bounds(acc, dt, *, p_lo=0.05, p_hi=0.95,
                 pre=10.0, post=15.0) -> tuple[int, int]:
    """``(lo, hi)`` sample indices of the Arias ``p_lo``-``p_hi`` window of
    ``acc`` widened by ``pre`` s before and ``post`` s after."""
    acc = np.asarray(acc, dtype=float)
    ia = np.cumsum(acc ** 2)
    if ia[-1] <= 0:
        return 0, acc.size
    ia = ia / ia[-1]
    i_lo = int(np.searchsorted(ia, p_lo))
    i_hi = int(np.searchsorted(ia, p_hi))
    lo = max(0, i_lo - int(round(pre / dt)))
    hi = min(acc.size, i_hi + int(round(post / dt)))
    return lo, hi


def strong_motion_window(acc_e, acc_n, acc_z, dt, *, p_lo=0.05, p_hi=0.95,
                         pre=10.0, post=15.0):
    """Trim the three components to a common Arias window (measured on the
    horizontal energy ``hypot(N, E)``).  Returns ``(e, n, z, lo, hi)``."""
    e = np.asarray(acc_e, dtype=float).ravel()
    n = np.asarray(acc_n, dtype=float).ravel()
    z = np.asarray(acc_z, dtype=float).ravel()
    m = min(e.size, n.size, z.size)
    e, n, z = e[:m], n[:m], z[:m]
    lo, hi = arias_bounds(np.hypot(n, e), dt, p_lo=p_lo, p_hi=p_hi,
                          pre=pre, post=post)
    return e[lo:hi], n[lo:hi], z[lo:hi], lo, hi


def decimate(acc_e, acc_n, acc_z, dt, *, factor=None, target_rate=50.0):
    """Anti-alias filter + downsample the three components.

    ``factor`` -- integer decimation factor; if ``None`` it is chosen so the
    output rate is >= ``target_rate`` (no-op when the input is already at or
    below ``target_rate``).  Returns ``(e, n, z, new_dt, factor)``.
    """
    from scipy.signal import decimate as _dec

    rate = 1.0 / dt
    if factor is None:
        factor = max(1, int(rate // target_rate))
    if factor <= 1:
        return (np.asarray(acc_e, float), np.asarray(acc_n, float),
                np.asarray(acc_z, float), dt, 1)
    out = [_dec(np.asarray(a, dtype=float), factor, ftype="fir", zero_phase=True)
           for a in (acc_e, acc_n, acc_z)]
    return out[0], out[1], out[2], dt * factor, factor


def prepare(acc_e, acc_n, acc_z, dt, *, window=None, decimate_to=None):
    """Apply optional windowing then optional decimation.

    ``window``      -- ``None`` (pass through), ``"arias"`` (5-95 % + 10/15 s),
                       a dict of :func:`strong_motion_window` kwargs, or an
                       explicit ``(t0_s, t1_s)`` tuple.
    ``decimate_to`` -- ``None`` (no decimation) or a target sample rate in Hz
                       (int or float); a no-op if the input rate is already at
                       or below it.

    Returns ``(e, n, z, dt, info)`` where ``info`` records what was done.
    """
    e = np.asarray(acc_e, dtype=float).ravel()
    n = np.asarray(acc_n, dtype=float).ravel()
    z = np.asarray(acc_z, dtype=float).ravel()
    m = min(e.size, n.size, z.size)
    e, n, z = e[:m], n[:m], z[:m]
    info = {"n_in": m, "dt_in": dt, "window": None, "decimate_factor": 1}

    if window is not None:
        if window == "arias":
            e, n, z, lo, hi = strong_motion_window(e, n, z, dt)
        elif isinstance(window, dict):
            e, n, z, lo, hi = strong_motion_window(e, n, z, dt, **window)
        else:                                    # (t0, t1) in seconds
            t0, t1 = window
            lo = max(0, int(round(t0 / dt)))
            hi = min(m, int(round(t1 / dt)))
            e, n, z = e[lo:hi], n[lo:hi], z[lo:hi]
        info["window"] = {"lo": int(lo), "hi": int(hi),
                          "t0_s": lo * dt, "t1_s": hi * dt}

    if decimate_to is not None:
        e, n, z, dt, fac = decimate(e, n, z, dt, target_rate=float(decimate_to))
        info["decimate_factor"] = fac

    info["n_out"] = int(min(len(e), len(n), len(z)))
    info["dt_out"] = dt
    return e, n, z, dt, info
