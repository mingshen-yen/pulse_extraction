"""Shared comparison + plotting for the live-fetch validation drivers
(``validate_esm.py``, ``validate_geonet.py``).

A *record* is a dict produced by a driver's ``collect()``:

    sta dt npts dist_km vs30 qc is_pulse primary
    Tp PGV PGV_resid PI PC angle late any_pulse
    rotated pulse                       # velocity + extracted-pulse arrays
    sb_rrup sb_Tp sb_PGV                # None unless the station is in the ref table

``data`` is ``{event_label: [record, ...]}``; ``dirs`` maps each label to its
``output/<case>`` sub-directory; ``colors`` maps each label to a hex colour.
"""

from __future__ import annotations

import csv
import math
import statistics as st
from pathlib import Path

import numpy as np

_PULSE_COLS = ["station", "is_pulse", "primary", "Tp", "PGV", "PGV_resid",
               "pulse_indicator", "PC", "angle_deg", "late", "any_pulse",
               "dt", "npts", "dist_km", "vs30", "qc"]


def compute_stats(data):
    """is_pulse hit-rate + median/max |ΔTp|,|ΔPGV| over the reference stations."""
    rows = [r for ev in data for r in data[ev] if r["sb_Tp"] is not None]
    if not rows:
        return dict(n=0, is_pulse_hits=0, med_dTp=0.0, max_dTp=0.0,
                    med_dPGV=0.0, max_dPGV=0.0)
    dtp = [abs(r["Tp"] - r["sb_Tp"]) for r in rows]
    dpgv = [abs(r["PGV"] - r["sb_PGV"]) for r in rows]
    return dict(
        n=len(rows), is_pulse_hits=sum(int(r["is_pulse"]) for r in rows),
        med_dTp=st.median(dtp), max_dTp=max(dtp),
        med_dPGV=st.median(dpgv), max_dPGV=max(dpgv))


def write_tables(data, dirs, out, *, prefix, ref_label):
    """Write ``<case>/<prefix>_pulses.csv`` + ``<prefix>_vs_<ref>.csv`` per event
    and a combined ``<prefix>_vs_<ref>_all.csv``.  Prints a summary table and
    returns ``(combined_rows, stats)``."""
    ref_tag = "".join(c for c in ref_label if c.isalnum())
    combined = []
    for label, recs in data.items():
        odir = out / dirs[label]
        odir.mkdir(parents=True, exist_ok=True)
        with open(odir / f"{prefix}_pulses.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=_PULSE_COLS)
            w.writeheader()
            for r in recs:
                w.writerow({
                    "station": r["sta"], "is_pulse": int(r["is_pulse"]),
                    "primary": r["primary"], "Tp": round(r["Tp"], 3),
                    "PGV": round(r["PGV"], 2), "PGV_resid": round(r["PGV_resid"], 2),
                    "pulse_indicator": round(r["PI"], 3), "PC": round(r["PC"], 4),
                    "angle_deg": round(r["angle"], 2), "late": int(r["late"]),
                    "any_pulse": int(r["any_pulse"]), "dt": r["dt"],
                    "npts": r["npts"],
                    "dist_km": round(r["dist_km"], 1) if r["dist_km"] else "",
                    "vs30": r["vs30"] or "", "qc": r["qc"]})
        cmp_rows = []
        for r in recs:
            if r["sb_Tp"] is None:
                continue
            cmp_rows.append(dict(
                event=label, station=r["sta"], Rrup_km=r["sb_rrup"],
                Tp_ref=r["sb_Tp"], Tp_mine=round(r["Tp"], 3),
                dTp=round(r["Tp"] - r["sb_Tp"], 3),
                PGV_ref=r["sb_PGV"], PGV_mine=round(r["PGV"], 2),
                dPGV=round(r["PGV"] - r["sb_PGV"], 2),
                is_pulse_mine=int(r["is_pulse"]), PI=round(r["PI"], 3)))
        if cmp_rows:
            with open(odir / f"{prefix}_vs_{ref_tag}.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(cmp_rows[0]))
                w.writeheader()
                w.writerows(cmp_rows)
            combined += cmp_rows

    with open(out / f"{prefix}_vs_{ref_tag}_all.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(combined[0]))
        w.writeheader()
        w.writerows(combined)

    hdr = (f"{'event':<16}{'sta':<6}{'Rrup':>6}{'Tp_ref':>7}{'Tp_me':>7}{'dTp':>7}"
           f"{'PGV_ref':>8}{'PGV_me':>8}{'dPGV':>7}{'puls':>5}")
    print("\n" + hdr + "\n" + "-" * len(hdr))
    for r in combined:
        print(f"{r['event']:<16}{r['station']:<6}{r['Rrup_km']:>6}"
              f"{r['Tp_ref']:>7}{r['Tp_mine']:>7}{r['dTp']:>+7.3f}"
              f"{r['PGV_ref']:>8}{r['PGV_mine']:>8}{r['dPGV']:>+7.2f}"
              f"{r['is_pulse_mine']:>5}")

    n = len(combined)
    hits = sum(r["is_pulse_mine"] for r in combined)
    stats = dict(
        n=n, is_pulse_hits=hits,
        med_dTp=st.median(abs(r["dTp"]) for r in combined),
        max_dTp=max(abs(r["dTp"]) for r in combined),
        med_dPGV=st.median(abs(r["dPGV"]) for r in combined),
        max_dPGV=max(abs(r["dPGV"]) for r in combined))
    print(f"\nn = {n} {ref_label} pulse records, {len(data)} events")
    print(f"median |dTp|  = {stats['med_dTp']:.3f} s (max {stats['max_dTp']:.3f})")
    print(f"median |dPGV| = {stats['med_dPGV']:.2f} cm/s (max {stats['max_dPGV']:.2f})")
    print(f"is_pulse match: {hits}/{n}")
    return combined, stats


def plot_traces(data, colors, out, *, prefix, title, ref_short, xmax=None):
    """Grid of rotated velocity vs extracted pulse for every reference station,
    shared axes.  Auto grid shape and y-limit; ``xmax`` defaults to the longest
    record (rounded up to 10 s)."""
    import matplotlib.pyplot as plt

    panel = [(ev, r) for ev in data for r in data[ev] if r["sb_Tp"] is not None]
    if not panel:
        return
    ymax = math.ceil(max(np.max(np.abs(r["rotated"])) for _, r in panel) / 10) * 10
    if xmax is None:
        xmax = math.ceil(max(len(r["rotated"]) * r["dt"] for _, r in panel) / 10) * 10
    ncol = 4 if len(panel) > 9 else 3
    nrow = math.ceil(len(panel) / ncol)

    fig, axes = plt.subplots(nrow, ncol, figsize=(3.6 * ncol, 2.9 * nrow),
                             sharex=True, sharey=True, squeeze=False)
    for ax in axes.flat:
        ax.axis("off")
    for ax, (ev, r) in zip(axes.flat, panel):
        ax.axis("on")
        dt = r["dt"]
        rot, pul = np.asarray(r["rotated"]), np.asarray(r["pulse"])
        ax.plot(np.arange(len(rot)) * dt, rot, lw=0.8, color="0.55",
                label="rotated velocity")
        ax.plot(np.arange(len(pul)) * dt, pul, lw=2.0, color=colors[ev],
                label="extracted pulse")
        ax.set_title(f"{ev} — {r['sta']}", fontsize=10.5, fontweight="bold")
        ax.text(0.98, 0.03,
                f"Tp {r['Tp']:.2f} s  ({ref_short} {r['sb_Tp']:.2f})\n"
                f"PGV {r['PGV']:.1f} cm/s  ({ref_short} {r['sb_PGV']:.1f})\n"
                f"θ {r['angle']:+.0f}°   PI {r['PI']:.1f}",
                transform=ax.transAxes, fontsize=8, va="bottom", ha="right",
                bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=0.9))
        ax.set_xlabel("time [s]", fontsize=9)
        ax.set_ylabel("velocity [cm/s]", fontsize=9)
        ax.tick_params(labelsize=8, labelbottom=True, labelleft=True)
        ax.set_xlim(0, xmax)
        ax.set_ylim(-ymax, ymax)
    axes.flat[0].legend(fontsize=8, loc="upper right", framealpha=0.9)
    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.30 / nrow))
    fig.savefig(out / f"{prefix}_traces.png", dpi=130)
    print("wrote", out / f"{prefix}_traces.png")


def plot_scaling(data, colors, out, *, prefix, title, ref_label, stats):
    """Tp vs Rrup and PGV vs Rrup: pipeline value (filled dot) framed by the
    reference value (open square), one colour per event."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    pts = [(ev, r) for ev in data for r in data[ev] if r["sb_rrup"] is not None]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.6))
    for ev, r in pts:
        c = colors[ev]
        x = r["sb_rrup"]
        a1.plot([x, x], [r["Tp"], r["sb_Tp"]], color=c, lw=1.2, zorder=1)
        a2.plot([x, x], [r["PGV"], r["sb_PGV"]], color=c, lw=1.2, zorder=1)
        a1.plot(x, r["sb_Tp"], "s", ms=14, mfc="none", mec="k", mew=1.3, zorder=3)
        a2.plot(x, r["sb_PGV"], "s", ms=14, mfc="none", mec="k", mew=1.3, zorder=3)
        a1.plot(x, r["Tp"], "o", ms=7, mfc=c, mec="k", mew=.5, zorder=4)
        a2.plot(x, r["PGV"], "o", ms=7, mfc=c, mec="k", mew=.5, zorder=4)
        for ax, y in ((a1, r["Tp"]), (a2, r["PGV"])):
            ax.annotate(r["sta"], (x, y), fontsize=7.5, color=c,
                        xytext=(6, -2), textcoords="offset points")
    a1.text(0.03, 0.04,
            f"median |ΔT$_p$| = {stats['med_dTp']:.02f} s   "
            f"(is_pulse {stats['is_pulse_hits']}/{stats['n']})",
            transform=a1.transAxes, fontsize=8.5, style="italic",
            bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=.9))
    a2.text(0.03, 0.04,
            f"median |ΔPGV| = {stats['med_dPGV']:.02f} cm/s   "
            f"(is_pulse {stats['is_pulse_hits']}/{stats['n']})",
            transform=a2.transAxes, fontsize=8.5, style="italic",
            bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=.9))
    for ax in (a1, a2):
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel(f"R$_{{rup}}$ [km]  ({ref_label})", fontsize=9.5)
        ax.grid(True, which="both", alpha=0.25)
    a1.set_ylabel("pulse period  T$_p$  [s]")
    a2.set_ylabel("pulse  PGV  [cm/s]")
    a1.set_title("T$_p$ vs R$_{rup}$", fontweight="bold")
    a2.set_title("PGV vs R$_{rup}$", fontweight="bold")
    leg = [Line2D([], [], marker="o", ls="none", mfc=colors[e], mec="k", ms=9,
                  label=e) for e in colors if any(ev == e for ev, _ in pts)]
    leg.append(Line2D([], [], marker="s", ls="none", mfc="none", mec="k", ms=10,
                      label=ref_label))
    a1.legend(handles=leg, fontsize=8.5, loc="upper left", framealpha=.92)
    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out / f"{prefix}_Tp_PGV_Rrup.png", dpi=140)
    print("wrote", out / f"{prefix}_Tp_PGV_Rrup.png")
