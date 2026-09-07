"""Python port of the MATLAB near-fault velocity-pulse classification code
(Shahi & Baker stratified wavelet algorithm)."""

from .analyze_record import analyze_record, PulseData
from .classification_algo import classification_algo, build_scales, AlgoResult
from .matlab_wavelets import matlab_cwt, centfrq, scal2frq
from .parse import parse_segment, parse_asc, Segment

__all__ = [
    "analyze_record", "PulseData",
    "classification_algo", "build_scales", "AlgoResult",
    "matlab_cwt", "centfrq", "scal2frq",
    "parse_segment", "parse_asc", "Segment",
]
