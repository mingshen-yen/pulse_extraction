"""Checks for the preprocessing chain (run with `pytest`, or plain `python`)."""

import sys
from pathlib import Path

import numpy as np
from scipy.integrate import cumulative_trapezoid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_classification.preprocess import (
    to_cm, detrend, to_velocity, resample_to, cosine_taper, GRAVITY_CM_S2,
)


def test_to_cm_units():
    x = np.array([1.0, 2.0])
    assert np.allclose(to_cm(x, "g"), x * GRAVITY_CM_S2)
    assert np.allclose(to_cm(x, "m/s"), x * 100)
    assert np.allclose(to_cm(x, "cm/s"), x)
    assert np.allclose(to_cm(x, "mm/s**2"), x * 0.1)


def test_to_velocity_acc_matches_cumtrapz():
    dt = 0.01
    acc = np.sin(np.linspace(0, 6, 500))
    v = to_velocity(acc, dt, "acc")
    assert np.allclose(v, cumulative_trapezoid(acc, dx=dt, initial=0.0))


def test_to_velocity_dis_matches_gradient():
    dt = 0.02
    dis = np.cumsum(np.random.default_rng(1).standard_normal(300)) * dt
    v = to_velocity(dis, dt, "dis")
    assert np.allclose(v, np.gradient(dis, dt))


def test_to_velocity_vel_identity():
    v = np.arange(10.0)
    assert np.array_equal(to_velocity(v, 0.01, "vel"), v)


def test_detrend_linear_removes_line():
    t = np.arange(200)
    x = 3.0 + 0.5 * t + np.sin(t / 5)
    d = detrend(x, "linear")
    assert abs(np.polyfit(t, d, 1)[0]) < 1e-9


def test_resample_roundtrip_length():
    x = np.sin(np.linspace(0, 20, 2000))
    y = resample_to(x, 0.005, 0.01)
    assert abs(y.size - 1000) <= 1
    assert np.array_equal(resample_to(x, 0.01, 0.01), x)


def test_cosine_taper_zeros_the_ends():
    x = np.ones(1000)
    y = cosine_taper(x, 0.05)
    assert y[0] == 0.0 and y[-1] == 0.0 and y[500] == 1.0


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    for name, fn in sorted(inspect.getmembers(mod, inspect.isfunction)):
        if name.startswith("test_"):
            fn()
            print("ok", name)
