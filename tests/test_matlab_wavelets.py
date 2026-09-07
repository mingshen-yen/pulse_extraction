"""Lightweight checks for the wavelet-toolbox ports (run with `pytest`)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_classification.matlab_wavelets import centfrq, scal2frq, matlab_cwt


def test_centfrq_db4_matches_matlab():
    # MATLAB: centfrq('db4') == 0.714285714285714
    assert abs(centfrq("db4") - 0.7142857142857143) < 1e-12


def test_scal2frq_inverse_of_tp():
    # Tp = 1 / scal2frq(scale, 'db4', dt) == scale * dt / centfrq
    dt, scale = 0.01, 120
    tp = 1.0 / scal2frq(scale, "db4", dt)
    assert abs(tp - scale * dt / centfrq("db4")) < 1e-12


def test_matlab_cwt_shape_and_localisation():
    n = 400
    sig = np.zeros(n)
    sig[200] = 1.0
    scales = [10, 20, 40]
    c = matlab_cwt(sig, scales, "db4")
    assert c.shape == (len(scales), n)
    # energy of an impulse response stays localised near the impulse
    for row in c:
        assert abs(int(np.argmax(np.abs(row))) - 200) < 30


def test_matlab_cwt_linearity():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(300)
    y = rng.standard_normal(300)
    s = [15, 30]
    a = matlab_cwt(3 * x + 2 * y, s)
    b = 3 * matlab_cwt(x, s) + 2 * matlab_cwt(y, s)
    assert np.allclose(a, b, atol=1e-9)
