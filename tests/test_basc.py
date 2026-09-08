"""Regression + smoke tests for the BASC -> pulse-extraction bridge.

Golden arrays in ``fixtures/`` were produced by the *original* code in
``00_BASC_Fling_rm/BASC/`` on station TK.NAR of the 2023-02-06 Turkiye M7.8
event (raw 3-component acceleration in ``fixtures/TK.NAR..HN?...mseed``):

* ``nar_kamai_*``  -- ``obspy detrend('polynomial', order=6)`` -> ``funclib.baseline_KA``
  (the ``BASC_poly.ipynb`` chain), fed float64.
* ``nar_kamai_flingE`` -- ``funclib.FlingStep_rm(dispEp, 20.52, 1.3, 32.8)``.
* ``nar_ebasco_*`` -- the full ``eBASCO_FRM.ipynb`` driver over
  ``funclib_eBASCO``.  The original integrates in float32 (mseed dtype), so the
  refactor -- which works in float64 -- matches only to ~1e-4 relative; the
  selected T1/T2/T3 solution and the permanent displacement agree.

Run:  python -m pytest tests/test_basc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from waveform import basc                                       # noqa: E402
from waveform.classify import classify_velocity                 # noqa: E402
from waveform.ebasco import ebasco_correct                      # noqa: E402
from waveform.pipeline import (acc_to_velocity, run_pulse,      # noqa: E402
                               run_pulse_variants)

FIX = Path(__file__).resolve().parent / "fixtures"
_FLING = dict(t1=20.52, Tf=1.3, Dsite=32.8)


def _load_acc():
    obspy = pytest.importorskip("obspy")
    b = str(FIX / "TK.NAR..HN{}.INT-20230206_0000008.ACC.CV.mseed")
    e = obspy.read(b.format("E"))[0]
    n = obspy.read(b.format("N"))[0]
    z = obspy.read(b.format("Z"))[0]
    return (e.data.astype(float), n.data.astype(float), z.data.astype(float),
            float(e.stats.delta))


# --------------------------------------------------------------------------- #
# Kamai (BASC_poly) path -- deterministic, tight tolerance
# --------------------------------------------------------------------------- #
def test_kamai_correct_matches_original():
    acc_e, acc_n, acc_z, dt = _load_acc()
    vel_e, vel_n, disp_e, disp_n = basc.kamai_correct(acc_e, acc_n, acc_z, dt)

    np.testing.assert_allclose(vel_e, np.load(FIX / "nar_kamai_velEp.npy"), rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(vel_n, np.load(FIX / "nar_kamai_velNp.npy"), rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(disp_e, np.load(FIX / "nar_kamai_dispEp.npy"), rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(disp_n, np.load(FIX / "nar_kamai_dispNp.npy"), rtol=1e-9, atol=1e-9)


def test_flingstep_rm_matches_original():
    acc_e, acc_n, acc_z, dt = _load_acc()
    _, _, disp_e, _ = basc.kamai_correct(acc_e, acc_n, acc_z, dt)
    _, _, vel_resid = basc.flingstep_rm(disp_e, dt, **_FLING)
    np.testing.assert_allclose(vel_resid, np.load(FIX / "nar_kamai_flingE.npy"),
                               rtol=1e-9, atol=1e-9)


def test_flingstep_rm_uses_its_arguments():
    """The original hard-coded t1/Tf/Dsite in the body; ours must not."""
    disp = np.load(FIX / "nar_kamai_dispEp.npy")
    dt = 0.01
    _, f1, _ = basc.flingstep_rm(disp, dt, t1=20.0, Tf=1.0, Dsite=10.0)
    _, f2, _ = basc.flingstep_rm(disp, dt, t1=40.0, Tf=3.0, Dsite=25.0)
    assert not np.allclose(f1, f2)
    assert np.isclose(f1[-1], 10.0) and np.isclose(f2[-1], 25.0)


# --------------------------------------------------------------------------- #
# eBASCO path -- selection procedure, loose tolerance
# --------------------------------------------------------------------------- #
def test_ebasco_matches_original_selection():
    # legacy params: reproduces the funclib_eBASCO / eBASCO_FRM.ipynb driver
    # (no Arias pre-cut, T1 sampled with n_t1) that the golden arrays came from
    acc_e, acc_n, acc_z, dt = _load_acc()
    res = ebasco_correct(acc_e, acc_n, acc_z, dt, arias_cut=False, t1_count="t1")
    assert res.e.ok and res.n.ok

    np.testing.assert_allclose(res.e.vel, np.load(FIX / "nar_ebasco_vel_e.npy"),
                               rtol=2e-4, atol=2e-4)
    np.testing.assert_allclose(res.n.vel, np.load(FIX / "nar_ebasco_vel_n.npy"),
                               rtol=2e-4, atol=2e-4)
    # permanent displacement is preserved (Kamai poly path would kill it)
    assert abs(res.e.permanent_disp - np.load(FIX / "nar_ebasco_disp_e.npy")[-1]) < 1e-2
    assert abs(res.n.permanent_disp) > 1.0


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #
def test_pipeline_does_not_mutate_inputs():
    acc_e, acc_n, acc_z, dt = _load_acc()
    ref = acc_e.copy()
    acc_to_velocity(acc_e, acc_n, acc_z, dt)
    np.testing.assert_array_equal(acc_e, ref)


@pytest.mark.parametrize("method", ["kamai", "ebasco"])
def test_pipeline_runs_and_is_finite(method):
    acc_e, acc_n, acc_z, dt = _load_acc()
    out = run_pulse(acc_e, acc_n, acc_z, dt, method=method)

    assert out["method"].startswith(method)
    assert out["npts"] > 1000
    assert len(out["pulses"]) == 5
    for p in out["pulses"]:
        assert np.isfinite(p["pulse_indicator"])
    assert np.all(np.isfinite(out["vel_n"]))
    assert np.all(np.isfinite(out["vel_e"]))


def test_pipeline_kamai_with_auto_fling():
    acc_e, acc_n, acc_z, dt = _load_acc()
    out = run_pulse(acc_e, acc_n, acc_z, dt, method="kamai", remove_fling=True)
    assert out["fling_removed"] in (True, False)   # auto-estimate may decline
    assert len(out["pulses"]) == 5


def test_run_pulse_variants_splits_fling():
    """`basc` keeps the permanent displacement, `fling_removed` zeroes it."""
    acc_e, acc_n, acc_z, dt = _load_acc()
    # BASC_poly.py hand-pick for TK.NAR: t1=20.52 s, Tf=1.3 s, Dsite=32.8 cm
    out = run_pulse_variants(acc_e, acc_n, acc_z, dt,
                             fling_params=dict(t1=20.52, Tf=1.3, Dsite=32.8))

    assert set(out) >= {"variants", "fling_params", "method", "dt", "qc"}
    variants = out["variants"]
    assert set(variants) == {"basc", "fling_removed"}
    d_ret = np.array(variants["basc"]["disp_e"])
    d_rem = np.array(variants["fling_removed"]["disp_e"])
    assert abs(d_ret[-1]) > 10.0            # permanent displacement retained
    assert abs(d_rem[-1]) < abs(d_ret[-1]) / 3   # and removed in the other
    for v in variants.values():
        assert v["method"] == "kamai+fling" and len(v["pulses"]) == 5
        assert np.all(np.isfinite(v["vel_n"])) and np.all(np.isfinite(v["vel_e"]))


def test_classify_velocity_standalone_matches_pipeline():
    """The facade run directly on corrected velocity == what run_pulse reports."""
    acc_e, acc_n, acc_z, dt = _load_acc()
    vr = acc_to_velocity(acc_e, acc_n, acc_z, dt, method="kamai")
    direct = classify_velocity(vr.vel_n, vr.vel_e, dt)
    viap = run_pulse(acc_e, acc_n, acc_z, dt, method="kamai", qc="off")

    assert direct["any_pulse"] == viap["any_pulse"]
    for a, b in zip(direct["pulses"], viap["pulses"]):
        assert a["is_pulse"] == b["is_pulse"]
        assert a["Tp"] == pytest.approx(b["Tp"])
        assert a["PGV"] == pytest.approx(b["PGV"])


def test_classify_velocity_can_drop_waveforms():
    acc_e, acc_n, acc_z, dt = _load_acc()
    vr = acc_to_velocity(acc_e, acc_n, acc_z, dt, method="kamai")
    lean = classify_velocity(vr.vel_n, vr.vel_e, dt, include_waveforms=False)
    assert "rotated_wave" not in lean["pulses"][0]
    assert lean["pulses"][0]["pulse_peak_time"] is not None   # kept even in lean mode
    assert len(lean["pulses"]) == 5


def test_select_earliest_prefers_earlier_pulse():
    """`earliest` never reports a later pulse than `strongest` when the two
    top candidates are within tolerance; it picks the first-arriving one."""
    acc_e, acc_n, acc_z, dt = _load_acc()
    vr = acc_to_velocity(acc_e, acc_n, acc_z, dt, method="kamai")

    strong = classify_velocity(vr.vel_n, vr.vel_e, dt, select="strongest")
    early = classify_velocity(vr.vel_n, vr.vel_e, dt, select="earliest",
                              early_tol=0.5)
    assert strong["select"] == "strongest" and early["select"] == "earliest"
    ps = strong["pulses"][strong["primary"] - 1]
    pe = early["pulses"][early["primary"] - 1]
    assert pe["pulse_peak_time"] <= ps["pulse_peak_time"] + 1e-9
    # both indices are valid pulse-like picks
    assert 1 <= early["primary"] <= 5


def test_kamai_fling_decompose_fixed_vs_fitted():
    acc_e, acc_n, acc_z, dt = _load_acc()
    n = acc_e.size
    t = np.arange(n) * dt
    ae = basc.detrend_poly(acc_e, 6)
    fixed = basc.kamai_fling_decompose(ae, t, dt, 20.52, 1.3, Dsite=32.8)
    fitted = basc.kamai_fling_decompose(ae, t, dt, 20.52, 1.3)
    assert fixed["Dsite"] == 32.8
    # retained keeps a step, removed drives the tail toward zero
    assert abs(fixed["retained"][2][-1]) > abs(fixed["removed"][2][-1])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
