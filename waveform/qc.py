"""Record quality control -- gate a 3-component acceleration record before the
baseline-correction / pulse-extraction pipeline trusts it.

``check_record`` returns a :class:`QCResult` with one :class:`QCCheck` per test
(status ``ok`` / ``warn`` / ``fail``) and an overall ``level``:

    fail  -- do not process (non-finite data, dead channel, wrong units, ...)
    warn  -- process, but flag the output (short record, weak event,
             little pre-event data, mild clipping, ...)
    pass  -- clean

Thresholds live in :class:`QCThresholds`; override any of them per call.
All checks are read-only (inputs are copied).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List

import numpy as np

__all__ = ["QCThresholds", "QCCheck", "QCResult", "QCError", "check_record"]


class QCError(RuntimeError):
    """Raised when a record fails QC and the caller asked to gate on it."""

    def __init__(self, result):
        self.result = result
        super().__init__("record failed QC: "
                         + "; ".join(c.message for c in result.failures))


@dataclass
class QCThresholds:
    min_duration_s: float = 20.0        # fail below this
    warn_duration_s: float = 40.0       # warn below this
    length_mismatch_warn: float = 0.05  # fractional npts spread
    length_mismatch_fail: float = 0.20
    dt_min_s: float = 0.001
    dt_max_s: float = 0.05
    flat_std_frac: float = 1e-6         # std < this * max(|x|) -> dead channel
    const_run_warn: float = 0.20        # longest constant run / npts
    const_run_fail: float = 0.50
    clip_band_frac: float = 0.005       # |x| within this * peak counts as "at rail"
    clip_frac_warn: float = 0.001       # fraction of samples at the rail
    clip_frac_fail: float = 0.01
    spike_mad_k: float = 20.0           # isolated 1-sample reversal > k*MAD near peak
    spike_count_warn: int = 12
    spike_count_fail: int = 40
    dc_offset_warn: float = 0.5         # |mean| / rms
    pga_min_cm_s2: float = 1.0          # warn below (nothing there)
    pga_warn_cm_s2: float = 1500.0      # warn above (~1.5 g, check units)
    pga_fail_cm_s2: float = 8000.0      # fail above (~8 g, almost certainly wrong)
    pre_event_s: float = 5.0            # window treated as "pre-event"
    pre_event_arias_warn: float = 0.20  # >this share of Arias in pre-event -> weak/no trigger
    onset_min_s: float = 2.0            # Arias-5% earlier than this -> little pre-event data
    arias_dur_frac_warn: float = 0.6    # (t95-t5)/total above this -> energy not concentrated


@dataclass
class QCCheck:
    name: str
    status: str          # "ok" | "warn" | "fail"
    message: str
    value: object = None


@dataclass
class QCResult:
    level: str           # "pass" | "warn" | "fail"
    checks: List[QCCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.level != "fail"

    @property
    def failures(self):
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warnings(self):
        return [c for c in self.checks if c.status == "warn"]

    def to_dict(self):
        return {"level": self.level, "ok": self.ok,
                "checks": [asdict(c) for c in self.checks]}

    def __str__(self):
        lines = [f"QC: {self.level.upper()}"]
        for c in self.checks:
            mark = {"ok": "  ", "warn": "! ", "fail": "X "}[c.status]
            lines.append(f"  {mark}{c.name}: {c.message}")
        return "\n".join(lines)


def _longest_constant_run(x):
    if x.size < 2:
        return x.size
    change = np.flatnonzero(np.diff(x) != 0.0)
    if change.size == 0:
        return x.size
    bounds = np.concatenate(([-1], change, [x.size - 1]))
    return int(np.max(np.diff(bounds)))


def _arias_time_frac(acc, dt, frac):
    ia = np.cumsum(acc ** 2)
    if ia[-1] <= 0:
        return 0.0
    return float(np.searchsorted(ia / ia[-1], frac) * dt)


_RESPONSE_LEVEL = {
    "file": "ok", "cache": "ok", "fdsn": "ok",
    "fdsn-other-epoch": "warn", "fdsn-routed": "warn",
    "nominal": "warn", "assumed-physical": "warn", "none": "fail",
}


def check_record(acc_e, acc_n, acc_z, dt, dts=None, *,
                 response=None,
                 thresholds: QCThresholds | None = None) -> QCResult:
    """QC a 3-component acceleration record (cm/s**2).

    ``dt``  -- nominal sampling interval; ``dts`` -- optional ``(dt_e,dt_n,dt_z)``
    if the three differ.  ``response`` -- a ``ResponseInfo`` / its ``to_dict()``
    / a bare source string, to fold the instrument-response provenance into the
    verdict (``nominal`` / ``assumed-physical`` -> warn, ``none`` -> fail).
    """
    T = thresholds or QCThresholds()
    comps = {
        "E": np.asarray(acc_e, float).ravel(),
        "N": np.asarray(acc_n, float).ravel(),
        "Z": np.asarray(acc_z, float).ravel(),
    }
    checks: List[QCCheck] = []

    def add(name, status, msg, value=None):
        checks.append(QCCheck(name, status, msg, value))

    # ---- instrument response provenance ---------------------------------------
    if response is not None:
        src = getattr(response, "source", None)
        if src is None and isinstance(response, dict):
            src = response.get("source")
        if src is None and isinstance(response, str):
            src = response
        if src is not None:
            st = _RESPONSE_LEVEL.get(src, "warn")
            msg = {"ok": f"from {src}",
                   "warn": f"from {src} — amplitudes approximate",
                   "fail": "no usable instrument response"}[st]
            add("response", st, msg, src)

    # ---- non-finite --------------------------------------------------------
    bad = {k: int(np.count_nonzero(~np.isfinite(v))) for k, v in comps.items()}
    if any(bad.values()):
        add("finite", "fail", f"non-finite samples {bad}", bad)
    else:
        add("finite", "ok", "all samples finite")

    # replace non-finite with 0 for the remaining numeric checks
    comps = {k: np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)
             for k, v in comps.items()}

    # ---- sampling interval ----------------------------------------------------
    dts = tuple(float(x) for x in (dts if dts is not None else (dt, dt, dt)))
    if not (T.dt_min_s <= dt <= T.dt_max_s):
        add("sampling", "fail", f"dt={dt:g}s outside [{T.dt_min_s}, {T.dt_max_s}]", dt)
    elif max(dts) - min(dts) > 1e-9:
        add("sampling", "fail", f"components disagree on dt: {dts}", dts)
    else:
        add("sampling", "ok", f"dt={dt:g}s")

    # ---- length ------------------------------------------------------------
    npts = {k: v.size for k, v in comps.items()}
    nmin, nmax = min(npts.values()), max(npts.values())
    dur = nmin * dt
    spread = (nmax - nmin) / nmax if nmax else 1.0
    if spread > T.length_mismatch_fail:
        add("length_match", "fail", f"npts spread {spread:.0%} {npts}", npts)
    elif spread > T.length_mismatch_warn:
        add("length_match", "warn", f"npts spread {spread:.0%} {npts}", npts)
    else:
        add("length_match", "ok", f"npts≈{nmin}")

    if dur < T.min_duration_s:
        add("duration", "fail", f"{dur:.1f}s < {T.min_duration_s}s", dur)
    elif dur < T.warn_duration_s:
        add("duration", "warn", f"{dur:.1f}s < {T.warn_duration_s}s", dur)
    else:
        add("duration", "ok", f"{dur:.0f}s")

    # ---- per-component: dead / constant-run / clipping / spikes / DC ------
    for k, x in comps.items():
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        std = float(np.std(x))
        if peak == 0.0 or std < T.flat_std_frac * max(peak, 1e-30):
            add(f"dead[{k}]", "fail", f"channel {k} is flat (std={std:.3g})", std)
            continue
        add(f"dead[{k}]", "ok", f"std={std:.3g}")

        run = _longest_constant_run(x) / x.size
        if run > T.const_run_fail:
            add(f"const_run[{k}]", "fail", f"{run:.0%} of {k} is one constant value", run)
        elif run > T.const_run_warn:
            add(f"const_run[{k}]", "warn", f"{run:.0%} constant run in {k}", run)

        at_rail = np.count_nonzero(np.abs(x) >= (1.0 - T.clip_band_frac) * peak)
        rail_frac = at_rail / x.size
        if rail_frac > T.clip_frac_fail:
            add(f"clip[{k}]", "fail", f"{rail_frac:.2%} of {k} pinned near ±peak", rail_frac)
        elif rail_frac > T.clip_frac_warn:
            add(f"clip[{k}]", "warn", f"{rail_frac:.2%} of {k} near ±peak (clipping?)", rail_frac)

        # isolated single-sample outliers: the sample sits far from the mean of
        # its neighbours while the neighbours themselves are close together
        # (a digitizer spike, not just high-frequency signal)
        mid = 0.5 * (x[:-2] + x[2:])
        excursion = np.abs(x[1:-1] - mid)
        neighbour_gap = np.abs(x[:-2] - x[2:])
        mad = np.median(np.abs(np.diff(x) - np.median(np.diff(x)))) + 1e-30
        spikes = int(np.count_nonzero(
            (excursion > T.spike_mad_k * mad)
            & (neighbour_gap < 0.3 * excursion)
            & (excursion > 0.3 * peak)))
        if spikes >= T.spike_count_fail:
            add(f"spikes[{k}]", "fail", f"{spikes} step glitches in {k}", spikes)
        elif spikes >= T.spike_count_warn:
            add(f"spikes[{k}]", "warn", f"{spikes} step glitches in {k}", spikes)

        rms = float(np.sqrt(np.mean(x ** 2)))
        dc = abs(float(np.mean(x))) / max(rms, 1e-30)
        if dc > T.dc_offset_warn:
            add(f"dc_offset[{k}]", "warn", f"{k} mean/rms={dc:.2f} (large offset)", dc)

    # ---- PGA sanity (demeaned) ------------------------------------------------
    pga = max(float(np.max(np.abs(x - x.mean()))) for x in comps.values())
    if pga > T.pga_fail_cm_s2:
        add("pga", "fail", f"PGA {pga:.0f} cm/s² (~{pga/981:.1f} g) — wrong units?", pga)
    elif pga > T.pga_warn_cm_s2:
        add("pga", "warn", f"PGA {pga:.0f} cm/s² (~{pga/981:.2f} g) — check units", pga)
    elif pga < T.pga_min_cm_s2:
        add("pga", "warn", f"PGA {pga:.3g} cm/s² — record may be empty", pga)
    else:
        add("pga", "ok", f"PGA {pga:.0f} cm/s² (~{pga/981:.2f} g)")

    # ---- event present / pre-event data ------------------------------------
    pre_n = max(int(T.pre_event_s / dt), 1)
    for k in ("E", "N"):
        x = comps[k]
        tot = float(np.sum(x ** 2))
        if tot <= 0:
            continue
        pre_share = float(np.sum(x[:pre_n] ** 2)) / tot
        if pre_share > T.pre_event_arias_warn:
            add(f"event[{k}]", "warn",
                f"{pre_share:.0%} of {k} energy in first {T.pre_event_s:g}s "
                f"— weak or untriggered", pre_share)

    onset = min(_arias_time_frac(comps[k], dt, 0.05) for k in ("E", "N"))
    if onset < T.onset_min_s:
        add("pre_event_window", "warn",
            f"Arias-5% onset at {onset:.1f}s — little pre-event data for baseline",
            onset)
    else:
        add("pre_event_window", "ok", f"onset {onset:.1f}s")

    # energy concentration -- stationary noise spreads 5-95% Arias over ~the
    # whole record; a real event concentrates it
    dur_fracs = []
    for k in ("E", "N"):
        t5 = _arias_time_frac(comps[k], dt, 0.05)
        t95 = _arias_time_frac(comps[k], dt, 0.95)
        if dur > 0:
            dur_fracs.append((t95 - t5) / dur)
    df = min(dur_fracs) if dur_fracs else 1.0
    if df > T.arias_dur_frac_warn:
        add("event_concentration", "warn",
            f"5-95% Arias spans {df:.0%} of the record — energy not concentrated, "
            f"possibly noise", df)
    else:
        add("event_concentration", "ok", f"5-95% Arias over {df:.0%} of record")

    level = ("fail" if any(c.status == "fail" for c in checks)
             else "warn" if any(c.status == "warn" for c in checks)
             else "pass")
    return QCResult(level=level, checks=checks)
