"""Port of ``classify_record_main.m`` -- batch driver.

Usage
-----
    python -m pulse_classification.main \
        --data DATA/2023_Turkey/..._TXT \
        --stations stations_pulse.txt \
        --figures Results/2023_Turkey/Figures \
        --out Results/2023_Turkey \
        [--dt 0.01]

For every station ``S`` in the station list it expects ``S_VEL_N.txt`` and
``S_VEL_E.txt`` (single-column velocity in cm/s), runs the classification, writes
``S_j_rotated.txt`` / ``S_j_pulseth.txt`` and a figure for every pulse-like
component, and finally a combined ``pulseData.csv``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .classification_algo import classification_algo, N_PULSES
from .parse import parse_segment
from .plotting import make_plot

# NOTE: the original writetable() call in classify_record_main.m pairs these
# header names with shifted columns (e.g. 'Ipulse' actually held the indicator,
# 'late' held PC).  The port uses correct, self-consistent names.
CSV_COLUMNS = ["sta_ID", "max_Dir", "Tp", "PGV", "pulse_indicator", "PC",
               "is_pulse", "late"]
MISSING = -999


def classify_station(sta, path_data, path_out, path_fig, dt=None, verbose=True):
    """Returns a list of ``N_PULSES`` row dicts for one station."""
    file_n = Path(path_data) / f"{sta}_VEL_N.txt"
    file_e = Path(path_data) / f"{sta}_VEL_E.txt"

    seg_n = parse_segment(file_n) if dt is None else parse_segment(file_n, dt)
    seg_e = parse_segment(file_e) if dt is None else parse_segment(file_e, dt)

    if seg_n.err_code == -1 or seg_e.err_code == -1:
        raise FileNotFoundError(f"missing component file for station {sta}")
    if abs(seg_n.npts - seg_e.npts) > 20:
        raise ValueError(f"{sta}: NPTS mismatch ({seg_n.npts} vs {seg_e.npts})")
    if seg_n.dt != seg_e.dt:
        raise ValueError(f"{sta}: dt mismatch ({seg_n.dt} vs {seg_e.dt})")

    n = min(seg_n.npts, seg_e.npts)
    s1, s2, rec_dt = seg_n.vel[:n], seg_e.vel[:n], seg_n.dt

    res = classification_algo(s1, s2, rec_dt, verbose=verbose)

    rows = []
    for j, pdata in enumerate(res.pulse_datas, start=1):
        sta_id = f"{sta}_{j}"
        if pdata.is_pulse:
            rows.append(dict(sta_ID=sta_id, max_Dir=pdata.angles, Tp=pdata.Tp,
                             PGV=pdata.PGV, pulse_indicator=pdata.pulse_indicator,
                             PC=pdata.PC, is_pulse=int(pdata.is_pulse),
                             late=int(pdata.late)))
            np.savetxt(Path(path_out) / f"{sta}_{j}_rotated.txt", pdata.signal, fmt="%f")
            np.savetxt(Path(path_out) / f"{sta}_{j}_pulseth.txt", pdata.pulse_th, fmt="%f")
            make_plot(j, pdata.signal, pdata.pulse_th, pdata.resid_th, rec_dt, sta, path_fig)
        else:
            rows.append(dict(sta_ID=sta_id, max_Dir=MISSING, Tp=MISSING,
                             PGV=MISSING, pulse_indicator=pdata.pulse_indicator,
                             PC=MISSING, is_pulse=int(pdata.is_pulse),
                             late=int(pdata.late)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--stations", required=True,
                    help="station-list file (relative to --data unless absolute)")
    ap.add_argument("--figures", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dt", type=float, default=None,
                    help="override sampling interval (default: parse_segment's 0.01)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only process the first N stations (MATLAB used 2)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    data_dir = Path(args.data)
    fig_dir = Path(args.figures)
    out_dir = Path(args.out)
    fig_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    stations_path = Path(args.stations)
    if not stations_path.is_absolute() and not stations_path.exists():
        stations_path = data_dir / args.stations
    stations = stations_path.read_text().split()
    if args.limit is not None:
        stations = stations[: args.limit]

    all_rows = []
    for sta in stations:
        print(sta)
        try:
            all_rows.extend(classify_station(sta, data_dir, out_dir, fig_dir,
                                             dt=args.dt, verbose=not args.quiet))
        except (FileNotFoundError, ValueError) as exc:
            print(f"  skipped: {exc}")
            for j in range(1, N_PULSES + 1):
                all_rows.append(dict(sta_ID=f"{sta}_{j}", max_Dir=MISSING,
                                     Tp=MISSING, PGV=MISSING,
                                     pulse_indicator=MISSING, PC=MISSING,
                                     is_pulse=MISSING, late=MISSING))

    df = pd.DataFrame(all_rows, columns=CSV_COLUMNS)
    df.to_csv(out_dir / "pulseData.csv", index=False)
    print(f"\nwrote {out_dir / 'pulseData.csv'}  ({len(df)} rows)")


if __name__ == "__main__":
    main()
