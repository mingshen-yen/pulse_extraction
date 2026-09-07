"""End-to-end: corrected acceleration -> BASC velocity -> pulse classification.

``acc_to_velocity`` runs the BASC chain (detrend -> taper -> Kamai baseline
correction, optional fling-step removal) and returns the two horizontal velocity
components the classifier expects.  ``run_pulse`` feeds those into
``pulse_classification.classification_algo`` and returns a plain dict that a web
backend can serialise.

Everything here works on NumPy arrays; reading MiniSEED / removing instrument
response lives in :mod:`waveform.fetch`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pulse_classification.classification_algo import classification_algo

from . import basc
from .ebasco import ebasco_correct
from .qc import QCError, check_record


def _apply_qc(acc_e, acc_n, acc_z, dt, qc, dts=None, response=None):
    """Run QC per the ``qc`` mode; return the QCResult (or None if off).

    ``"gate"``   -- raise :class:`QCError` when the record fails (automation default)
    ``"attach"`` -- run it, return it, never raise
    ``"off"``    -- skip
    """
    if qc in (None, "off", False):
        return None
    res = check_record(acc_e, acc_n, acc_z, dt, dts=dts, response=response)
    if qc == "gate" and res.level == "fail":
        raise QCError(res)
    return res


@dataclass
class VelocityResult:
    vel_n: np.ndarray          # fault-processing "north" component [cm/s]
    vel_e: np.ndarray          # "east" component [cm/s]
    dt: float
    disp_n: np.ndarray
    disp_e: np.ndarray
    method: str = "kamai"
    fling_removed: bool = False
    fling_params: dict = field(default_factory=dict)
    ebasco: object = None      # EbascoResult when method == "ebasco"


def _estimate_fling_params(disp: np.ndarray, dt: float,
                           onset_frac: float = 0.02):
    """Rough auto-estimate of (t1, Tf, Dsite) from a displacement trace.

    * ``Dsite`` -- median of the final 10 % of the trace (static offset).
    * ``t1``    -- first time |disp| crosses ``onset_frac * |Dsite|``.
    * ``Tf``    -- time from ``t1`` until |disp| first reaches 90 % of ``Dsite``.

    Deliberately simple; good enough to seed the model, not a substitute for
    hand-picking on a well-recorded near-fault station.
    """
    n = disp.size
    tail = disp[int(0.9 * n):]
    dsite = float(np.median(tail))
    if abs(dsite) < 1e-6:
        return None
    thr = onset_frac * abs(dsite)
    above = np.where(np.abs(disp) >= thr)[0]
    if above.size == 0:
        return None
    i1 = int(above[0])
    reach = np.where(np.abs(disp) >= 0.9 * abs(dsite))[0]
    i90 = int(reach[0]) if reach.size and reach[0] > i1 else min(i1 + int(1.0 / dt), n - 1)
    t1 = i1 * dt
    tf = max((i90 - i1) * dt, 5 * dt)
    return {"t1": t1, "Tf": tf, "Dsite": dsite}


def acc_to_velocity(acc_e, acc_n, acc_z, dt, *,
                    method: str = "kamai",
                    remove_fling: bool = False,
                    fling_params: dict | None = None,
                    taper_frac: float = 0.0,
                    ebasco_kwargs: dict | None = None,
                    ebasco_fallback: bool = True) -> VelocityResult:
    """Baseline-correct three acceleration components (cm/s**2) to velocity.

    Parameters
    ----------
    acc_e, acc_n, acc_z
        Acceleration in cm/s**2, instrument response already removed, equal
        length.
    method
        ``"kamai"`` -- ``BASC_poly.ipynb`` chain: polynomial detrend -> tail
        taper -> Kamai 6th-order-polynomial baseline correction.
        ``"ebasco"`` -- automatic pre/strong/post-event trilinear correction
        (:func:`waveform.ebasco.ebasco_correct`); preserves permanent
        displacement, ``remove_fling`` is then ignored.
    remove_fling
        (Kamai only) subtract a Kamai (2014) fling step from each horizontal
        displacement before differentiating back to velocity.
    fling_params
        ``{"t1", "Tf", "Dsite"}`` applied to both components, or
        ``{"e": {...}, "n": {...}}`` per component.  ``None`` -> auto-estimate.
    ebasco_kwargs
        Extra keyword args forwarded to :func:`ebasco_correct`.
    """
    acc_e = np.asarray(acc_e, dtype=float).ravel()
    acc_n = np.asarray(acc_n, dtype=float).ravel()
    acc_z = np.asarray(acc_z, dtype=float).ravel()
    n = min(acc_e.size, acc_n.size, acc_z.size)
    acc_e, acc_n, acc_z = acc_e[:n], acc_n[:n], acc_z[:n]
    t = np.arange(n, dtype=float) * dt

    if method == "ebasco":
        res = ebasco_correct(acc_e, acc_n, acc_z, dt, **(ebasco_kwargs or {}))
        if res.e.ok and res.n.ok:
            return VelocityResult(
                vel_n=res.n.vel, vel_e=res.e.vel, dt=dt,
                disp_n=res.n.disp, disp_e=res.e.disp,
                method="ebasco", ebasco=res)
        if not ebasco_fallback:
            raise RuntimeError(
                f"eBASCO found no acceptable solution "
                f"(E ok={res.e.ok}, N ok={res.n.ok}); try method='kamai'")
        method = "kamai"        # fall through to the Kamai path below

    if method != "kamai":
        raise ValueError(f"unknown method {method!r}; use 'kamai' or 'ebasco'")

    vel_e, vel_n, disp_e, disp_n = basc.kamai_correct(
        acc_e, acc_n, acc_z, dt, taper_frac=taper_frac)

    used = {}
    if remove_fling:
        def _params(key, disp):
            if fling_params and key in fling_params:
                return fling_params[key]
            if fling_params and {"t1", "Tf", "Dsite"} <= set(fling_params):
                return fling_params
            return _estimate_fling_params(disp, dt)

        pe = _params("e", disp_e)
        pn = _params("n", disp_n)
        if pe:
            _, _, vel_e = basc.flingstep_rm(disp_e, dt, pe["t1"], pe["Tf"], pe["Dsite"])
            used["e"] = pe
        if pn:
            _, _, vel_n = basc.flingstep_rm(disp_n, dt, pn["t1"], pn["Tf"], pn["Dsite"])
            used["n"] = pn

    m = min(vel_e.size, vel_n.size)
    return VelocityResult(
        vel_n=vel_n[:m], vel_e=vel_e[:m], dt=dt,
        disp_n=disp_n, disp_e=disp_e,
        method="kamai", fling_removed=bool(used), fling_params=used,
    )


def _summarise_pulses(vel_n, vel_e, dt, verbose):
    res = classification_algo(vel_n, vel_e, dt, verbose=verbose)
    pulses = []
    for j, p in enumerate(res.pulse_datas, start=1):
        pulses.append({
            "index": j,
            "is_pulse": bool(p.is_pulse),
            "angle_deg": float(p.angles),   # analyze_record already stores degrees
            "Tp": float(p.Tp),
            "PGV": float(p.PGV),
            "PGV_resid": float(p.PGV_resid),
            "pulse_indicator": float(p.pulse_indicator),
            "PC": float(p.PC),
            "late": bool(p.late),
            "rotated_wave": np.asarray(p.signal, dtype=float).tolist(),
            "pulse_wave": np.asarray(p.pulse_th, dtype=float).tolist(),
            "resid_wave": np.asarray(p.resid_th, dtype=float).tolist(),
        })
    return pulses


def run_pulse(acc_e, acc_n, acc_z, dt, *, method: str = "kamai",
              remove_fling: bool = False, fling_params: dict | None = None,
              ebasco_kwargs: dict | None = None, ebasco_fallback: bool = True,
              qc: str = "gate", response=None, verbose: bool = False) -> dict:
    """Full pipeline: corrected acceleration -> pulse-classification summary.

    Returns a JSON-friendly dict: the corrected velocity the classifier saw,
    plus, for each of the 5 extracted pulses, its direction / Tp / PGV /
    indicator / is_pulse and the rotated + extracted-pulse waveforms.

    ``qc`` -- ``"gate"`` (default) raises :class:`waveform.qc.QCError` if the
    record fails QC; ``"attach"`` runs QC without gating; ``"off"`` skips it.
    The result is under ``out["qc"]``.
    """
    qc_res = _apply_qc(acc_e, acc_n, acc_z, dt, qc, response=response)

    vr = acc_to_velocity(acc_e, acc_n, acc_z, dt, method=method,
                         remove_fling=remove_fling, fling_params=fling_params,
                         ebasco_kwargs=ebasco_kwargs,
                         ebasco_fallback=ebasco_fallback)
    out_method = vr.method if vr.method == method else f"{method}->fell back to {vr.method}"

    pulses = _summarise_pulses(vr.vel_n, vr.vel_e, vr.dt, verbose)

    out = {
        "method": out_method,
        "dt": vr.dt,
        "npts": int(vr.vel_n.size),
        "fling_removed": vr.fling_removed,
        "fling_params": vr.fling_params,
        "qc": qc_res.to_dict() if qc_res is not None else None,
        "vel_n": vr.vel_n.tolist(),
        "vel_e": vr.vel_e.tolist(),
        "pulses": pulses,
        "any_pulse": any(p["is_pulse"] for p in pulses),
    }
    if vr.ebasco is not None:
        out["ebasco"] = {
            c: {"t1": getattr(vr.ebasco, c).t1, "t2": getattr(vr.ebasco, c).t2,
                "t3": getattr(vr.ebasco, c).t3,
                "f_value": getattr(vr.ebasco, c).f_value,
                "permanent_disp": getattr(vr.ebasco, c).permanent_disp}
            for c in ("e", "n", "z")
        }
    return out


def run_pulse_variants(acc_e, acc_n, acc_z, dt, *,
                       fling_params: dict | None = None,
                       taper_frac: float = 0.0, qc: str = "gate",
                       response=None, verbose: bool = False) -> dict:
    """Kamai baseline correction with an explicit, separable fling term
    (:func:`waveform.basc.kamai_fling_decompose`), emitting two products from
    one joint fit:

    ``"basc"``          -- polynomial drift removed, fling step **retained**
                           (keeps the permanent displacement)
    ``"fling_removed"`` -- polynomial *and* fling term removed (permanent
                           displacement ~0; matches the plain Kamai output)

    Each entry is a ``run_pulse``-style dict.  ``fling_params`` reports the
    ``{t1, Tf, Dsite}`` per horizontal -- ``t1``/``Tf`` are auto-estimated
    from the uncorrected displacement (override with a ``{"t1","Tf"}`` or
    ``{"e":{...},"n":{...}}`` ``fling_params``), ``Dsite`` comes from the fit.
    """
    qc_res = _apply_qc(acc_e, acc_n, acc_z, dt, qc, response=response)

    acc_e = np.asarray(acc_e, dtype=float).ravel()
    acc_n = np.asarray(acc_n, dtype=float).ravel()
    acc_z = np.asarray(acc_z, dtype=float).ravel()
    n = min(acc_e.size, acc_n.size, acc_z.size)
    acc_e, acc_n, acc_z = acc_e[:n], acc_n[:n], acc_z[:n]
    t = np.arange(n, dtype=float) * dt

    ae = basc.taper(basc.detrend_poly(acc_e, 6), taper_frac)
    an = basc.taper(basc.detrend_poly(acc_n, 6), taper_frac)

    def _arias_t5(acc1):
        ia = np.cumsum(acc1 ** 2)
        if ia[-1] <= 0:
            return 0.0
        return float(np.searchsorted(ia / ia[-1], 0.05) * dt)

    def _fp(key, acc1):
        override = None
        if fling_params and key in fling_params:
            override = fling_params[key]
        elif fling_params and {"t1", "Tf"} <= set(fling_params):
            override = fling_params
        if override:
            return (float(override["t1"]), float(override["Tf"]),
                    float(override["Dsite"]) if "Dsite" in override else None)
        # t1 = Arias-intensity 5% onset (robust); Tf = physical prior; Dsite
        # from the joint fit.  The uncorrected displacement is drift-dominated,
        # so pass explicit fling_params for a well-constrained real record.
        return _arias_t5(acc1), 2.0, None

    t1e, tfe, dse = _fp("e", ae)
    t1n, tfn, dsn = _fp("n", an)
    de = basc.kamai_fling_decompose(ae, t, dt, t1e, tfe, dse)
    dn = basc.kamai_fling_decompose(an, t, dt, t1n, tfn, dsn)

    used = {"e": {"t1": t1e, "Tf": tfe, "Dsite": de["Dsite"]},
            "n": {"t1": t1n, "Tf": tfn, "Dsite": dn["Dsite"]}}

    def _variant(kind, key):
        ve = de[kind][1]
        vn = dn[kind][1]
        m = min(ve.size, vn.size)
        pulses = _summarise_pulses(vn[:m], ve[:m], dt, verbose)
        return {
            "fling_removed": kind == "removed", "npts": int(m),
            "vel_n": vn[:m].tolist(), "vel_e": ve[:m].tolist(),
            "disp_n": dn[kind][2].tolist(), "disp_e": de[kind][2].tolist(),
            "pulses": pulses,
            "any_pulse": any(p["is_pulse"] for p in pulses),
        }

    return {
        "method": "kamai+fling",
        "dt": dt,
        "fling_params": used,
        "qc": qc_res.to_dict() if qc_res is not None else None,
        "basc": _variant("retained", "basc"),
        "fling_removed": _variant("removed", "fling_removed"),
    }
