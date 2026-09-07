"""Python port of the MATLAB near-fault velocity-pulse classification code
(Shahi & Baker stratified wavelet algorithm)."""

from .analyze_record import analyze_record, PulseData
from .classification_algo import classification_algo, build_scales, AlgoResult
from .matlab_wavelets import matlab_cwt, centfrq, scal2frq
from .parse import parse_segment, parse_asc, Segment
from .preprocess import (
    RawRecord, read_record, read_at2, read_asc, read_plain, read_mseed,
    to_cm, detrend, cosine_taper, bandpass, to_velocity, resample_to,
    preprocess_component, write_vel_txt,
)

__all__ = [
    "analyze_record", "PulseData",
    "classification_algo", "build_scales", "AlgoResult",
    "matlab_cwt", "centfrq", "scal2frq",
    "parse_segment", "parse_asc", "Segment",
    "RawRecord", "read_record", "read_at2", "read_asc", "read_plain", "read_mseed",
    "to_cm", "detrend", "cosine_taper", "bandpass", "to_velocity", "resample_to",
    "preprocess_component", "write_vel_txt",
]
