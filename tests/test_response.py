"""Tests for waveform.response -- the StationXML / instrument-response resolver.

Only the offline fallback logic is exercised (file / cache / nominal /
assumed-physical / none); the FDSN and routing paths need a network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.response import (resolve_response, apply_response,        # noqa: E402
                               _looks_physical)
from waveform.qc import check_record                                   # noqa: E402

T0 = "2023-02-06T01:17:00"
T1 = "2023-02-06T01:20:00"


def _resolve(**kw):
    kw.setdefault("client", None)
    kw.setdefault("routing", False)
    return resolve_response("TK", "NAR", "*", "HN?", T0, T1, **kw)


# --------------------------------------------------------------------------- #
def test_looks_physical_classifies():
    assert _looks_physical(np.array([0.01, -7.8, 3.2])) is True       # m/s**2-ish
    assert _looks_physical(np.array([12.3, -780.4, 340.1])) is True   # gal-ish
    assert _looks_physical(np.round(np.linspace(-3e5, 3e5, 500))) is False  # counts
    assert _looks_physical(np.array([2e6, -1e6])) is False
    assert _looks_physical(np.round(np.linspace(-8e3, 8e3, 500))) is False  # int counts
    assert _looks_physical(None) is None


def test_explicit_file(tmp_path):
    obspy = pytest.importorskip("obspy")
    inv = obspy.read_inventory()               # bundled example inventory
    p = tmp_path / "resp.xml"
    inv.write(str(p), format="STATIONXML")
    info = _resolve(stationxml=str(p))
    assert info.source == "file" and info.level == "ok"
    assert info.inventory is not None


def test_missing_file_falls_through(tmp_path):
    info = _resolve(stationxml=str(tmp_path / "nope.xml"),
                    cache_dir=tmp_path, data_sample=np.array([1.2, -8.4, 3.1]))
    assert info.source == "assumed-physical" and info.level == "warn"


def test_nominal_scalar(tmp_path):
    info = _resolve(cache_dir=tmp_path, nominal_sensitivity=4.0e5)
    assert info.source == "nominal" and info.level == "warn"
    assert info.scalar_sensitivity == 4.0e5


def test_nominal_dict_keying(tmp_path):
    info = _resolve(cache_dir=tmp_path,
                    nominal_sensitivity={"TK.NAR.HN?": 1.23e5, "*": 9.9e9})
    assert info.scalar_sensitivity == 1.23e5


def test_counts_without_response_fails(tmp_path):
    counts = np.round(np.linspace(-2e5, 2e5, 4000)).astype(float)
    info = _resolve(cache_dir=tmp_path, data_sample=counts)
    assert info.source == "none" and info.level == "fail"
    assert not info.ok


def test_cache_hit(tmp_path):
    obspy = pytest.importorskip("obspy")
    inv = obspy.read_inventory()
    net = inv[0].code
    sta = inv[0][0].code
    (tmp_path / f"{net}.{sta}.xml").write_bytes(
        _inv_bytes(inv))
    info = resolve_response(net, sta, "*", "*",
                            inv[0][0].start_date or T0,
                            inv[0][0].end_date or T1,
                            client=None, routing=False, cache_dir=tmp_path)
    assert info.source in ("cache", "fdsn-other-epoch")
    assert info.inventory is not None


def _inv_bytes(inv):
    import io
    buf = io.BytesIO()
    inv.write(buf, format="STATIONXML")
    return buf.getvalue()


def test_apply_response_nominal_scales_counts():
    obspy = pytest.importorskip("obspy")
    from waveform.response import ResponseInfo
    tr = obspy.Trace(data=np.full(1000, 1.0e5), header={"delta": 0.01})
    info = ResponseInfo("nominal", "warn", scalar_sensitivity=1.0e5)
    apply_response(tr, info)
    # 1e5 counts / (1e5 counts per m/s**2) = 1 m/s**2 = 100 cm/s**2 (minus demean)
    assert abs(np.max(np.abs(tr.data))) < 1e-6   # constant -> demeaned to ~0
    tr2 = obspy.Trace(data=np.arange(1000, dtype=float) * 1.0e3,
                      header={"delta": 0.01})
    apply_response(tr2, ResponseInfo("nominal", "warn", scalar_sensitivity=1.0e5))
    assert np.max(np.abs(tr2.data)) == pytest.approx(
        np.max(np.abs((np.arange(1000) * 1e3 - np.mean(np.arange(1000) * 1e3))
                      / 1e5 * 100)))


def test_apply_response_none_raises():
    obspy = pytest.importorskip("obspy")
    from waveform.response import ResponseInfo
    tr = obspy.Trace(data=np.ones(10), header={"delta": 0.01})
    with pytest.raises(ValueError):
        apply_response(tr, ResponseInfo("none", "fail"))


def test_qc_folds_response_level():
    e = np.random.default_rng(0).normal(0, 50, 12000)
    res = check_record(e, e * 1.1, e * 0.9, 0.01, response={"source": "nominal"})
    assert any(c.name == "response" and c.status == "warn" for c in res.checks)
    res2 = check_record(e, e, e, 0.01, response="none")
    assert res2.level == "fail"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
