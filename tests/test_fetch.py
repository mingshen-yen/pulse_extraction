"""Tests for waveform.fetch.read_cwa_freefield and waveform.batch."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.batch import batch_cwa_freefield                    # noqa: E402
from waveform.fetch import read_cwa_freefield                     # noqa: E402

SR = 100.0


def _write_cwa(path, code="HWA999", kind="CVA", n=4000, sr=SR, pulse=True):
    """A minimal CWA FreeField ASCII record: quiet - (optional) pulse - quiet."""
    dt = 1.0 / sr
    t = np.arange(n) * dt
    rng = np.random.default_rng(abs(hash(code)) % 2**32)
    u = rng.normal(0, 0.3, n)
    n_c = rng.normal(0, 0.3, n)
    e_c = rng.normal(0, 0.3, n)
    if pulse:
        m = (t >= 15.0) & (t <= 27.0)
        env = np.hanning(m.sum())
        e_c[m] += 40 * np.sin(2 * np.pi * t[m] / 3.0) * env
        n_c[m] += 25 * np.sin(2 * np.pi * t[m] / 3.0) * env
    hdr = (f"#StationCode: {code}\n"
           f"#InstrumentKind: {kind}  (test.{kind})\n"
           f"#StartTime: 2018/02/06-15:50:05.000\n"
           f"#RecordLength(sec):  {n * dt:.3f}\n"
           f"#SampleRate(Hz): {sr:g}\n"
           f"#AmplitudeUnit:  gal. DCoffset(corr)\n"
           f"#DataSequence: Time U(+); N(+); E(+)\n")
    body = "\n".join(f"{t[i]:10.3f}{u[i]:10.3f}{n_c[i]:10.3f}{e_c[i]:10.3f}"
                     for i in range(n))
    Path(path).write_text(hdr + body + "\n")


def test_read_cwa_freefield_parses_header_and_columns(tmp_path):
    f = tmp_path / "12345678.CVA.txt"
    _write_cwa(f, code="HWA057-ETL", kind="CVA")
    acc = read_cwa_freefield(f)
    assert acc.dt == pytest.approx(1.0 / SR)
    assert len(acc.acc_e) == len(acc.acc_n) == len(acc.acc_z) == 4000
    assert acc.meta["station"] == "HWA057"          # suffix stripped
    assert acc.meta["station_code"] == "HWA057-ETL"
    assert acc.meta["instrument_kind"] == "CVA"
    assert acc.meta["format"] == "cwa-freefield"
    assert acc.meta["response"]["source"] == "assumed-physical"
    assert acc.meta["response_removed"] is False


def test_read_cwa_freefield_falls_back_to_time_column(tmp_path):
    f = tmp_path / "nosr.CVA.txt"
    _write_cwa(f)
    txt = f.read_text().replace("#SampleRate(Hz): 100\n", "")
    f.write_text(txt)
    acc = read_cwa_freefield(f)
    assert acc.dt == pytest.approx(1.0 / SR, rel=1e-6)


def test_read_cwa_freefield_rejects_short_record(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("#StationCode: X\n0.0 1.0 2.0\n0.01 1.0 2.0\n")
    with pytest.raises(ValueError):
        read_cwa_freefield(f)


def test_batch_cwa_freefield_writes_one_row_per_record(tmp_path):
    rec = tmp_path / "Record"
    rec.mkdir()
    _write_cwa(rec / "AAA01.CVA.txt", code="HWA101", pulse=True)
    _write_cwa(rec / "BBB02.CVA.txt", code="HWA102", pulse=False)
    out = tmp_path / "pulses.csv"
    rows = batch_cwa_freefield(rec, out, qc="attach", verbose=False)

    assert out.exists()
    assert len(rows) == 2
    assert all(not r["error"] for r in rows)
    by_sta = {r["station"]: r for r in rows}
    assert by_sta["HWA101"]["is_pulse"] == 1
    assert by_sta["HWA101"]["Tp"] == pytest.approx(3.0, abs=0.6)
    assert by_sta["HWA102"]["is_pulse"] == 0
    # decimated 100 -> 50 Hz, Arias-trimmed
    assert by_sta["HWA101"]["dt_out"] == pytest.approx(0.02)
    assert by_sta["HWA101"]["npts_out"] < 4000


def test_batch_cwa_freefield_records_errors_and_continues(tmp_path):
    rec = tmp_path / "Record"
    rec.mkdir()
    _write_cwa(rec / "GOOD.CVA.txt", code="HWA200", pulse=True)
    (rec / "BROKEN.CVA.txt").write_text("#StationCode: NOPE\nnot numbers here\n")
    out = tmp_path / "pulses.csv"
    rows = batch_cwa_freefield(rec, out, qc="attach", verbose=False)

    assert len(rows) == 2
    err = {r["record"]: r["error"] for r in rows}
    assert err["GOOD.CVA"] == ""
    assert err["BROKEN.CVA"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
