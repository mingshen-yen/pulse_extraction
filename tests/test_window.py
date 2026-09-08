"""Tests for waveform.window -- strong-motion windowing + decimation."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.window import (arias_bounds, decimate, prepare,           # noqa: E402
                             strong_motion_window)
from waveform.pipeline import run_pulse                                 # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def _nar():
    obspy = pytest.importorskip("obspy")
    b = str(FIX / "TK.NAR..HN{}.INT-20230206_0000008.ACC.CV.mseed")
    tr = [obspy.read(b.format(c))[0] for c in "ENZ"]
    return (tr[0].data.astype(float), tr[1].data.astype(float),
            tr[2].data.astype(float), float(tr[0].stats.delta))


def _synthetic(dt=0.01, n=6000, t_on=20.0, t_off=45.0):
    """quiet - burst - quiet acceleration."""
    t = np.arange(n) * dt
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.2, n)
    burst = np.zeros(n)
    m = (t >= t_on) & (t <= t_off)
    burst[m] = 30 * np.sin(2 * np.pi * t[m] / 3.0) * np.hanning(m.sum())
    a = noise + burst
    return a, a * 0.8, a * 0.5, dt


def test_arias_bounds_brackets_the_burst():
    a, _, _, dt = _synthetic()
    lo, hi = arias_bounds(a, dt, pre=5.0, post=5.0)
    # the 5-95 % energy of the (hanning-tapered) 20-45 s burst is ~26-38 s
    assert lo * dt < 27.0 and hi * dt > 37.0          # burst energy inside
    assert lo * dt > 12.0 and hi * dt < 52.0          # far quiet trimmed


def test_strong_motion_window_keeps_components_aligned():
    e, n, z, dt = _synthetic()
    we, wn, wz, lo, hi = strong_motion_window(e, n, z, dt)
    assert len(we) == len(wn) == len(wz) == hi - lo
    assert len(we) < len(e)


def test_decimate_halves_100hz_to_50hz():
    e, n, z, dt = _nar()
    de, dn, dz, ndt, fac = decimate(e, n, z, dt, target_rate=50.0)
    assert fac == 2 and ndt == pytest.approx(0.02)
    assert len(de) == pytest.approx(len(e) / 2, abs=2)
    # the anti-alias filter attenuates the sharp *acceleration* peak a little,
    # but energy is preserved to within ~15 %
    e_full = np.sqrt(np.mean(e ** 2))
    e_dec = np.sqrt(np.mean(de ** 2))
    assert e_dec == pytest.approx(e_full, rel=0.15)


def test_decimate_noop_when_already_low_rate():
    e, n, z, dt = _synthetic(dt=0.05)                 # 20 Hz
    de, dn, dz, ndt, fac = decimate(e, n, z, dt, target_rate=50.0)
    assert fac == 1 and ndt == dt and len(de) == len(e)


def test_prepare_reports_what_it_did():
    e, n, z, dt = _synthetic()                        # 100 Hz
    oe, on, oz, odt, info = prepare(e, n, z, dt, window="arias", decimate_to=50)
    assert info["window"] is not None
    assert info["decimate_factor"] == 2              # 100 Hz -> 50 Hz
    assert odt == pytest.approx(0.02)
    assert info["n_out"] == len(oe) < info["n_in"]


def test_run_pulse_window_decimate_matches_full(tmp_path=None):
    """Arias window + 50 Hz decimation must not move Tp/PGV meaningfully."""
    e, n, z, dt = _nar()
    full = run_pulse(e, n, z, dt, method="kamai", qc="off")
    fast = run_pulse(e, n, z, dt, method="kamai", qc="off",
                     window="arias", decimate_to=50)
    pf = full["pulses"][full["primary"] - 1]
    px = fast["pulses"][fast["primary"] - 1]
    assert px["Tp"] == pytest.approx(pf["Tp"], abs=0.15)
    assert px["PGV"] == pytest.approx(pf["PGV"], rel=0.20)
    assert px["is_pulse"] == pf["is_pulse"]
    assert fast["preprocess"]["decimate_factor"] == 2
    assert fast["dt"] == pytest.approx(0.02)


def test_qc_sees_untrimmed_record():
    """A record that is long enough only before trimming must still pass the
    duration check (QC runs before the window)."""
    e, n, z, dt = _nar()                              # 105 s
    out = run_pulse(e, n, z, dt, method="kamai", qc="attach",
                    response="assumed-physical", window="arias")
    dur = next(c for c in out["qc"]["checks"] if c["name"] == "duration")
    assert dur["status"] == "ok"                      # measured on the full 105 s


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
