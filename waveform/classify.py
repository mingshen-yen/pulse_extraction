"""Pulse-classification facade.

The single place the ``pulse_classification`` output (``AlgoResult`` /
``PulseData``) is turned into a JSON-friendly dict.  Use :func:`classify_velocity`
directly to run only the Shahi & Baker wavelet pulse extraction on a pair of
already-corrected horizontal velocity components -- no fetch, QC or baseline
correction.  :mod:`waveform.pipeline` calls this so every entry point emits the
same pulse schema.
"""

from __future__ import annotations

import numpy as np

from pulse_classification.classification_algo import classification_algo

__all__ = ["classify_velocity", "pulse_to_dict", "pulse_picks", "select_primary"]


def pulse_to_dict(index: int, p, dt: float, *,
                  include_waveforms: bool = True) -> dict:
    """One ``PulseData`` -> dict.  ``p.angles`` is already in degrees."""
    pulse_th = np.asarray(p.pulse_th, dtype=float)
    peak_t = float(np.argmax(np.abs(pulse_th)) * dt) if pulse_th.size else None
    d = {
        "index": index,
        "is_pulse": bool(p.is_pulse),
        "angle_deg": float(p.angles),
        "Tp": float(p.Tp),
        "PGV": float(p.PGV),
        "PGV_resid": float(p.PGV_resid),
        "pulse_indicator": float(p.pulse_indicator),
        "PC": float(p.PC),
        "late": bool(p.late),
        "pulse_peak_time": peak_t,     # s, |extracted pulse| argmax
    }
    if include_waveforms:
        d["rotated_wave"] = np.asarray(p.signal, dtype=float).tolist()
        d["pulse_wave"] = pulse_th.tolist()
        d["resid_wave"] = np.asarray(p.resid_th, dtype=float).tolist()
    return d


def pulse_picks(pulses: list, *, early_tol: float = 0.2,
                min_split_s: float = 1.0) -> dict:
    """Identify the *strongest* and the *earliest* pulse and whether they split.

    The classifier returns up to 5 pulses.  For interpretation two are useful:

    * ``strongest`` -- the classifier's pulse 1 (Shahi & Baker order; the
      MATLAB ``pulseData`` row).  It is the dominant velocity pulse.
    * ``earliest``  -- among pulse-like results whose ``pulse_indicator`` is
      within ``early_tol`` of the strongest pulse-like one, the earliest in
      time.  A rupture-directivity pulse rides the S-wave first arrival.

    ``split`` is set only when ``earliest`` really is a *separate* feature: the
    two peaks are at least ``max(min_split_s, min(Tp)/3)`` apart in time.  Two
    wavelets a fraction of a period apart (the classifier often re-finds the
    same pulse at a nearby angle) do **not** count -- that was catching false
    positives.

    When ``split`` is true the record plausibly carries an **early directivity
    pulse plus a later, stronger pulse that may be a basin / site-response
    effect** -- worth keeping separate rather than collapsing to one number.

    Returns ``{strongest, earliest, split, split_dt, interpretation}``
    (indices are 1-based into ``pulses``, or ``None``).
    """
    pulse_like = [p for p in pulses if p["is_pulse"]]
    if not pulse_like:
        strongest = (max(pulses, key=lambda p: p["pulse_indicator"])["index"]
                     if pulses else None)
        return {"strongest": strongest, "earliest": None, "split": False,
                "split_dt": None,
                "interpretation": "no pulse-like feature"}

    strongest = pulse_like[0]["index"]          # classifier order = decreasing
    pi_max = max(p["pulse_indicator"] for p in pulse_like)
    near = [p for p in pulse_like
            if p["pulse_indicator"] >= (1.0 - early_tol) * pi_max]
    near.sort(key=lambda p: (p["pulse_peak_time"]
                             if p["pulse_peak_time"] is not None else 1e18))
    earliest = near[0]["index"]

    ps = pulses[strongest - 1]
    pe = pulses[earliest - 1]
    tps, tpe = ps["pulse_peak_time"], pe["pulse_peak_time"]
    split_dt = (None if tps is None or tpe is None else float(tps - tpe))
    sep_needed = max(min_split_s, min(ps["Tp"], pe["Tp"]) / 3.0)
    split = (earliest != strongest and split_dt is not None
             and abs(split_dt) >= sep_needed)

    if not split:
        interp = "single dominant pulse (directivity)"
    else:
        interp = (f"early pulse at {tpe:.1f}s (directivity candidate) + "
                  f"later dominant pulse at {tps:.1f}s "
                  f"(Δ{split_dt:+.1f}s; later one may be basin / site effect)")
    return {"strongest": strongest, "earliest": earliest, "split": split,
            "split_dt": split_dt, "interpretation": interp}


def select_primary(pulses: list, *, select: str = "strongest",
                   early_tol: float = 0.2, min_split_s: float = 1.0) -> int:
    """1-based index of the pulse to report as *the* pulse.

    ``"strongest"`` -- the classifier's pulse 1 (matches the MATLAB row).
    ``"earliest"``  -- the earlier pulse **only when the record genuinely
    splits** (see :func:`pulse_picks`); otherwise falls back to strongest.
    """
    picks = pulse_picks(pulses, early_tol=early_tol, min_split_s=min_split_s)
    if select == "strongest":
        return picks["strongest"] or 1
    if select == "earliest":
        if picks["split"]:
            return picks["earliest"]
        return picks["strongest"] or 1
    raise ValueError(f"unknown select {select!r}; use 'strongest' or 'earliest'")


def classify_velocity(vel_n, vel_e, dt, *, include_waveforms: bool = True,
                      select: str = "strongest", early_tol: float = 0.2,
                      min_split_s: float = 1.0, verbose: bool = False) -> dict:
    """Run the wavelet pulse extraction on two horizontal velocity components.

    ``vel_n`` / ``vel_e`` -- velocity in cm/s (fault-processing "north"/"east"),
    equal length; ``dt`` -- sampling interval [s].

    ``select`` -- which pulse ``primary`` points at: ``"strongest"`` (default,
    classifier pulse 1, matches MATLAB) or ``"earliest"`` (directivity pick).
    Both picks and a split flag are always in ``picks`` regardless.

    Returns::

        {"dt", "npts",
         "pulses": [ {index, is_pulse, angle_deg, Tp, PGV, PGV_resid,
                      pulse_indicator, PC, late, pulse_peak_time,
                      rotated_wave, pulse_wave, resid_wave}, ... x5 ],
         "any_pulse": bool,
         "primary": int,                     # 1-based, per `select`
         "select": str,
         "picks": {strongest, earliest, split, split_dt, interpretation}}

    Pass ``include_waveforms=False`` to drop the three per-pulse arrays.
    """
    vel_n = np.asarray(vel_n, dtype=float).ravel()
    vel_e = np.asarray(vel_e, dtype=float).ravel()
    m = min(vel_n.size, vel_e.size)
    vel_n, vel_e = vel_n[:m], vel_e[:m]

    res = classification_algo(vel_n, vel_e, dt, verbose=verbose)
    pulses = [pulse_to_dict(j, p, dt, include_waveforms=include_waveforms)
              for j, p in enumerate(res.pulse_datas, start=1)]
    if select not in ("strongest", "earliest"):
        raise ValueError(f"unknown select {select!r}")
    picks = pulse_picks(pulses, early_tol=early_tol, min_split_s=min_split_s)
    primary = select_primary(pulses, select=select, early_tol=early_tol,
                             min_split_s=min_split_s)
    return {
        "dt": float(dt),
        "npts": int(m),
        "pulses": pulses,
        "any_pulse": any(p["is_pulse"] for p in pulses),
        "primary": primary,
        "select": select,
        "picks": picks,
    }
