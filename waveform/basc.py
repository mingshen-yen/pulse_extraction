"""Baseline correction and fling-step removal.

Faithful port of ``00_BASC_Fling_rm/BASC/funclib.py`` (Kamai-style polynomial
baseline correction plus the Kamai et al. 2014 fling-step model), with three
changes needed to run it unattended in a pipeline:

* every routine copies its inputs instead of mutating the caller's arrays;
* :func:`flingstep_rm` actually uses its ``t1 / Tf / Dsite`` arguments -- the
  original hard-coded them in the function body;
* ``np.matrix`` (removed in modern NumPy) is replaced by a plain lstsq solve.

Numeric output matches the original to floating-point round-off
(see ``tests/test_basc.py``).
"""

from __future__ import annotations

import numpy as np

__all__ = ["detrend", "detrend_poly", "taper", "baseline_ka",
           "make_fling", "flingstep_rm", "kamai_correct",
           "unit_fling", "unit_fling_accel", "kamai_fling_decompose"]


def detrend(y: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Remove the mean and a least-squares linear trend in ``t`` from ``y``.

    This mirrors the *intended* behaviour of ``funclib.detrend`` (detrend ``y``
    against regressor ``t``).  Note ``BASC_poly.py`` calls the original with its
    arguments swapped -- ``BASC_poly.ipynb`` avoids that by using ObsPy's
    polynomial detrend instead; see :func:`detrend_poly`, which is what the
    Kamai pipeline actually uses.
    """
    y = np.asarray(y, dtype=float)
    t = np.asarray(t, dtype=float)
    G = np.column_stack((t, np.ones_like(t)))
    a, b = np.linalg.solve(G.T @ G, G.T @ y)
    return y - (a * t + b)


def detrend_poly(data: np.ndarray, order: int = 6) -> np.ndarray:
    """Subtract an ``order``-degree polynomial fitted against sample index.

    Byte-for-byte equivalent of ObsPy's ``Trace.detrend('polynomial', order=n)``
    (``obspy.signal.detrend.polynomial``): ``fit = polyval(polyfit(arange(n),
    data, order), arange(n)); data -= fit``.  Returns a new array.
    """
    data = np.asarray(data, dtype=float).copy()
    x = np.arange(len(data))
    fit = np.polyval(np.polyfit(x, data, deg=order), x)
    data -= fit
    return data


def taper(y: np.ndarray, frac: float = 0.05) -> np.ndarray:
    """Apply the original 5 % cosine taper to the tail of ``y``.

    Kept bit-for-bit: the taper window is ``cos((0.5*pi/1000) * (1..n))`` over
    the last ``frac`` of the trace, which is an extremely gentle roll-off.
    """
    y = np.asarray(y, dtype=float).copy()
    n = y.size
    k = int(n * frac)
    if k == 0:
        return y
    ramp = np.cos((0.5 * np.pi / 1000) * np.arange(1, k + 1))
    window = np.concatenate((np.ones(n - k), ramp))
    y *= window
    return y


def baseline_ka(acc_e, acc_n, acc_z, t, dt, return_acc=False):
    """Kamai-style baseline correction on three acceleration components.

    Integrates to displacement, fits a 6th-order polynomial with the constant
    and linear terms constrained to zero, subtracts its second derivative from
    the acceleration, and re-integrates.

    Returns ``(vel_e, vel_n, disp_e, disp_n)`` -- ``vel_*`` has ``npts - 1``
    samples, ``disp_*`` has ``npts - 2`` (matching the original ``cumsum`` of
    trapezoidal steps).  With ``return_acc=True`` also returns
    ``(acc_e_corr, acc_n_corr)`` (full ``npts`` samples) as a third tuple.
    """
    ae = np.asarray(acc_e, dtype=float).copy()
    an = np.asarray(acc_n, dtype=float).copy()
    az = np.asarray(acc_z, dtype=float).copy()
    t = np.asarray(t, dtype=float)

    def _integ(x):
        return np.cumsum(x[:-1] + x[1:]) / 2.0 * dt

    vel_e, vel_n, vel_z = _integ(ae), _integ(an), _integ(az)
    disp_e, disp_n, disp_z = _integ(vel_e), _integ(vel_n), _integ(vel_z)

    t_d = t[2:]
    A = np.vstack((t_d ** 2, t_d ** 3, t_d ** 4, t_d ** 5, t_d ** 6)).T

    def _fit(disp):
        return np.linalg.solve(A.T @ A, A.T @ disp)

    pe, pn, pu = _fit(disp_e), _fit(disp_n), _fit(disp_z)
    disp_e = disp_e - A @ pe
    disp_n = disp_n - A @ pn

    t_v = t[1:]
    dA = np.vstack((2 * t_v, 3 * t_v ** 2, 4 * t_v ** 3,
                    5 * t_v ** 4, 6 * t_v ** 5)).T
    vel_e = vel_e - dA @ pe
    vel_n = vel_n - dA @ pn

    d2A = np.vstack((2 * np.ones_like(t), 6 * t, 12 * t ** 2,
                     20 * t ** 3, 30 * t ** 4)).T
    ae = ae - d2A @ pe
    an = an - d2A @ pn

    vel_e_c = _integ(ae)
    vel_n_c = _integ(an)
    disp_e_c = _integ(vel_e_c)
    disp_n_c = _integ(vel_n_c)
    if return_acc:
        return vel_e_c, vel_n_c, disp_e_c, disp_n_c, (ae, an)
    return vel_e_c, vel_n_c, disp_e_c, disp_n_c


def make_fling(dt, sr, total_time, t1, Tf, Dsite):
    """Kamai et al. (2014) idealised fling-step displacement time history.

    ``t1``  -- onset time of the static offset [s]
    ``Tf``  -- rise time / duration of the ramp [s]
    ``Dsite`` -- final coseismic displacement [same units as the trace]
    """
    t1_pt = round(t1 * sr)
    tf_pt = round(Tf * sr)
    npts = round(total_time * sr)
    time = np.arange(1, npts + 1) * dt
    disp = np.zeros(npts)
    seg = slice(t1_pt, t1_pt + tf_pt)
    tt = time[seg] - t1
    disp[seg] = (Dsite / Tf) * tt - (Dsite / (2 * np.pi)) * np.sin((2 * np.pi / Tf) * tt)
    disp[t1_pt + tf_pt:] = Dsite
    return time, disp


def flingstep_rm(disp: np.ndarray, dt: float, t1: float, Tf: float, Dsite: float):
    """Subtract an idealised fling step from a displacement trace.

    Returns ``(time, disp_fling, vel_residual)`` where ``vel_residual`` is the
    derivative of ``disp - disp_fling`` (the fling-removed velocity), same length
    as ``disp``.
    """
    disp = np.asarray(disp, dtype=float)
    npts = disp.size
    sr = 1.0 / dt
    total_time = npts / sr

    time_fling, disp_fling = make_fling(dt, sr, total_time, t1, Tf, Dsite)
    disp_fling = disp_fling[:npts]

    res_disp = disp - disp_fling
    vel_resid = np.diff(res_disp) * sr
    vel_resid = np.concatenate((vel_resid, vel_resid[-1:]))
    return time_fling[:npts], disp_fling, vel_resid


def unit_fling(t: np.ndarray, t1: float, Tf: float) -> np.ndarray:
    """Kamai (2014) fling-step displacement shape, normalised to unit final
    offset: 0 before ``t1``, a smooth ramp over ``[t1, t1+Tf]``, then 1."""
    t = np.asarray(t, dtype=float)
    g = np.zeros_like(t)
    tau = t - t1
    ramp = (tau >= 0) & (tau < Tf)
    g[ramp] = tau[ramp] / Tf - np.sin(2 * np.pi * tau[ramp] / Tf) / (2 * np.pi)
    g[tau >= Tf] = 1.0
    return g


def unit_fling_accel(t: np.ndarray, t1: float, Tf: float) -> np.ndarray:
    """Second time-derivative of :func:`unit_fling` -- one sine arch over
    ``[t1, t1+Tf]``, zero elsewhere."""
    t = np.asarray(t, dtype=float)
    a = np.zeros_like(t)
    tau = t - t1
    arch = (tau >= 0) & (tau < Tf)
    a[arch] = (2 * np.pi / Tf ** 2) * np.sin(2 * np.pi * tau[arch] / Tf)
    return a


def kamai_fling_decompose(acc: np.ndarray, t: np.ndarray, dt: float,
                          t1: float, Tf: float, Dsite: float | None = None):
    """Kamai baseline correction with an explicit, separable fling term.

    Jointly least-squares fits the double-integrated displacement to
    ``p2 t^2 + ... + p6 t^6  +  Dsite * unit_fling(t; t1, Tf)``, then produces
    two corrected records by subtracting the 2nd derivative of the trend from
    the acceleration and re-integrating:

    * ``retained`` -- only the polynomial drift removed; the fling step (hence
      the permanent displacement) is kept.
    * ``removed``  -- polynomial *and* fling term removed (equivalent in intent
      to :func:`baseline_ka`, permanent displacement ~0).

    ``Dsite`` -- if given, the fling amplitude is fixed at this value (the
    original ``BASC_poly.py`` workflow) and only the polynomial is fitted; if
    ``None`` it is a free parameter of the joint least-squares fit.

    Returns ``dict(Dsite, t1, Tf, retained=(acc,vel,disp), removed=(acc,vel,disp))``
    with ``acc`` full length, ``vel`` ``npts-1``, ``disp`` ``npts-2``.
    """
    acc = np.asarray(acc, dtype=float).copy()
    t = np.asarray(t, dtype=float)

    def _integ(x):
        return np.cumsum(x[:-1] + x[1:]) / 2.0 * dt

    vel = _integ(acc)
    disp = _integ(vel)

    t_d = t[2:]
    poly = np.column_stack([t_d ** k for k in (2, 3, 4, 5, 6)])
    g_d = unit_fling(t_d, t1, Tf)
    if Dsite is None:
        A = np.column_stack([poly, g_d])
        coef = np.linalg.solve(A.T @ A, A.T @ disp)
        p, Dsite = coef[:5], float(coef[5])
    else:
        Dsite = float(Dsite)
        p = np.linalg.solve(poly.T @ poly, poly.T @ (disp - Dsite * g_d))

    d2_poly = np.column_stack((2 * np.ones_like(t), 6 * t, 12 * t ** 2,
                               20 * t ** 3, 30 * t ** 4)) @ p
    d2_fling = Dsite * unit_fling_accel(t, t1, Tf)

    def _correct(trend_acc):
        ac = acc - trend_acc
        v = _integ(ac)
        d = _integ(v)
        return ac, v, d

    return {
        "Dsite": Dsite, "t1": t1, "Tf": Tf,
        "retained": _correct(d2_poly),
        "removed": _correct(d2_poly + d2_fling),
    }


def kamai_correct(acc_e, acc_n, acc_z, dt, *, poly_order: int = 6,
                  taper_frac: float = 0.0):
    """The ``BASC_poly.ipynb`` chain: polynomial detrend -> tail taper ->
    Kamai polynomial baseline correction.

    Returns ``(vel_e, vel_n, disp_e, disp_n)`` in the input's units x s
    (feed cm/s**2 to get cm/s).  ``vel_*`` has ``npts - 1`` samples,
    ``disp_*`` has ``npts - 2``.
    """
    acc_e = np.asarray(acc_e, dtype=float).ravel()
    acc_n = np.asarray(acc_n, dtype=float).ravel()
    acc_z = np.asarray(acc_z, dtype=float).ravel()
    n = min(acc_e.size, acc_n.size, acc_z.size)
    acc_e, acc_n, acc_z = acc_e[:n], acc_n[:n], acc_z[:n]
    t = np.arange(n, dtype=float) * dt

    ae = taper(detrend_poly(acc_e, poly_order), taper_frac)
    an = taper(detrend_poly(acc_n, poly_order), taper_frac)
    az = taper(detrend_poly(acc_z, poly_order), taper_frac)
    return baseline_ka(ae, an, az, t, dt)
