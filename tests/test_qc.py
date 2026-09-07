"""Tests for waveform.qc -- the record quality-control gate."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.qc import check_record, QCError, QCThresholds       # noqa: E402
from waveform.pipeline import run_pulse                           # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def _nar():
    obspy = pytest.importorskip("obspy")
    b = str(FIX / "TK.NAR..HN{}.INT-20230206_0000008.ACC.CV.mseed")
    tr = [obspy.read(b.format(c))[0] for c in "ENZ"]
    return (tr[0].data.astype(float), tr[1].data.astype(float),
            tr[2].data.astype(float), float(tr[0].stats.delta))


def test_real_record_is_not_a_failure():
    e, n, z, dt = _nar()
    res = check_record(e, n, z, dt)
    assert res.level in ("pass", "warn")
    assert res.ok
    # no false clipping / dead / units failure on a clean strong-motion record
    assert not any(c.name.startswith(("dead", "clip", "pga", "finite"))
                   and c.status == "fail" for c in res.checks)


def test_nonfinite_fails():
    e, n, z, dt = _nar()
    e = e.copy()
    e[123] = np.nan
    res = check_record(e, n, z, dt)
    assert res.level == "fail"
    assert any(c.name == "finite" and c.status == "fail" for c in res.checks)


def test_dead_channel_fails():
    e, n, z, dt = _nar()
    res = check_record(np.zeros_like(e), n, z, dt)
    assert res.level == "fail"
    assert any(c.name == "dead[E]" and c.status == "fail" for c in res.checks)


def test_clipping_fails():
    e, n, z, dt = _nar()
    peak = np.max(np.abs(e))
    res = check_record(np.clip(e, -0.2 * peak, 0.2 * peak), n, z, dt)
    assert res.level == "fail"
    assert any(c.name.startswith("clip") and c.status == "fail" for c in res.checks)


def test_wrong_units_flagged_on_pga():
    e, n, z, dt = _nar()
    res = check_record(e * 3e4, n * 3e4, z * 3e4, dt)   # counts-scale amplitudes
    assert res.level == "fail"
    assert any(c.name == "pga" and c.status == "fail" for c in res.checks)


def test_too_short_fails():
    e, n, z, dt = _nar()
    k = int(10.0 / dt)
    res = check_record(e[:k], n[:k], z[:k], dt)
    assert res.level == "fail"
    assert any(c.name == "duration" and c.status == "fail" for c in res.checks)


def test_pure_noise_flagged_not_concentrated():
    rng = np.random.default_rng(0)
    n_pts = 12000
    dt = 0.01
    a = [rng.normal(0, 5, n_pts) for _ in range(3)]
    res = check_record(*a, dt)
    assert any(c.name == "event_concentration" and c.status == "warn"
               for c in res.checks)


def test_pipeline_gate_raises_on_fail():
    e, n, z, dt = _nar()
    e = e.copy()
    e[10] = np.inf
    with pytest.raises(QCError):
        run_pulse(e, n, z, dt, method="kamai", qc="gate")


def test_pipeline_attach_does_not_raise():
    e, n, z, dt = _nar()
    out = run_pulse(e, n, z, dt, method="kamai", qc="attach")
    assert out["qc"] is not None
    assert out["qc"]["level"] in ("pass", "warn", "fail")
    assert len(out["pulses"]) == 5


def test_pipeline_qc_off():
    e, n, z, dt = _nar()
    out = run_pulse(e, n, z, dt, method="kamai", qc="off")
    assert out["qc"] is None


def test_thresholds_are_overridable():
    e, n, z, dt = _nar()
    strict = QCThresholds(warn_duration_s=200.0)   # 105 s record now "short"
    res = check_record(e, n, z, dt, thresholds=strict)
    assert any(c.name == "duration" and c.status == "warn" for c in res.checks)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
