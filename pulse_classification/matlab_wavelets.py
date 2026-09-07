"""Faithful re-implementations of the MATLAB Wavelet Toolbox routines that the
original pulse-classification code relies on.

The original MATLAB code calls ``cwt(signal, scales, 'db4')`` -- i.e. the *old*
(pre-R2016b) continuous wavelet transform driven by a **discrete** wavelet
(Daubechies-4).  ``pywt.cwt`` cannot do this (it only accepts continuous
wavelets), so we reproduce MATLAB's internal algorithm here:

    1. take the integral of the (refined) wavelet function  -> ``intwave``
    2. for every scale ``a`` resample that integral,
    3. convolve with the signal, differentiate, keep the central part,
    4. multiply by ``-sqrt(a)``.

References
----------
MATLAB ``cwt.m`` / ``intwave.m`` / ``scal2frq.m`` / ``centfrq.m`` (R2016a).
"""

from __future__ import annotations

import numpy as np
import pywt

__all__ = ["intwave", "matlab_cwt", "centfrq", "scal2frq", "wavefun_psi"]

_INTWAVE_PRECISION = 10  # MATLAB cwt() default is intwave(wname, 10)


def wavefun_psi(wname: str = "db4", level: int = 4):
    """Return ``(psi, xval)`` the way MATLAB ``wavefun`` does for an orthogonal
    wavelet (``[phi, psi, xval] = wavefun(wname, level)``)."""
    phi, psi, x = pywt.Wavelet(wname).wavefun(level=level)
    return np.asarray(psi, dtype=float), np.asarray(x, dtype=float)


def intwave(wname: str = "db4", precision: int = _INTWAVE_PRECISION):
    """MATLAB ``[integ, xval] = intwave(wname, precision)``.

    ``integ`` is the running integral (cumulative sum * step) of the wavelet
    function ``psi`` sampled on ``xval``.
    """
    psi, x = wavefun_psi(wname, level=precision)
    step = x[1] - x[0]
    integ = np.cumsum(psi) * step
    return integ, x


def matlab_cwt(signal: np.ndarray, scales, wname: str = "db4") -> np.ndarray:
    """Port of the old MATLAB ``cwt(signal, scales, wname)`` for a discrete
    wavelet.

    Parameters
    ----------
    signal : 1-D array
    scales : int or sequence of int
        Integer scales, exactly as produced by ``classification_algo``.
    wname : str
        Only ``'db4'`` is exercised by the original code, but any discrete
        orthogonal wavelet works.

    Returns
    -------
    coefs : ndarray, shape ``(len(scales), len(signal))``
    """
    signal = np.asarray(signal, dtype=float).ravel()
    scales = np.atleast_1d(np.asarray(scales)).astype(float)
    n_sig = signal.size

    psi_integ, xval = intwave(wname, _INTWAVE_PRECISION)
    step_x = xval[1] - xval[0]
    x_span = xval[-1] - xval[0]
    n_int = psi_integ.size

    coefs = np.empty((scales.size, n_sig), dtype=float)

    for i, a in enumerate(scales):
        # k = 0 : floor(a * x_span)      (MATLAB "0 : a*(xVALmax-xVALmin)")
        k = np.arange(0, int(np.floor(a * x_span)) + 1)
        idx = np.floor(k / (a * step_x)).astype(int)
        idx = np.clip(idx, 0, n_int - 1)
        if idx.size == 1:                       # MATLAB: if length(j)==1, j=[1 1]
            idx = np.array([idx[0], idx[0]])
        f = psi_integ[idx][::-1]

        conv_full = np.convolve(signal, f)      # 'full', length n_sig + len(f) - 1
        d = np.diff(conv_full)                  # length n_sig + len(f) - 2
        coefs[i, :] = -np.sqrt(a) * _wkeep(d, n_sig)

    return coefs


def _wkeep(x: np.ndarray, length: int) -> np.ndarray:
    """MATLAB ``wkeep1(x, length)`` -- keep the central ``length`` samples."""
    n = x.size
    if length >= n:
        return x
    start = int(np.floor((n - length) / 2.0))
    return x[start:start + length]


def centfrq(wname: str = "db4", precision: int = 8) -> float:
    """Port of MATLAB ``centfrq`` -- the wavelet centre frequency.

    MATLAB estimates it from the location of the maximum of ``|FFT(psi)|``
    over the wavelet's effective support.
    """
    psi, x = wavefun_psi(wname, level=precision)
    domain = x[-1] - x[0]
    n = psi.size
    mag = np.abs(np.fft.fft(psi))
    mag[0] = 0.0                                # ignore the DC component
    half = mag[: n // 2]
    idx = int(np.argmax(half))
    return idx / domain


# db4 centre frequency, cached (matches MATLAB centfrq('db4') ~= 0.71428).
CENTFRQ_DB4 = centfrq("db4")


def scal2frq(scale, wname: str = "db4", delta: float = 1.0) -> float:
    """Port of MATLAB ``scal2frq(scale, wname, delta)``.

    ``frequency = centfrq(wname) / (scale * delta)``.
    """
    cf = CENTFRQ_DB4 if wname == "db4" else centfrq(wname)
    return cf / (np.asarray(scale, dtype=float) * delta)
