"""Turn raw strong-motion records into the ``*_VEL_N.txt`` / ``*_VEL_E.txt``
inputs the classifier consumes (single-column velocity in **cm/s**).

Covers the pre-processing that the MATLAB workflow scattered across
``parseAT2.m`` / ``parseCWB.m`` / ``parseJP.m`` / ``parse_iceland.m`` /
``parse_ASC.m`` and ``convert_dis_vel_acc.m``:

* format readers (PEER NGA ``.AT2``, ESM/ORFEUS ``.ASC``, plain single-column,
  optionally miniSEED via ObsPy),
* unit conversion (g, m, cm and their /s, /s^2 forms),
* de-trend + cosine taper (opt-in),
* acausal Butterworth band-pass (opt-in),
* ``acc <-> vel <-> dis`` conversion by cumulative-trapezoid integration
  (matches MATLAB ``cumtrapz``) / finite-difference (matches ``gradient``),
* resampling to a common ``dt``.

Only ``numpy`` + ``scipy`` are required; ObsPy is imported lazily and only for
miniSEED.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt, resample_poly

try:                                        # scipy >= 1.6
    from scipy.integrate import cumulative_trapezoid as _cumtrap
except ImportError:                          # pragma: no cover - old scipy
    from scipy.integrate import cumtrapz as _cumtrap

from .parse import parse_asc

__all__ = [
    "RawRecord", "read_at2", "read_asc", "read_plain", "read_mseed", "read_record",
    "GRAVITY_CM_S2", "to_cm", "detrend", "cosine_taper", "bandpass",
    "to_velocity", "resample_to", "preprocess_component", "write_vel_txt",
]

GRAVITY_CM_S2 = 980.665          # 1 g in cm/s^2


@dataclass
class RawRecord:
    data: np.ndarray             # samples, in the units named by `unit`
    dt: float                    # sampling interval [s]
    unit: str                    # e.g. 'g', 'cm/s**2', 'm/s', 'cm', ...
    kind: str                    # 'acc' | 'vel' | 'dis'
    meta: dict                   # free-form header info


# --------------------------------------------------------------------------- #
# format readers
# --------------------------------------------------------------------------- #
def read_at2(path) -> RawRecord:
    """PEER NGA-West2 ``.AT2`` acceleration file (units: g).

    Line 4 looks like ``NPTS=  7998, DT=   .0050 SEC``.
    """
    lines = Path(path).read_text().splitlines()
    hdr = lines[3].replace(",", " ")
    npts = int(hdr.split("NPTS=")[1].split()[0])
    dt = float(hdr.split("DT=")[1].split()[0])
    data = np.fromstring(" ".join(" ".join(lines[4:]).split()), sep=" ")
    if npts and data.size >= npts:
        data = data[:npts]
    return RawRecord(data, dt, "g", "acc", {"npts": npts, "source": "AT2"})


def read_asc(path) -> RawRecord:
    """ESM/ORFEUS ``.ASC``.  ``UNITS`` and ``SAMPLING_INTERVAL_S`` come from the
    header; ``cm/s`` -> velocity, ``cm/s^2`` -> acceleration, ``cm`` -> displ."""
    data, header = parse_asc(path)
    unit = header.get("UNITS", "cm/s").strip().replace("^", "**")
    kind = {"cm/s": "vel", "cm/s**2": "acc", "cm": "dis"}.get(unit, "vel")
    dt = header.get("dt") or float(header.get("SAMPLING_INTERVAL_S", 0.0)) or None
    if dt is None:
        raise ValueError(f"{path}: no SAMPLING_INTERVAL_S in header")
    return RawRecord(data, float(dt), unit, kind, header)


def read_plain(path, dt: float, *, kind: str = "vel", unit: str = "cm/s",
               skip: int = 0) -> RawRecord:
    """Generic single-/multi-column whitespace file (the CWB / K-NET / Iceland
    cases -- ``dt`` is not in the file, so the caller supplies it)."""
    text = Path(path).read_text().splitlines()[skip:]
    data = np.fromstring(" ".join(" ".join(text).split()), sep=" ")
    return RawRecord(data, float(dt), unit, kind, {"source": "plain", "skip": skip})


def read_mseed(path, *, kind: str = "vel", unit: str = "m/s") -> RawRecord:
    """miniSEED via ObsPy (lazy import).  Returns the first trace."""
    try:
        from obspy import read as _obspy_read
    except ImportError as exc:               # pragma: no cover
        raise ImportError("read_mseed needs ObsPy:  pip install obspy") from exc
    tr = _obspy_read(str(path))[0]
    return RawRecord(np.asarray(tr.data, float), float(tr.stats.delta), unit, kind,
                     {"source": "mseed", "id": tr.id})


_READERS = {".at2": read_at2, ".asc": read_asc, ".mseed": read_mseed}


def read_record(path, *, dt: float | None = None, kind: str = "vel",
                unit: str | None = None, skip: int = 0) -> RawRecord:
    """Dispatch on file extension; fall back to :func:`read_plain`."""
    ext = Path(path).suffix.lower()
    if ext in (".at2", ".mseed"):
        return _READERS[ext](path)
    if ext == ".asc":
        return read_asc(path)
    if dt is None:
        raise ValueError(f"{path}: plain-text format needs an explicit dt=")
    return read_plain(path, dt, kind=kind, unit=unit or "cm/s", skip=skip)


# --------------------------------------------------------------------------- #
# signal operations
# --------------------------------------------------------------------------- #
def to_cm(data: np.ndarray, unit: str) -> np.ndarray:
    """Scale to the cm system: cm, cm/s or cm/s**2 (value unchanged, only the
    magnitude is rescaled).  ``unit`` accepts ``g``, ``m``/``cm`` and ``/s``,
    ``/s2``, ``/s**2`` suffixes."""
    u = unit.strip().lower().replace("^", "**").replace("/s2", "/s**2")
    factor = {
        "g": GRAVITY_CM_S2, "gal": 1.0,
        "m": 100.0, "m/s": 100.0, "m/s**2": 100.0,
        "cm": 1.0, "cm/s": 1.0, "cm/s**2": 1.0,
        "mm": 0.1, "mm/s": 0.1, "mm/s**2": 0.1,
    }.get(u)
    if factor is None:
        raise ValueError(f"unknown unit {unit!r}")
    return np.asarray(data, float) * factor


def detrend(x: np.ndarray, kind: str = "linear") -> np.ndarray:
    """Remove the mean (``'constant'``) or a least-squares line (``'linear'``)."""
    x = np.asarray(x, float)
    if kind == "constant":
        return x - x.mean()
    if kind == "linear":
        n = x.size
        t = np.arange(n)
        a, b = np.polyfit(t, x, 1)
        return x - (a * t + b)
    raise ValueError("kind must be 'constant' or 'linear'")


def cosine_taper(x: np.ndarray, frac: float = 0.05) -> np.ndarray:
    """Apply a Hann (cosine) taper to each end over ``frac`` of the length."""
    x = np.asarray(x, float)
    n = x.size
    m = int(max(1, round(frac * n)))
    if 2 * m >= n:
        m = n // 2
    w = np.ones(n)
    ramp = 0.5 * (1 - np.cos(np.pi * np.arange(m) / m))
    w[:m] = ramp
    w[n - m:] = ramp[::-1]
    return x * w


def bandpass(x: np.ndarray, dt: float, fmin=None, fmax=None,
             order: int = 4, zerophase: bool = True) -> np.ndarray:
    """Butterworth band/low/high-pass.  ``zerophase`` -> ``sosfiltfilt`` (acausal,
    like the 'acausal Butterworth' used by Shahi & Baker).  Effective order is
    doubled when ``zerophase`` is True, matching ``filtfilt`` semantics."""
    x = np.asarray(x, float)
    nyq = 0.5 / dt
    if fmin and fmax:
        sos = butter(order, [fmin / nyq, fmax / nyq], btype="bandpass", output="sos")
    elif fmin:
        sos = butter(order, fmin / nyq, btype="highpass", output="sos")
    elif fmax:
        sos = butter(order, fmax / nyq, btype="lowpass", output="sos")
    else:
        return x
    return sosfiltfilt(sos, x) if zerophase else _sosfilt_causal(sos, x)


def _sosfilt_causal(sos, x):
    from scipy.signal import sosfilt
    return sosfilt(sos, x)


def _integrate(x: np.ndarray, dt: float) -> np.ndarray:
    """Cumulative trapezoid with leading zero -- matches MATLAB ``cumtrapz``."""
    return _cumtrap(np.asarray(x, float), dx=dt, initial=0.0)


def _differentiate(x: np.ndarray, dt: float) -> np.ndarray:
    """Central finite difference -- matches MATLAB ``gradient(x)/dt``."""
    return np.gradient(np.asarray(x, float), dt)


def to_velocity(x: np.ndarray, dt: float, kind: str) -> np.ndarray:
    """Bring an ``'acc'`` / ``'vel'`` / ``'dis'`` trace to velocity."""
    if kind == "vel":
        return np.asarray(x, float)
    if kind == "acc":
        return _integrate(x, dt)
    if kind == "dis":
        return _differentiate(x, dt)
    raise ValueError("kind must be 'acc', 'vel' or 'dis'")


def resample_to(x: np.ndarray, dt_in: float, dt_out: float) -> np.ndarray:
    """Polyphase resample from ``dt_in`` to ``dt_out`` (no-op within 1e-9)."""
    if abs(dt_in - dt_out) < 1e-9:
        return np.asarray(x, float)
    from fractions import Fraction
    r = Fraction(dt_in / dt_out).limit_denominator(1000)
    return resample_poly(np.asarray(x, float), r.numerator, r.denominator)


# --------------------------------------------------------------------------- #
# high-level driver
# --------------------------------------------------------------------------- #
def preprocess_component(
    path, *, dt=None, in_kind="vel", in_unit=None, skip=0,
    do_detrend="linear", taper_frac=0.0,
    fmin=None, fmax=None, filt_order=4, zerophase=True,
    target_dt=None,
) -> tuple[np.ndarray, float]:
    """Full raw-record -> ``(velocity_cm_s, dt)`` chain for one component.

    Steps (each skippable): read -> to cm-system -> de-trend -> taper ->
    band-pass -> to velocity -> de-trend velocity -> resample.
    With every optional step off this reduces to MATLAB ``convert_dis_vel_acc``:
    ``cumtrapz`` for acc, ``gradient`` for dis, identity for vel.
    """
    rec = read_record(path, dt=dt, kind=in_kind, unit=in_unit, skip=skip)
    unit = in_unit or rec.unit
    x = to_cm(rec.data, unit)

    if do_detrend:
        x = detrend(x, do_detrend)
    if taper_frac:
        x = cosine_taper(x, taper_frac)
    if fmin or fmax:
        x = bandpass(x, rec.dt, fmin, fmax, filt_order, zerophase)

    v = to_velocity(x, rec.dt, rec.kind)
    if do_detrend:
        v = detrend(v, do_detrend)

    out_dt = rec.dt
    if target_dt:
        v = resample_to(v, rec.dt, target_dt)
        out_dt = target_dt
    return np.asarray(v, float), out_dt


def write_vel_txt(vel: np.ndarray, path) -> None:
    """One sample per line, ``%f`` -- byte-compatible with the MATLAB
    ``fprintf(f, '%f\\n', vel)`` output that ``parse_segment`` reads back."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(path, np.asarray(vel, float), fmt="%f")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Batch raw -> <sta>_VEL_N.txt / <sta>_VEL_E.txt")
    p.add_argument("--stations", required=True, help="station-list text file")
    p.add_argument("--in-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--pattern-n", required=True,
                   help="filename pattern for the N component, e.g. "
                        "'{sta}_ACC_N.txt' or 'TK.{sta}..HNN.*.ASC'")
    p.add_argument("--pattern-e", required=True)
    p.add_argument("--in-kind", default="vel", choices=["acc", "vel", "dis"])
    p.add_argument("--in-unit", default=None,
                   help="override the input unit (else taken from the header, "
                        "or cm/s for plain text)")
    p.add_argument("--dt", type=float, default=None,
                   help="sampling interval for plain-text inputs")
    p.add_argument("--skip", type=int, default=0, help="header lines to skip (plain text)")
    p.add_argument("--detrend", default="linear",
                   choices=["none", "constant", "linear"])
    p.add_argument("--taper", type=float, default=0.0, help="taper fraction per end")
    p.add_argument("--fmin", type=float, default=None, help="high-pass corner [Hz]")
    p.add_argument("--fmax", type=float, default=None, help="low-pass corner [Hz]")
    p.add_argument("--filt-order", type=int, default=4)
    p.add_argument("--causal", action="store_true", help="causal filter (default: zero-phase)")
    p.add_argument("--target-dt", type=float, default=None, help="resample to this dt")
    return p


def _resolve(in_dir: Path, pattern: str, sta: str) -> Path:
    name = pattern.format(sta=sta)
    if any(ch in name for ch in "*?["):
        hits = sorted(in_dir.glob(name))
        if not hits:
            raise FileNotFoundError(f"no match for {name} in {in_dir}")
        return hits[0]
    return in_dir / name


def main(argv=None) -> None:
    args = _build_parser().parse_args(argv)
    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    stations = Path(args.stations).read_text().split()
    do_detrend = None if args.detrend == "none" else args.detrend

    common = dict(dt=args.dt, in_kind=args.in_kind, in_unit=args.in_unit,
                  skip=args.skip, do_detrend=do_detrend, taper_frac=args.taper,
                  fmin=args.fmin, fmax=args.fmax, filt_order=args.filt_order,
                  zerophase=not args.causal, target_dt=args.target_dt)

    for sta in stations:
        try:
            fn = _resolve(in_dir, args.pattern_n, sta)
            fe = _resolve(in_dir, args.pattern_e, sta)
            vn, dtn = preprocess_component(fn, **common)
            ve, dte = preprocess_component(fe, **common)
        except (FileNotFoundError, ValueError) as exc:
            print(f"{sta}: skipped ({exc})")
            continue
        n = min(vn.size, ve.size)
        write_vel_txt(vn[:n], out_dir / f"{sta}_VEL_N.txt")
        write_vel_txt(ve[:n], out_dir / f"{sta}_VEL_E.txt")
        print(f"{sta}: {n} pts, dt={dtn:g}s  ->  {out_dir}/{sta}_VEL_[NE].txt")


if __name__ == "__main__":
    main()
