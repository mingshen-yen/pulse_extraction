"""eBASCO automatic baseline correction -- driver around :mod:`waveform._ebasco`.

Faithful transcription of the driver loop in
``00_BASC_Fling_rm/BASC/eBASCO_FRM.ipynb`` (cell 1): sample T1/T3 from the Arias
intensity, sweep T1 x T3 x T2, trilinearly detrend the velocity in the
pre / strong / post-event windows, differentiate back to acceleration, keep the
solutions whose corrected acceleration stays within ``eps`` of the raw trace at
T1 and T2, and pick the flattest displacement tail per component.

Preserves the permanent (fling) displacement -- unlike the Kamai polynomial
path in :mod:`waveform.basc`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import _ebasco as E


@dataclass
class EbascoComponent:
    acc: np.ndarray            # corrected acceleration (filtered, tapered)
    vel: np.ndarray            # corrected velocity  [input units x s]
    disp: np.ndarray           # corrected displacement (keeps static offset)
    t1: float
    t2: float
    t3: float
    f_value: float
    permanent_disp: float
    ok: bool


@dataclass
class EbascoResult:
    e: EbascoComponent
    n: EbascoComponent
    z: EbascoComponent
    dt: float


def _stream(arr, dt):
    from obspy import Stream, Trace
    return Stream([Trace(data=np.asarray(arr, dtype=float),
                         header={"delta": float(dt)})])


def _fail(reason: str):
    empty = np.array([])
    return EbascoComponent(empty, empty, empty, np.nan, np.nan, np.nan,
                           np.nan, np.nan, ok=False), reason


def _arias_cut(st, dt, mfst, mfnd, p_start=0.05, p_end=0.95):
    """Trim a Stream to ``[t(p_start) - mfst*D, t(p_end) + mfnd*D]`` where ``D``
    is the p_start-p_end Arias duration, padding with the first sample.

    Port of ``cut_wf_ARIAS`` in the reference eBASCO.py (default mfst=1.5,
    mfnd=2.0).  Returns a new Stream.
    """
    s = st.copy()
    i0, i1, dur = E.wf_Partition(s[0].data, dt, p_start, p_end)
    t0 = s[0].stats.starttime
    s.trim(starttime=t0 + i0 - mfst * dur,
           endtime=t0 + i1 + mfnd * dur,
           pad=True, fill_value=float(s[0].data[0]))
    return s


def ebasco_correct(acc_e, acc_n, acc_z, dt, *,
                   n_t1: int = 5, n_t2: int = 20, n_t3: int = 20,
                   eps: float = 0.25,
                   arias_cut: bool = True, mfst: float = 1.5, mfnd: float = 2.0,
                   t1_count: str = "t3",
                   final_corners: int = 2, final_lowpass_hz: float = 35.0,
                   taper_pct: float = 5.0):
    """Run eBASCO on three acceleration components (equal ``dt``).

    ``arias_cut``  -- trim each component to the strong-motion window first
    (``cut_wf_ARIAS`` in the reference eBASCO.py; default on, matching it).
    ``t1_count``   -- ``"t3"`` samples T1 with ``n_t3`` points (what the
    reference eBASCO.py actually does), ``"t1"`` uses ``n_t1``.

    Returns an :class:`EbascoResult`.  A component with no acceptable solution
    comes back with ``ok=False`` and empty arrays.
    """
    acc_e = np.asarray(acc_e, dtype=float).ravel()
    acc_n = np.asarray(acc_n, dtype=float).ravel()
    acc_z = np.asarray(acc_z, dtype=float).ravel()
    m = min(acc_e.size, acc_n.size, acc_z.size)
    acc_e, acc_n, acc_z = acc_e[:m], acc_n[:m], acc_z[:m]
    dt_e = dt_n = dt_z = float(dt)

    st_e, st_n, st_z = _stream(acc_e, dt), _stream(acc_n, dt), _stream(acc_z, dt)

    if arias_cut:
        st_e = _arias_cut(st_e, dt_e, mfst, mfnd)
        st_n = _arias_cut(st_n, dt_n, mfst, mfnd)
        st_z = _arias_cut(st_z, dt_z, mfst, mfnd)
        n = min(len(st_e[0].data), len(st_n[0].data), len(st_z[0].data))
        for s in (st_e, st_n, st_z):
            s[0].data = np.asarray(s[0].data[:n], dtype=float)

    WF_CUT = E.ACCtoDISP(st_e, st_n, st_z, dt_e, dt_n, dt_z)
    #  WF_CUT = [ [ACC_E,ACC_N,ACC_Z], [VEL...], [DIS...], [TIME...] ]

    n_t1_eff = n_t3 if t1_count == "t3" else n_t1
    T1_SAMPLES = E.sample_T1(WF_CUT[0][0], WF_CUT[0][1], WF_CUT[0][2],
                             dt_e, dt_n, dt_z, n_t1_eff)
    PRE_EVE_TIME, PRE_EVE_VEL = E.pre_eve(WF_CUT[1][0], WF_CUT[1][1], WF_CUT[1][2],
                                          dt_e, dt_n, dt_z, T1_SAMPLES)
    PRE_EVE_VEL_DET, LAST_VALUE_LIN_FIT, _LIN_FIT = E.pre_eve_detrend(
        PRE_EVE_TIME, PRE_EVE_VEL)
    T3_SAMPLES = E.sample_T3(WF_CUT[0][0], WF_CUT[0][1], WF_CUT[0][2],
                             dt_e, dt_n, dt_z, n_t3)
    END_POINTS = E.end_point(WF_CUT[0][0], WF_CUT[0][1], WF_CUT[0][2],
                             dt_e, dt_n, dt_z)

    T1_E, T2_E, T3_E, TIME_E, VEL_CORR_E = [], [], [], [], []
    T1_N, T2_N, T3_N, TIME_N, VEL_CORR_N = [], [], [], [], []
    T1_Z, T2_Z, T3_Z, TIME_Z, VEL_CORR_Z = [], [], [], [], []

    half = lambda a: int(len(a) / 2)
    for i1 in np.arange(len(T1_SAMPLES[0]) - half(T1_SAMPLES[0])):
        for i3 in np.arange(len(T3_SAMPLES[0]) - half(T3_SAMPLES[0])):
            T2_SAMPLES = E.sample_T2(T3_SAMPLES, END_POINTS, i3, n_t2)
            for i2 in np.arange(len(T2_SAMPLES[0]) - half(T2_SAMPLES[0])):
                POST_EVE_TIME, POST_EVE_VEL = E.post_eve(
                    WF_CUT[1][0], WF_CUT[1][1], WF_CUT[1][2],
                    dt_e, dt_n, dt_z, T2_SAMPLES, END_POINTS, i2)
                POST_EVE_VEL_DET, POST_EVE_LIN_FIT = E.post_eve_detrend(
                    POST_EVE_TIME, POST_EVE_VEL)
                STRONG_TIME, STRONG_VEL = E.strong_eve(
                    WF_CUT[1][0], WF_CUT[1][1], WF_CUT[1][2],
                    dt_e, dt_n, dt_z, T1_SAMPLES, T2_SAMPLES, i1, i2)

                def _line(k, T2s, T1s):
                    Am = float((POST_EVE_LIN_FIT[k][0] - LAST_VALUE_LIN_FIT[k][i1])
                               / (T2s[k][i2] - T1s[k][i1]))
                    q = LAST_VALUE_LIN_FIT[k][i1] - Am * T1s[k][i1]
                    return Am, q

                Am_E, q_E = _line(0, T2_SAMPLES, T1_SAMPLES)
                Am_N, q_N = _line(1, T2_SAMPLES, T1_SAMPLES)
                Am_Z, q_Z = _line(2, T2_SAMPLES, T1_SAMPLES)

                STRONG_LINE = [E.retta(STRONG_TIME[0], Am_E, q_E),
                               E.retta(STRONG_TIME[1], Am_N, q_N),
                               E.retta(STRONG_TIME[2], Am_Z, q_Z)]
                STRONG_VEL_DET = E.strong_eve_detrend(STRONG_TIME, STRONG_VEL,
                                                      STRONG_LINE)

                for (TIME, VEL_CORR, T1L, T2L, T3L, k) in (
                    (TIME_E, VEL_CORR_E, T1_E, T2_E, T3_E, 0),
                    (TIME_N, VEL_CORR_N, T1_N, T2_N, T3_N, 1),
                    (TIME_Z, VEL_CORR_Z, T1_Z, T2_Z, T3_Z, 2),
                ):
                    TIME.append(np.concatenate((PRE_EVE_TIME[k][i1],
                                                STRONG_TIME[k],
                                                POST_EVE_TIME[k][1:]), axis=0))
                    VEL_CORR.append(np.concatenate((PRE_EVE_VEL_DET[k][i1],
                                                    STRONG_VEL_DET[k],
                                                    POST_EVE_VEL_DET[k][1:]), axis=0))
                    T1L.append(T1_SAMPLES[k][i1])
                    T2L.append(T2_SAMPLES[k][i2])
                    T3L.append(T3_SAMPLES[k][i3])

    def _finish(VEL_CORR, T1L, T2L, T3L, raw_acc, dt_k, label):
        if not VEL_CORR:
            return _fail(f"{label}: no candidate solutions")[0]
        acc_corr = [np.gradient(v, dt_k) for v in VEL_CORR]
        good, _bad, t3_good, _idx = E.acc_corr(raw_acc, acc_corr, dt_k,
                                               T1L, T2L, T3L, eps)
        if len(good) == 0:
            return _fail(f"{label}: no solution within eps={eps}")[0]
        t_good, _v_good, d_good = E.accept_solution(good, dt_k, label)
        fvals = E.fvalue(t_good, d_good, t3_good)
        best = int(np.argmax(fvals))
        acc_f, vel_f, dis_f = E.final_trace(good, best, taper_pct, dt_k,
                                            final_corners, final_lowpass_hz)
        return EbascoComponent(
            acc=np.asarray(acc_f), vel=np.asarray(vel_f), disp=np.asarray(dis_f),
            t1=float(T1L[best]), t2=float(T2L[best]), t3=float(t3_good[best]),
            f_value=float(fvals[best]), permanent_disp=float(dis_f[-1]), ok=True)

    return EbascoResult(
        e=_finish(VEL_CORR_E, T1_E, T2_E, T3_E, WF_CUT[0][0], dt_e, "EW"),
        n=_finish(VEL_CORR_N, T1_N, T2_N, T3_N, WF_CUT[0][1], dt_n, "NS"),
        z=_finish(VEL_CORR_Z, T1_Z, T2_Z, T3_Z, WF_CUT[0][2], dt_z, "UD"),
        dt=float(dt),
    )
