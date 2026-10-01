"""Pre-release checks for the workbook-to-site reference catalog build."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import build_reference_catalogs as catalogs  # noqa: E402


def test_public_url_rejects_local_paths_and_non_urls():
    assert catalogs._public_url("/Users/name/Desktop/source.png") is None
    assert catalogs._public_url("NCREE original table in this workbook") is None
    assert catalogs._public_url("file:///tmp/source.fsp") is None
    assert catalogs._public_url("https://doi.org/10.1785/0120200376")
    assert catalogs._public_url(
        "https://earthquake.usgs.gov/earthquakes/eventpage/us7000irp8",
        host="earthquake.usgs.gov",
    )
    assert catalogs._public_url(
        "https://doi.org/10.1785/0120200376", host="earthquake.usgs.gov"
    ) is None


def test_committed_catalogs_are_public_safe_and_complete():
    expected = {"sb": (46, 243), "ncree": (56, 340), "yen": (9, 118)}
    for cat_id, (n_events, n_records) in expected.items():
        path = catalogs.OUT / f"{cat_id}.json"
        doc = json.loads(path.read_text())
        assert (doc["n_events"], doc["n_records"]) == (n_events, n_records)
        catalogs._validate_catalog(cat_id, doc["events"])
        raw = path.read_text()
        assert "/Users/" not in raw
        assert "/Volumes/" not in raw
        assert "file://" not in raw


def test_corrected_reference_values_reach_the_site_catalog():
    yen = json.loads((catalogs.OUT / "yen.json").read_text())
    events = {event["name"]: event for event in yen["events"]}

    second = events["Kumamoto second foreshock"]
    assert second["mag"] == 6.4
    assert second["depth_km"] == 5.9
    assert len(second["stations"]) == 12

    hualien = events["Hualien"]
    stations = {station["code"]: station for station in hualien["stations"]}
    assert stations["HWA028"]["rhyp_km"] == 28.0
    assert stations["TRB042"]["rhyp_km"] == 16.93

    duzce = events["Duzce"]
    assert all(station.get("rrup_km") is not None for station in duzce["stations"])
    assert all(station.get("rhyp_km") is None for station in duzce["stations"])
