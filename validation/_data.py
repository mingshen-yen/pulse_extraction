"""Shared data-location resolution for the validation scripts.

Records go in ``data/records/2023_turkey/`` and the reference table in
``data/reference/ES_published_pulse_table.csv`` (both git-ignored -- see
``data/README.md``).  The old absolute dev paths are kept as a fallback.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVID = "INT-20230206_0000008"

_RECORD_CANDIDATES = (
    REPO / "data" / "records" / "2023_turkey",
    Path("/Volumes/WD/work/pulse/00_BASC_Fling_rm/BASC/TK_unprocess"),
)
_ES_CANDIDATES = (
    REPO / "data" / "reference" / "ES_published_pulse_table.csv",
    Path("/Volumes/WD/work/pulse/01_pulse_classification/PulseClassification-master"
         "/2023_turkey/ES_published_pulse_table.csv"),
)


def records_dir(cli: str | Path | None = None) -> Path:
    for c in ([Path(cli)] if cli else []) + list(_RECORD_CANDIDATES):
        if c.is_dir():
            return c
    raise SystemExit(
        "no record directory found. Put 3-component mseed in "
        "data/records/2023_turkey/ (see data/README.md) or pass --mseed DIR.")


def es_csv(cli: str | Path | None = None) -> Path:
    for c in ([Path(cli)] if cli else []) + list(_ES_CANDIDATES):
        if c.is_file():
            return c
    raise SystemExit(
        "ES_published_pulse_table.csv not found. Put it in data/reference/ "
        "(see data/README.md) or pass --es CSV.")


def net_for(sta: str) -> str:
    return "KO" if sta == "KHMN" else "TK"


def read_three(sta: str, mseed_dir: Path):
    """Return (acc_e, acc_n, acc_z, dt) in the file's units (cm/s**2)."""
    import obspy
    base = str(Path(mseed_dir) / f"{net_for(sta)}.{sta}..HN{{}}.{EVID}.ACC.CV.mseed")
    tr = [obspy.read(base.format(c))[0] for c in "ENZ"]
    return (tr[0].data.astype(float), tr[1].data.astype(float),
            tr[2].data.astype(float), float(tr[0].stats.delta))
