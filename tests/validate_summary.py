"""Combine every live-fetch validation case into one summary + figure.

Reads the caches written by ``validate_esm.py`` and ``validate_geonet.py``
(``output/esm_cache.pkl``, ``output/geonet_cache.pkl`` -- run those first) and
produces, over every Shahi & Baker (2014) pulse record fetched:

    output/validation_summary.csv       one row per record, all 5 events
    output/validation_summary.png       Tp & PGV 1:1  +  Tp & PGV vs Rrup

    python tests/validate_summary.py
"""

from __future__ import annotations

import csv
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests._pulse_validation import compute_stats                 # noqa: E402

OUT = ROOT / "output"
CACHES = ["esm_cache.pkl", "geonet_cache.pkl"]

COLORS = {
    "2009 L'Aquila": "#1f77b4", "1980 Irpinia": "#4c9be8",
    "1979 Montenegro": "#7fc7ff", "2010 Darfield": "#d62728",
    "2011 Christchurch": "#ff9896",
}
SOURCE = {"2009 L'Aquila": "ESM", "1980 Irpinia": "ESM", "1979 Montenegro": "ESM",
          "2010 Darfield": "GeoNet", "2011 Christchurch": "GeoNet"}


def load():
    data = {}
    for name in CACHES:
        p = OUT / name
        if not p.exists():
            sys.exit(f"missing {p} — run the matching validate_*.py first")
        for ev, recs in pickle.loads(p.read_bytes()).items():
            data[ev] = recs
    return data


def summarise(data):
    rows = []
    for ev, recs in data.items():
        for r in recs:
            if r["sb_Tp"] is None:
                continue
            rows.append(dict(
                source=SOURCE[ev], event=ev, station=r["sta"],
                Rrup_km=r["sb_rrup"], qc=r["qc"],
                Tp_ref=r["sb_Tp"], Tp=round(r["Tp"], 3),
                dTp=round(r["Tp"] - r["sb_Tp"], 3),
                PGV_ref=r["sb_PGV"], PGV=round(r["PGV"], 2),
                dPGV=round(r["PGV"] - r["sb_PGV"], 2),
                dPGV_pct=round(100 * (r["PGV"] - r["sb_PGV"]) / r["sb_PGV"], 1),
                is_pulse=int(r["is_pulse"]), PI=round(r["PI"], 2)))
    rows.sort(key=lambda x: (x["event"], x["Rrup_km"]))
    with open(OUT / "validation_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    hdr = (f"{'source':<7}{'event':<16}{'sta':<6}{'Rrup':>6}{'Tp_ref':>7}"
           f"{'Tp':>7}{'dTp':>7}{'PGVr':>7}{'PGV':>7}{'dPGV%':>7}{'puls':>5}")
    print(hdr + "\n" + "-" * len(hdr))
    for r in rows:
        print(f"{r['source']:<7}{r['event']:<16}{r['station']:<6}{r['Rrup_km']:>6}"
              f"{r['Tp_ref']:>7}{r['Tp']:>7}{r['dTp']:>+7.2f}"
              f"{r['PGV_ref']:>7}{r['PGV']:>7}{r['dPGV_pct']:>+7.1f}{r['is_pulse']:>5}")

    print()
    for ev in list(data) + ["ALL"]:
        sub = {ev: data[ev]} if ev != "ALL" else data
        s = compute_stats(sub)
        if s["n"] == 0:
            continue
        print(f"{ev:<18} n={s['n']:<3} is_pulse {s['is_pulse_hits']}/{s['n']}  "
              f"med|dTp| {s['med_dTp']:.3f}s (max {s['max_dTp']:.2f})  "
              f"med|dPGV| {s['med_dPGV']:.2f} (max {s['max_dPGV']:.1f}) cm/s")
    return rows


def plot(data, rows):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig, ax = plt.subplots(2, 2, figsize=(13, 11))
    (a_tp, a_pgv), (a_tpr, a_pgvr) = ax

    def mk(ev, r):
        return dict(mfc=COLORS[ev] if r["is_pulse"] else "none",
                    mec=COLORS[ev], marker="o", ms=8, mew=1.4, ls="none")

    recs = [(ev, r) for ev in data for r in data[ev] if r["sb_Tp"] is not None]

    # --- 1:1 panels -------------------------------------------------------
    for ev, r in recs:
        a_tp.plot(r["sb_Tp"], r["Tp"], **mk(ev, r))
        a_pgv.plot(r["sb_PGV"], r["PGV"], **mk(ev, r))
    for a, lo, hi, lab in ((a_tp, 0.8, 15, "pulse period  T$_p$  [s]"),
                           (a_pgv, 20, 160, "pulse  PGV  [cm/s]")):
        a.plot([lo, hi], [lo, hi], "k-", lw=1, zorder=0)
        a.plot([lo, hi], [1.1 * lo, 1.1 * hi], "k--", lw=.6, alpha=.5, zorder=0)
        a.plot([lo, hi], [0.9 * lo, 0.9 * hi], "k--", lw=.6, alpha=.5, zorder=0)
        a.set_xscale("log"); a.set_yscale("log")
        a.set_xlim(lo, hi); a.set_ylim(lo, hi)
        a.set_xlabel(f"Shahi & Baker (2014)   {lab}")
        a.set_ylabel(f"this pipeline   {lab}")
        a.grid(True, which="both", alpha=.25)
    a_tp.set_title("T$_p$  —  pipeline vs reference (±10 % dashed)", fontweight="bold")
    a_pgv.set_title("PGV  —  pipeline vs reference (±10 % dashed)", fontweight="bold")

    # --- vs Rrup --------------------------------------------------------
    for ev, r in recs:
        x = r["sb_rrup"]
        a_tpr.plot([x, x], [r["Tp"], r["sb_Tp"]], color=COLORS[ev], lw=1, zorder=1)
        a_pgvr.plot([x, x], [r["PGV"], r["sb_PGV"]], color=COLORS[ev], lw=1, zorder=1)
        a_tpr.plot(x, r["sb_Tp"], "s", ms=13, mfc="none", mec="k", mew=1.2, zorder=3)
        a_pgvr.plot(x, r["sb_PGV"], "s", ms=13, mfc="none", mec="k", mew=1.2, zorder=3)
        a_tpr.plot(x, r["Tp"], **mk(ev, r))
        a_pgvr.plot(x, r["PGV"], **mk(ev, r))
    for a, lab in ((a_tpr, "pulse period  T$_p$  [s]"), (a_pgvr, "pulse  PGV  [cm/s]")):
        a.set_xscale("log"); a.set_yscale("log")
        a.set_xlabel("R$_{rup}$ [km]  (Shahi & Baker 2014)")
        a.set_ylabel(lab)
        a.grid(True, which="both", alpha=.25)
    a_tpr.set_title("T$_p$ vs R$_{rup}$", fontweight="bold")
    a_pgvr.set_title("PGV vs R$_{rup}$   (□ = reference)", fontweight="bold")

    s = compute_stats(data)
    leg = [Line2D([], [], marker="o", ls="none", mfc=COLORS[e], mec=COLORS[e],
                  label=f"{e}  ({SOURCE[e]})") for e in COLORS]
    leg += [Line2D([], [], marker="o", ls="none", mfc="none", mec="0.4",
                   label="open = is_pulse = 0")]
    a_tp.legend(handles=leg, fontsize=8.5, loc="upper left", framealpha=.92)
    fig.suptitle(
        f"Live-fetch validation vs Shahi & Baker (2014) — {s['n']} pulse records, "
        f"5 events (1979–2011)\n"
        f"is_pulse {s['is_pulse_hits']}/{s['n']}   ·   "
        f"median |ΔT$_p$| {s['med_dTp']:.3f} s   ·   "
        f"median |ΔPGV| {s['med_dPGV']:.2f} cm/s",
        fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT / "validation_summary.png", dpi=140)
    print("\nwrote", OUT / "validation_summary.png")
    print("wrote", OUT / "validation_summary.csv")


def main():
    data = load()
    rows = summarise(data)
    plot(data, rows)


if __name__ == "__main__":
    main()
