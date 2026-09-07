"""End-to-end check of the Python port against the MATLAB reference outputs
shipped in ``classification_matlab/Results/2023_Turkey/``.

The raw ``*_VEL_N.txt`` inputs the MATLAB driver consumed are no longer in the
repo, so we regenerate them from the ESM ``.ASC`` files (data column only) and
feed them with ``dt = 0.01`` -- exactly what ``parse_segment.m`` did.

Offline record only: this script needs the original MATLAB tree
(``classification_matlab/DATA`` and ``classification_matlab/Results``) sitting
two levels above this package.  It is kept here to document the numeric
agreement, not to run as part of this stand-alone repo -- see the table in
``README.md``.  ``tests/test_matlab_wavelets.py`` runs anywhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulse_classification.classification_algo import classification_algo
from pulse_classification.parse import parse_asc

REPO = Path(__file__).resolve().parents[2]
MAT = REPO / "classification_matlab"
ASC_DIR = MAT / "DATA/2023_Turkey/ESM_TurkeyEQ_02060117_rmdisp"
REF_DIR = MAT / "Results/2023_Turkey"
EVENT = "INT-20230206_0000008"
DT = 0.01

# sta -> {pulse_j: (max_Dir, Tp, PGV, pulse_indicator, PC, is_pulse, late)}
# Values read from classification_matlab/Results/2023_Turkey/pulseData.csv, whose
# writetable() header is mislabelled: the real column order is
#   sta_ID, angles, Tp, PGV, pulse_indicator, PC, is_pulse, late
REF_CSV = {
    ("3123", 1): (17.0939466067761, 5.138, 180.179347914548, 19.6730778211653, 0.687882260249135, 1, 0),
    ("3123", 2): (18.8898218238723, 4.774, 178.365456220291, 15.1578976049765, 0.731624496864443, 1, 0),
    ("2712", 1): (-31.4436012770364, 14.182, 127.465794172729, 7.33996234749528, 0.793796307220867, 1, 0),
    ("2712", 2): (-27.3233422185786, 15.624, 123.583501718129, 0.786086503280799, 0.883491674227415, 1, 0),
}


def load_component(sta, comp):
    f = ASC_DIR / f"TK.{sta}..HN{comp}.D.{EVENT}.VEL.MP.ASC"
    data, _ = parse_asc(f)
    return data


def check_station(sta):
    print(f"\n=== station {sta} ===")
    s_n = load_component(sta, "N")
    s_e = load_component(sta, "E")
    n = min(s_n.size, s_e.size)
    res = classification_algo(s_n[:n], s_e[:n], DT, verbose=False)

    ok = True
    for j, pdata in enumerate(res.pulse_datas, start=1):
        key = (sta, j)
        if key not in REF_CSV:
            continue
        ref = REF_CSV[key]
        got = (pdata.angles, pdata.Tp, pdata.PGV, pdata.pulse_indicator,
               pdata.PC, int(pdata.is_pulse), int(pdata.late))
        names = ["max_Dir", "Tp", "PGV", "pulse_indicator", "PC", "is_pulse", "late"]
        print(f"  pulse {j}")
        # pulse_indicator is a stiff polynomial of standardized PC/PGV, so a
        # sub-percent PC difference shows up as ~0.1 here -> allow an abs tol.
        abstol = {"pulse_indicator": 0.15, "PC": 5e-3}
        for name, g, r in zip(names, got, ref):
            rel = abs(g - r) / (abs(r) + 1e-12)
            passed = (rel < 5e-3
                      or abs(g - r) < abstol.get(name, 0.0)
                      or (name in ("is_pulse", "late") and g == r))
            flag = "OK " if passed else "XX "
            if not passed:
                ok = False
            print(f"    {flag}{name:16s} port={g:>18.8g}  matlab={r:>18.8g}  rel={rel:.2e}")

        # waveform comparison against the *_rotated.txt / *_pulseth.txt references
        for tag, arr in (("rotated", pdata.signal), ("pulseth", pdata.pulse_th)):
            ref_f = REF_DIR / f"{sta}_{j}_{tag}.txt"
            if ref_f.exists():
                ref_arr = np.loadtxt(ref_f)
                m = min(len(ref_arr), len(arr))
                num = np.linalg.norm(arr[:m] - ref_arr[:m])
                den = np.linalg.norm(ref_arr[:m]) + 1e-12
                print(f"    ~~ {tag:8s} rel L2 diff = {num / den:.3e}  (n={m})")
    return ok


if __name__ == "__main__":
    all_ok = True
    for sta in ("3123", "2712"):
        all_ok &= check_station(sta)
    print("\nRESULT:", "PASS" if all_ok else "MISMATCH (see XX rows)")
    sys.exit(0 if all_ok else 1)
