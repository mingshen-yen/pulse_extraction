"""Tests for waveform.site_export -- the showcase-site JSON bundler."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.site_export import event_summary, haversine_km   # noqa: E402


def test_haversine_known_distance():
    # L'Aquila epicentre -> AQV, ~5 km
    d = haversine_km(42.342, 13.380, 42.377, 13.344)
    assert 3.5 < d < 6.0
    assert haversine_km(None, 1, 2, 3) is None


def _station(code, lat, lon, is_pulse, Tp, PGV, PI, n=400):
    return dict(code=code, network="NZ", lat=lat, lon=lon, vs30=400.0,
                is_pulse=is_pulse, Tp=Tp, PGV=PGV, PI=PI, angle_deg=12.3,
                late=False, qc="pass", dt=0.02,
                pulse=[0.0] * (n // 2) + [1.0, -1.0] * (n // 4))


EVENT = dict(id="test1", time="2010-09-03T16:35:41Z", lat=-43.55, lon=172.18,
             depth_km=10.0, mag=7.0, mag_type="Mw", name="Test", source="USGS")


def test_event_summary_shape_and_stats():
    stations = [
        _station("AAA", -43.53, 172.20, True, 6.2, 120.0, 5.0),
        _station("BBB", -43.60, 172.05, True, 8.1, 60.0, 3.0),
        _station("CCC", -43.90, 171.50, False, 2.0, 8.0, -5.0),
    ]
    out = event_summary(EVENT, stations)

    assert out["schema"] == "pulse-extraction/event/1"
    assert out["event"]["mag"] == 7.0
    assert len(out["stations"]) == 3
    a = out["stations"][0]
    assert a["repi_km"] is not None and a["repi_km"] < 10
    assert "pulse_trace" in a and a["pulse_trace"]["v"]          # downsampled
    assert len(a["pulse_trace"]["v"]) <= 240

    s = out["stats"]
    assert s["n"] == 3 and s["n_pulse"] == 2
    assert s["pulse_fraction"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["Tp_median"] == pytest.approx(7.15, abs=0.01)       # median(6.2, 8.1)
    assert s["by_distance"] and all("pulse_fraction" in b for b in s["by_distance"])
    assert len(s["scatter"]) == 3


def test_event_summary_downsamples_only_when_long():
    short = _station("S", -43.5, 172.2, True, 5.0, 50.0, 4.0, n=100)
    out = event_summary(EVENT, [short], trace_points=240)
    assert out["stations"][0]["pulse_trace"]["dt"] == pytest.approx(0.02)
    assert len(out["stations"][0]["pulse_trace"]["v"]) == 100


def test_event_summary_tolerates_missing_station_coords():
    st = _station("X", None, None, True, 5.0, 50.0, 4.0)
    out = event_summary(EVENT, [st])
    assert out["stations"][0]["repi_km"] is None
    assert out["stats"]["scatter"] == []                        # no distance -> skipped


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
