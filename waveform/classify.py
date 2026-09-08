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

__all__ = ["classify_velocity", "pulse_to_dict"]


def pulse_to_dict(index: int, p, *, include_waveforms: bool = True) -> dict:
    """One ``PulseData`` -> dict.  ``p.angles`` is already in degrees."""
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
    }
    if include_waveforms:
        d["rotated_wave"] = np.asarray(p.signal, dtype=float).tolist()
        d["pulse_wave"] = np.asarray(p.pulse_th, dtype=float).tolist()
        d["resid_wave"] = np.asarray(p.resid_th, dtype=float).tolist()
    return d


def classify_velocity(vel_n, vel_e, dt, *, include_waveforms: bool = True,
                      verbose: bool = False) -> dict:
    """Run the wavelet pulse extraction on two horizontal velocity components.

    ``vel_n`` / ``vel_e`` -- velocity in cm/s (fault-processing "north"/"east"),
    equal length; ``dt`` -- sampling interval [s].

    Returns::

        {"dt", "npts",
         "pulses": [ {index, is_pulse, angle_deg, Tp, PGV, PGV_resid,
                      pulse_indicator, PC, late,
                      rotated_wave, pulse_wave, resid_wave}, ... x5 ],
         "any_pulse": bool}

    Pass ``include_waveforms=False`` to drop the three per-pulse arrays.
    """
    vel_n = np.asarray(vel_n, dtype=float).ravel()
    vel_e = np.asarray(vel_e, dtype=float).ravel()
    m = min(vel_n.size, vel_e.size)
    vel_n, vel_e = vel_n[:m], vel_e[:m]

    res = classification_algo(vel_n, vel_e, dt, verbose=verbose)
    pulses = [pulse_to_dict(j, p, include_waveforms=include_waveforms)
              for j, p in enumerate(res.pulse_datas, start=1)]
    return {
        "dt": float(dt),
        "npts": int(m),
        "pulses": pulses,
        "any_pulse": any(p["is_pulse"] for p in pulses),
    }
