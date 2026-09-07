"""Port of ``analyze_record.m`` -- classify one extracted pulse as pulse-like or
non-pulse-like, and rebuild the pulse waveform from ``num_coefs`` wavelets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pywt

from .matlab_wavelets import matlab_cwt, scal2frq, wavefun_psi

NUM_COEFS = 10          # number of wavelet coefficients used to build the pulse
_WNAME = "db4"
_ROW_RANGE = 10.0 / 25.0
_WAVEFUN_ITER = 4

# logistic-regression constants from Shahi & Baker (kept verbatim)
_PC_A, _PC_B = 0.63, 0.777
_P_MEAN, _P_STD = 1.208421, 0.2462717
_V_MEAN, _V_STD = 11.58861, 18.88015
_LR = (-7.817, -0.5679, -0.1516, -3.0253, -1.7396, -2.7156)


@dataclass
class PulseData:
    dt: float
    num_pts: int
    Tp: float
    wavelet_name: str
    pulse_scale: float
    rows: np.ndarray
    coefs: np.ndarray
    PGV: float
    PGV_resid: float
    delta_energy_t: float
    late: bool
    pulse_indicator: float
    is_pulse: bool
    signal: np.ndarray
    pulse_th: np.ndarray
    resid_th: np.ndarray
    PC: float
    angles: float
    dwt_orig: float = 0.0
    dwt_resid: float = 0.0
    dwt_squared_orig: float = 0.0
    dwt_squared_resid: float = 0.0
    pulse_th_list: list = field(default_factory=list)


def _dwt_matrix(signal: np.ndarray, wname: str = _WNAME) -> np.ndarray:
    """Reproduce MATLAB's single-output ``cA = dwt(signal, wname)`` (symmetric
    half-point extension, one level, approximation coefficients only)."""
    cA, _cD = pywt.dwt(signal, wname, mode="symmetric")
    return cA


def _fn_extract_one_wavelet(signal, dt, pulse_scale, pulse_row):
    """Port of the nested ``fn_extract_one_wavelet``.

    Returns ``(coef, pulse_scale, col, Tp)`` -- ``col`` is a 0-based time index.
    """
    n = signal.size
    lo = max(0, int(pulse_row - np.ceil(pulse_scale * _ROW_RANGE)))
    hi = min(n, int(pulse_row + np.ceil(pulse_scale * _ROW_RANGE)) + 1)

    row = matlab_cwt(signal, [pulse_scale], _WNAME)[0]      # shape (n,)
    z = np.max(np.abs(row[lo:hi]))
    matches = np.where(np.abs(row) == z)[0]
    col = int(matches[0])
    coef = float(row[col])
    Tp = 1.0 / scal2frq(pulse_scale, _WNAME, dt)
    return coef, pulse_scale, col, Tp


def analyze_record(signal, dt, col, row, scales, wname=_WNAME, max_dir=0.0):
    """Port of ``analyze_record.m``.

    Parameters
    ----------
    signal : 1-D array          rotated velocity time history
    dt : float
    col : int                   0-based time index of the identified pulse
    row : int                   0-based scale index of the identified pulse
    scales : 1-D int array      scales used by the outer CWT
    wname : str
    max_dir : float             rotation angle [rad], stored as degrees on output
    """
    signal = np.asarray(signal, dtype=float).ravel()
    scales = np.atleast_1d(np.asarray(scales)).astype(int)
    n = signal.size
    num_scales = scales.size

    # --- refine the scales around the detected row (zoom in) -----------------
    lo = scales[max(0, row - 1)]
    hi = scales[min(num_scales - 1, row + 1)]
    refined = np.arange(lo, hi + 1)                      # MATLAB "a:b", step 1
    cwt_coefs = matlab_cwt(signal, refined, wname)       # (len(refined), n)
    z = np.abs(cwt_coefs[:, col])
    r = int(np.argmax(z))
    pulse_scale = int(refined[r])

    time = np.arange(1, n + 1) * dt
    psi, xval = wavefun_psi(wname, level=_WAVEFUN_ITER)

    resid_th = signal.copy()
    pulse_th = np.zeros_like(signal)
    coefs = np.zeros(NUM_COEFS)
    cols = np.zeros(NUM_COEFS, dtype=int)
    col0 = int(col)
    Tp = np.nan
    delta = np.nan
    pulse_th_steps: list[np.ndarray] = []

    for i in range(NUM_COEFS):
        coef_i, _, col_i, Tp = _fn_extract_one_wavelet(resid_th, dt, pulse_scale, col0)
        coefs[i] = coef_i
        cols[i] = col_i

        basis = xval * pulse_scale
        basis = basis + (col_i - np.median(basis))
        basis = basis * dt
        y_vals = psi * coef_i / np.sqrt(pulse_scale)
        delta = basis[1] - basis[0]

        num_pads = max(int(np.ceil((time.max() - basis.max()) / delta)), 0)
        left_axis = np.arange(0, basis.min() - 0.00001, delta)
        right_axis = (basis.max() + delta * np.arange(1, num_pads + 1))
        final_basis = np.concatenate([left_axis, basis, right_axis])
        final_yvals = np.concatenate([np.zeros(left_axis.size), y_vals, np.zeros(num_pads)])

        contrib = np.interp(time, final_basis, final_yvals, left=np.nan, right=np.nan)
        contrib[np.isnan(contrib)] = 0.0
        pulse_th = pulse_th + contrib
        resid_th = signal - pulse_th
        pulse_th_steps.append(pulse_th.copy())

    # --- "late" arrival check ---------------------------------------------------
    signal_E = np.cumsum(signal ** 2) / np.sum(signal ** 2) * 100.0
    pth_sq = np.sum(pulse_th ** 2)
    if pth_sq > 0:
        pulse_E = np.cumsum(pulse_th ** 2) / pth_sq * 100.0
        idx = np.where(pulse_E <= 5)[0]
        late_time = signal_E[idx[-1]] if idx.size else 0.0
    else:
        late_time = 0.0
    late = bool(late_time >= 17)

    # --- energy / PGV ratios -> pulse indicator ------------------------------
    dwt_orig = float(np.sum(np.abs(_dwt_matrix(signal, wname))))
    dwt_resid = float(np.sum(np.abs(_dwt_matrix(resid_th, wname))))
    dwt_sq_orig = float(np.sum(_dwt_matrix(signal, wname) ** 2))
    dwt_sq_resid = float(np.sum(_dwt_matrix(resid_th, wname) ** 2))

    PGV = float(np.max(np.abs(signal)))
    PGV_resid = float(np.max(np.abs(resid_th)))
    pgv_ratio = PGV_resid / PGV
    energy_ratio = dwt_sq_resid / dwt_sq_orig
    pc = _PC_A * pgv_ratio + _PC_B * energy_ratio

    P = (pc - _P_MEAN) / _P_STD
    V = (PGV - _V_MEAN) / _V_STD
    a0, a1, a2, a3, a4, a5 = _LR
    pulse_indicator = (a0 + a1 * P ** 2 + a2 * V ** 2
                       + a3 * P + a4 * V + a5 * P * V)
    is_pulse = bool(pulse_indicator > 0)

    return PulseData(
        dt=dt, num_pts=n, Tp=Tp, wavelet_name=wname, pulse_scale=pulse_scale,
        rows=cols, coefs=coefs, PGV=PGV, PGV_resid=PGV_resid,
        delta_energy_t=delta, late=late, pulse_indicator=pulse_indicator,
        is_pulse=is_pulse, signal=signal, pulse_th=pulse_th, resid_th=resid_th,
        PC=pc, angles=float(np.degrees(max_dir)),
        dwt_orig=dwt_orig, dwt_resid=dwt_resid,
        dwt_squared_orig=dwt_sq_orig, dwt_squared_resid=dwt_sq_resid,
        pulse_th_list=pulse_th_steps,
    )
