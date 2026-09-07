"""Port of ``classification_algo.m`` -- the stratified pulse-extraction loop.

For each of the 5 strongest time/scale cells of ``coefs1^2 + coefs2^2`` it
rotates the two horizontal components into the maximising direction, classifies
that pulse with :func:`analyze_record`, then zeroes the surrounding time band so
the next iteration finds a pulse from a different time-frequency region.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from .analyze_record import analyze_record
from .matlab_wavelets import matlab_cwt

_WNAME = "db4"
_TP_MIN = 0.25
_TP_MAX = 15.0
_NUM_SCALES = 50
_CF = 1.4                     # ~ 1 / centfrq('db4'); kept verbatim from MATLAB
_BLOCK_RANGE = 10.0 / 25.0
N_PULSES = 5


@dataclass
class AlgoResult:
    pulse_datas: List
    rot_angles: List[float]      # radians
    selected_col: List[int]      # 0-based time indices
    selected_row: List[int]      # 0-based scale indices
    scales: np.ndarray


def build_scales(dt: float) -> np.ndarray:
    """MATLAB:
        scaleMin  = floor(TpMin/1.4/dt)
        scaleStep = ceil((TpMax/1.4/dt - scaleMin)/numScales)
        scaleMax  = scaleMin + numScales*scaleStep
        scales    = scaleMin:scaleStep:scaleMax        (numScales+1 values)
    """
    scale_min = int(np.floor(_TP_MIN / _CF / dt))
    scale_step = int(np.ceil((_TP_MAX / _CF / dt - scale_min) / _NUM_SCALES))
    scale_max = scale_min + _NUM_SCALES * scale_step
    return np.arange(scale_min, scale_max + 1, scale_step)


def classification_algo(signal1, signal2, dt, verbose: bool = True) -> AlgoResult:
    signal1 = np.asarray(signal1, dtype=float).ravel()
    signal2 = np.asarray(signal2, dtype=float).ravel()
    n = signal1.size

    scales = build_scales(dt)
    coefs1 = matlab_cwt(signal1, scales, _WNAME)
    coefs2 = matlab_cwt(signal2, scales, _WNAME)
    max_coefs = coefs1 ** 2 + coefs2 ** 2         # (n_scales, n)

    pulse_datas, rot_angles, sel_col, sel_row = [], [], [], []
    time_index = np.arange(1, n + 1)              # MATLAB 1:length(signal1)

    for i in range(N_PULSES):
        peak = max_coefs.max()
        col = int(np.argmax(max_coefs.max(axis=0) == peak))   # first matching column
        row = int(np.argmax(max_coefs.max(axis=1) == peak))   # first matching row

        max_dir = np.arctan(coefs2[row, col] / coefs1[row, col])
        signal = signal1 * np.cos(max_dir) + signal2 * np.sin(max_dir)

        pdata = analyze_record(signal, dt, col, row, scales, _WNAME, max_dir)
        pulse_scale = scales[row]

        pulse_datas.append(pdata)
        rot_angles.append(float(max_dir))
        sel_col.append(col)
        sel_row.append(row)

        if verbose:
            ang = np.degrees(np.arctan(coefs2[row, col] / coefs1[row, col]))
            print(f"{ang:5.1f} {peak:.4g}")

        block_min = col - _BLOCK_RANGE * pulse_scale
        block_max = col + _BLOCK_RANGE * pulse_scale
        blocked = (time_index > block_min) & (time_index < block_max)
        max_coefs[:, blocked] = 0.0

    return AlgoResult(pulse_datas, rot_angles, sel_col, sel_row, scales)
