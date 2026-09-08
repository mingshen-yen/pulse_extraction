"""Tests for waveform.fetch (CWA + ESM readers) and waveform.batch.

The live ESM / FDSN network paths are not exercised here; only the DYNA .ASC
parsing and ZIP assembly are.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.batch import batch_cwa_freefield                    # noqa: E402
from waveform.fetch import (_parse_dyna_asc, read_cwa_freefield,  # noqa: E402
                            read_esm_asc_zip)

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


# --------------------------------------------------------------------------- #
# ESM DYNA .ASC
# --------------------------------------------------------------------------- #
def _dyna_asc(stream, data, dt=0.01, station="AMT", network="IT"):
    hdr = [
        "EVENT_NAME: TEST", "EVENT_ID: EMSC-TEST_0001",
        "EVENT_DATE_YYYYMMDD: 20160824", "EVENT_TIME_HHMMSS: 013632",
        "EVENT_LATITUDE_DEGREE: 42.70", "EVENT_LONGITUDE_DEGREE: 13.23",
        "EVENT_DEPTH_KM: 8.1", "MAGNITUDE_W: 6.0", "MAGNITUDE_L: ",
        f"NETWORK: {network}", f"STATION_CODE: {station}", "STATION_NAME: Amatrice",
        "STATION_LATITUDE_DEGREE: 42.632500", "STATION_LONGITUDE_DEGREE: 13.286400",
        "VS30_M/S: 670", "SITE_CLASSIFICATION_EC8: B",
        "EPICENTRAL_DISTANCE_KM: 8.5",
        "DATE_TIME_FIRST_SAMPLE_YYYYMMDD_HHMMSS: 20160824_013628.000",
        f"SAMPLING_INTERVAL_S: {dt:.6f}", f"NDATA: {len(data)}",
        f"DURATION_S: {len(data) * dt:.3f}", f"STREAM: {stream}",
        "UNITS: cm/s^2", "BASELINE_CORRECTION: BASELINE NOT REMOVED",
        "DATABASE_VERSION: HEADER_FORMAT: DYNA 1.2",
        "DATA_TYPE: ACCELERATION", "PROCESSING: none",
        "DATA_LICENSE: CC-BY",
    ]
    body = "\n".join(f"{v:.6f}" for v in data)
    return ("\n".join(hdr) + "\n" + body + "\n").encode()


def _esm_zip(dt=0.01, n=3000, pulse=True, streams=("HGE", "HGN", "HGZ")):
    t = np.arange(n) * dt
    rng = np.random.default_rng(1)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for s in streams:
            a = rng.normal(0, 0.3, n)
            if pulse and s[-1] in "EN12":
                m = (t >= 12.0) & (t <= 20.0)
                a[m] += 35 * np.sin(2 * np.pi * t[m] / 2.0) * np.hanning(m.sum())
            zf.writestr(f"IT.AMT..{s}.D.EMSC-TEST_0001.ACC.CV.ASC",
                        _dyna_asc(s, a, dt=dt))
    return buf.getvalue()


def test_parse_dyna_asc_splits_header_and_data():
    raw = _dyna_asc("HGE", np.arange(50, dtype=float) * 0.1, dt=0.02).decode()
    data, hdr = _parse_dyna_asc(raw)
    assert hdr["STATION_CODE"] == "AMT"
    assert hdr["dt"] == pytest.approx(0.02)
    assert hdr["npts"] == 50
    assert len(data) == 50 and data[10] == pytest.approx(1.0)


def test_read_esm_asc_zip_assembles_three_components(tmp_path):
    z = tmp_path / "esm.zip"
    z.write_bytes(_esm_zip())
    acc = read_esm_asc_zip(z)
    assert acc.dt == pytest.approx(0.01)
    assert len(acc.acc_e) == len(acc.acc_n) == len(acc.acc_z) == 3000
    m = acc.meta
    assert m["format"] == "esm-dyna-asc"
    assert m["station"] == "AMT" and m["network"] == "IT"
    assert m["magnitude"] == pytest.approx(6.0)
    assert m["vs30"] == pytest.approx(670.0)
    assert m["epicentral_distance_km"] == pytest.approx(8.5)
    assert m["response"]["source"] == "assumed-physical"
    assert m["response_removed"] is False


def test_read_esm_asc_zip_maps_numeric_streams(tmp_path):
    z = tmp_path / "esm12.zip"
    z.write_bytes(_esm_zip(streams=("HN2", "HN1", "HNZ")))   # 2->E, 1->N, Z->Z
    acc = read_esm_asc_zip(z)
    assert acc.meta["component_map"].startswith("HN1/HN2/HN3")
    assert len(acc.acc_e) == 3000


def test_read_esm_asc_zip_rejects_incomplete(tmp_path):
    z = tmp_path / "bad.zip"
    z.write_bytes(_esm_zip(streams=("HGE", "HGN")))          # no vertical
    with pytest.raises(ValueError, match="missing component"):
        read_esm_asc_zip(z)


def test_read_esm_asc_zip_runs_through_pipeline(tmp_path):
    from waveform.pipeline import run_pulse
    z = tmp_path / "esm.zip"
    z.write_bytes(_esm_zip(pulse=True))
    acc = read_esm_asc_zip(z)
    out = run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt, method="kamai",
                    response=acc.meta["response"], window="arias", decimate_to=50)
    assert out["primary"] >= 1
    assert out["dt"] == pytest.approx(0.02)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
