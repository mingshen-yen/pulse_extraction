"""Input parsers.

``parse_segment`` mirrors the original ``parse_segment.m`` (a bare single-column
text file, ``dt`` hard-coded to 0.01 s).  ``parse_asc`` is a convenience reader
for ORFEUS/ESM ``.ASC`` strong-motion files, used to regenerate the
``*_VEL_N.txt`` / ``*_VEL_E.txt`` inputs that the MATLAB driver expected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["Segment", "parse_segment", "parse_asc"]

DEFAULT_DT = 0.01  # parse_segment.m hard-codes this


@dataclass
class Segment:
    vel: np.ndarray          # velocity samples
    dt: float                # sampling interval [s]
    npts: int                # number of samples
    err_code: int            # 0 = ok, -1 = file not found (matches MATLAB)


def parse_segment(path, dt: float = DEFAULT_DT) -> Segment:
    """Port of ``parse_segment.m``.

    Reads whitespace-separated floats from *path*.  The original always returns
    ``dt = 0.01``; expose it as an argument so callers can override when the true
    sampling rate is known.
    """
    p = Path(path)
    if not p.is_file():
        return Segment(vel=np.array([-1.0]), dt=dt, npts=-1, err_code=-1)
    vel = np.fromstring(" ".join(p.read_text().split()), sep=" ")
    return Segment(vel=vel, dt=dt, npts=vel.size, err_code=0)


def parse_asc(path):
    """Read an ESM/ORFEUS ``.ASC`` file.

    Returns ``(data, header)`` where ``header`` is a ``dict`` of the ``KEY: value``
    lines and ``data`` is a float ``ndarray``.  ``header['dt']`` and
    ``header['npts']`` are provided for convenience.
    """
    lines = Path(path).read_text().splitlines()
    header: dict[str, str] = {}
    data_start = 0
    for i, line in enumerate(lines):
        if ":" in line and not line.lstrip()[:1].isdigit():
            key, _, val = line.partition(":")
            header[key.strip()] = val.strip()
        else:
            stripped = line.strip()
            if stripped and (stripped[0].isdigit() or stripped[0] in "+-."):
                data_start = i
                break
    data = np.array([float(x) for x in lines[data_start:] if x.strip()])
    if "SAMPLING_INTERVAL_S" in header:
        header["dt"] = float(header["SAMPLING_INTERVAL_S"])
    if "NDATA" in header:
        header["npts"] = int(header["NDATA"])
    return data, header
