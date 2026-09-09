"""Smoke tests for the waveform.run_record CLI.

Exercises the input-source selection in ``_load`` (local MiniSEED, saved ESM
DYNA ZIP), the ``--window`` / ``--decimate`` wiring, and the six output files.
No network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from waveform.run_record import main                                # noqa: E402
from tests.test_fetch import _esm_zip                               # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
MSEED = [str(FIX / f"TK.NAR..HN{c}.INT-20230206_0000008.ACC.CV.mseed")
         for c in "ENZ"]


def _outputs(d: Path, sta: str):
    return sorted(p.name for p in d.iterdir())


def test_mseed_writes_six_files(tmp_path):
    pytest.importorskip("obspy")
    main(["--sta", "NAR", "--mseed", *MSEED, "--qc", "attach",
          "--out", str(tmp_path), "--quiet"])
    names = _outputs(tmp_path, "NAR")
    for tag in ("basc", "frm"):
        assert f"NAR_VEL_N_{tag}.txt" in names
        assert f"NAR_VEL_E_{tag}.txt" in names
        assert f"NAR_pulse_{tag}.json" in names
    assert "NAR_qc.json" in names
    summ = json.loads((tmp_path / "NAR_pulse_basc.json").read_text())
    assert summ["dt"] == pytest.approx(0.01)
    assert summ["pulses"] and "Tp" in summ["pulses"][0]


def test_window_decimate_changes_dt(tmp_path):
    pytest.importorskip("obspy")
    main(["--sta", "NAR", "--mseed", *MSEED, "--qc", "attach",
          "--window", "arias", "--decimate", "50",
          "--out", str(tmp_path), "--quiet"])
    summ = json.loads((tmp_path / "NAR_pulse_basc.json").read_text())
    assert summ["dt"] == pytest.approx(0.02)          # 100 Hz -> 50 Hz
    vel = np.loadtxt(tmp_path / "NAR_VEL_N_basc.txt")
    assert len(vel) == summ["npts"] < 10500           # trimmed + decimated


def test_esm_zip_source(tmp_path):
    z = tmp_path / "esm.zip"
    z.write_bytes(_esm_zip(pulse=True))
    out = tmp_path / "out"
    main(["--sta", "AMT", "--esm-zip", str(z), "--qc", "attach",
          "--out", str(out), "--quiet"])
    assert (out / "AMT_pulse_basc.json").exists()
    assert (out / "AMT_VEL_E_frm.txt").exists()


def test_missing_source_errors(tmp_path):
    with pytest.raises(SystemExit):
        main(["--sta", "NAR", "--out", str(tmp_path), "--quiet"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
