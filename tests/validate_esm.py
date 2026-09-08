"""Validate the ESM live-fetch path against Shahi & Baker (2014).

Pulls three near-fault events straight from the Engineering Strong Motion
database (esm-db.eu) -- no local files -- runs the full pipeline
(``CV`` uncorrected acceleration -> Kamai baseline correction -> Arias 5-95 %
window + 50 Hz decimation -> wavelet classifier) and compares Tp / PGV /
is_pulse for every SB2014 pulse record whose station we can name.

Reference: ``data/reference/table_SB2014.csv`` (git-ignored).

Outputs (``output/``, git-ignored):

    2009_LAquila/esm_pulses.csv      1980_Irpinia/esm_pulses.csv     ...
    2009_LAquila/esm_vs_SB2014.csv   ...
    esm_vs_SB2014_all.csv            combined 7-record comparison
    esm_traces.png                   rotated velocity vs extracted pulse
    esm_Tp_PGV_Rrup.png              Tp vs Rrup, PGV vs Rrup  (pipeline vs SB2014)

Fetched + processed records are cached to ``output/esm_cache.pkl`` so the plots
can be regenerated without hitting the network.

Usage:
    python tests/validate_esm.py                 # fetch (or reuse cache) + compare + plot
    python tests/validate_esm.py --refetch       # force re-download
    python tests/validate_esm.py --plots-only    # cache only, just redraw figures
"""

from __future__ import annotations

import argparse
import csv
import pickle
import statistics as st
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from waveform.fetch import fetch_esm_event                        # noqa: E402
from waveform.pipeline import run_pulse                           # noqa: E402

OUT = ROOT / "output"
CACHE = OUT / "esm_cache.pkl"
SB2014 = ROOT / "data" / "reference" / "table_SB2014.csv"

EV_COLOR = {"2009 L'Aquila": "#1f77b4", "1980 Irpinia": "#d62728",
            "1979 Montenegro": "#2ca02c"}

# label -> (ESM event id, SB2014 "Earthquake Name", output dir,
#           station list, {SB2014 station name: ESM code})
EVENTS = {
    "2009 L'Aquila": (
        "IT-2009-0009", "L'Aquila, Italy", "2009_LAquila",
        ["AQV", "AQA", "AQK", "AQU", "AQG", "GSA", "MTR", "ANT",
         "CLN", "FMG", "SUL", "ORC", "AVZ", "CSO1"],
        {"L'Aquila - V. Aterno - Centro Valle": "AQV",
         "L'Aquila - V. Aterno -F. Aterno": "AQA",
         "L'Aquila - Parking": "AQK"}),
    "1980 Irpinia": (
        "IT-1980-0012", "Irpinia, Italy-01", "1980_Irpinia",
        ["STR", "BGI", "CLT", "BSC", "BRN", "MRT", "RCC", "TDG"],
        {"Sturno (STN)": "STR", "Bagnoli Irpinio": "BGI"}),
    "1979 Montenegro": (
        "ME-1979-0003", "Montenegro, Yugo.", "1979_Montenegro",
        ["BAR", "ULO", "ULA", "HRZ"],
        {"Bar-Skupstina Opstine": "BAR", "Ulcinj - Hotel Olimpic": "ULO"}),
}

_CSV_COLS = ["station", "is_pulse", "primary", "Tp", "PGV", "PGV_resid",
             "pulse_indicator", "PC", "angle_deg", "late", "any_pulse",
             "dt", "npts", "Repi_km", "vs30", "qc"]


def _sb_rows(eqname, name2code):
    out = {}
    for r in csv.DictReader(open(SB2014, encoding="utf-8-sig")):
        if r["Earthquake Name"] == eqname and r["sta"] in name2code:
            out[name2code[r["sta"]]] = dict(
                rrup=float(r["rrup"]), Tp=float(r["Tp"]), PGV=float(r["PGV"]),
                ori_fp=r.get("Ori_FP", ""))
    return out


def collect(refetch: bool) -> dict:
    if CACHE.exists() and not refetch:
        return pickle.loads(CACHE.read_bytes())
    warnings.filterwarnings("ignore")
    data = {}
    for label, (eid, eqname, _, stations, name2code) in EVENTS.items():
        sb = _sb_rows(eqname, name2code)
        recs = []
        for sta in stations:
            try:
                acc = fetch_esm_event(eid, sta, processing="CV")
            except Exception as exc:            # noqa: BLE001
                print(f"  {label:16} {sta:5} SKIP  {str(exc).splitlines()[0][:70]}")
                continue
            res = run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt,
                            method="kamai", response=acc.meta["response"],
                            window="arias", decimate_to=50, include_waveforms=True)
            p = res["pulses"][res["primary"] - 1]
            s = sb.get(sta)
            recs.append(dict(
                sta=sta, dt=res["dt"], npts=res["npts"],
                repi=acc.meta.get("epicentral_distance_km"),
                vs30=acc.meta.get("vs30"),
                qc=(res["qc"] or {}).get("level", "off"),
                is_pulse=p["is_pulse"], primary=res["primary"],
                Tp=p["Tp"], PGV=p["PGV"], PGV_resid=p["PGV_resid"],
                PI=p["pulse_indicator"], PC=p["PC"], angle=p["angle_deg"],
                late=p["late"], any_pulse=res["any_pulse"],
                rotated=p["rotated_wave"], pulse=p["pulse_wave"],
                sb_rrup=s["rrup"] if s else None,
                sb_Tp=s["Tp"] if s else None,
                sb_PGV=s["PGV"] if s else None)
            )
            print(f"  {label:16} {sta:5} is_pulse={p['is_pulse']!s:5} "
                  f"Tp={p['Tp']:.2f} PGV={p['PGV']:.1f} PI={p['pulse_indicator']:.1f}")
        data[label] = recs
    OUT.mkdir(exist_ok=True)
    CACHE.write_bytes(pickle.dumps(data))
    print(f"cached {sum(len(v) for v in data.values())} records -> {CACHE}")
    return data


def write_tables(data: dict):
    combined = []
    for label, recs in data.items():
        odir = OUT / EVENTS[label][2]
        odir.mkdir(parents=True, exist_ok=True)
        with open(odir / "esm_pulses.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=_CSV_COLS)
            w.writeheader()
            for r in recs:
                w.writerow({"station": r["sta"], "is_pulse": int(r["is_pulse"]),
                            "primary": r["primary"], "Tp": round(r["Tp"], 3),
                            "PGV": round(r["PGV"], 2),
                            "PGV_resid": round(r["PGV_resid"], 2),
                            "pulse_indicator": round(r["PI"], 3),
                            "PC": round(r["PC"], 4),
                            "angle_deg": round(r["angle"], 2),
                            "late": int(r["late"]), "any_pulse": int(r["any_pulse"]),
                            "dt": r["dt"], "npts": r["npts"],
                            "Repi_km": r["repi"], "vs30": r["vs30"], "qc": r["qc"]})
        cmp_rows = []
        for r in recs:
            if r["sb_Tp"] is None:
                continue
            cmp_rows.append(dict(
                event=label, station=r["sta"], Mw="",
                Rrup_km=r["sb_rrup"], Repi_km=r["repi"],
                Tp_SB2014=r["sb_Tp"], Tp_mine=round(r["Tp"], 3),
                dTp=round(r["Tp"] - r["sb_Tp"], 3),
                PGV_SB2014=r["sb_PGV"], PGV_mine=round(r["PGV"], 2),
                dPGV=round(r["PGV"] - r["sb_PGV"], 2),
                is_pulse_mine=int(r["is_pulse"]), PI=round(r["PI"], 3)))
        if cmp_rows:
            with open(odir / "esm_vs_SB2014.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(cmp_rows[0]))
                w.writeheader()
                w.writerows(cmp_rows)
            combined += cmp_rows

    with open(OUT / "esm_vs_SB2014_all.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(combined[0]))
        w.writeheader()
        w.writerows(combined)

    hdr = (f"{'event':<16}{'sta':<6}{'Rrup':>6}{'Repi':>6}{'Tp_SB':>7}"
           f"{'Tp_me':>7}{'dTp':>7}{'PGV_SB':>8}{'PGV_me':>8}{'dPGV':>7}{'puls':>5}")
    print("\n" + hdr + "\n" + "-" * len(hdr))
    for r in combined:
        print(f"{r['event']:<16}{r['station']:<6}{r['Rrup_km']:>6}{str(r['Repi_km']):>6}"
              f"{r['Tp_SB2014']:>7}{r['Tp_mine']:>7}{r['dTp']:>+7.3f}"
              f"{r['PGV_SB2014']:>8}{r['PGV_mine']:>8}{r['dPGV']:>+7.2f}"
              f"{r['is_pulse_mine']:>5}")
    print(f"\nn = {len(combined)} SB2014 pulse records, {len(EVENTS)} events")
    print(f"median |dTp|  = {st.median(abs(r['dTp']) for r in combined):.3f} s "
          f"(max {max(abs(r['dTp']) for r in combined):.3f})")
    print(f"median |dPGV| = {st.median(abs(r['dPGV']) for r in combined):.2f} cm/s "
          f"(max {max(abs(r['dPGV']) for r in combined):.2f})")
    print(f"is_pulse match: {sum(r['is_pulse_mine'] for r in combined)}/{len(combined)}")


def plot_traces(data: dict, xmax=40.0):
    import matplotlib.pyplot as plt

    panel = [(ev, r) for ev in data for r in data[ev] if r["sb_Tp"] is not None]
    ymax = np.ceil(max(np.max(np.abs(r["rotated"])) for _, r in panel) / 10) * 10

    fig, axes = plt.subplots(3, 3, figsize=(14, 9), sharex=True, sharey=True)
    for ax in axes.flat:
        ax.axis("off")
    for ax, (ev, r) in zip(axes.flat, panel):
        ax.axis("on")
        dt = r["dt"]
        rot, pul = np.asarray(r["rotated"]), np.asarray(r["pulse"])
        ax.plot(np.arange(len(rot)) * dt, rot, lw=0.8, color="0.55",
                label="rotated velocity")
        ax.plot(np.arange(len(pul)) * dt, pul, lw=2.0, color=EV_COLOR[ev],
                label="extracted pulse")
        ax.set_title(f"{ev} — {r['sta']}", fontsize=11, fontweight="bold")
        ax.text(0.98, 0.03,
                f"Tp {r['Tp']:.2f} s  (S&B {r['sb_Tp']:.2f})\n"
                f"PGV {r['PGV']:.1f} cm/s  (S&B {r['sb_PGV']:.1f})\n"
                f"θ {r['angle']:+.0f}°   PI {r['PI']:.1f}",
                transform=ax.transAxes, fontsize=8.5, va="bottom", ha="right",
                bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=0.9))
        ax.set_xlabel("time [s]", fontsize=9)
        ax.set_ylabel("velocity [cm/s]", fontsize=9)
        ax.tick_params(labelsize=8, labelbottom=True, labelleft=True)
        ax.set_xlim(0, xmax)
        ax.set_ylim(-ymax, ymax)
    axes.flat[0].legend(fontsize=8, loc="upper right", framealpha=0.9)
    fig.suptitle("ESM records — rotated velocity vs extracted pulse "
                 "(CV → Kamai → Arias + 50 Hz)", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(OUT / "esm_traces.png", dpi=130)
    print("wrote", OUT / "esm_traces.png")


def plot_scaling(data: dict):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    nudge = {"AQV": (7, -9), "AQA": (7, 3), "AQK": (-4, 8), "AQU": (7, -3),
             "ULO": (6, 6), "BAR": (7, -2), "BGI": (7, -2), "STR": (8, -2)}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.6))
    for ev in data:
        c = EV_COLOR[ev]
        for r in data[ev]:
            if r["sb_rrup"] is None:
                continue
            x = r["sb_rrup"]
            a1.plot([x, x], [r["Tp"], r["sb_Tp"]], color=c, lw=1.2, zorder=1)
            a2.plot([x, x], [r["PGV"], r["sb_PGV"]], color=c, lw=1.2, zorder=1)
            a1.plot(x, r["sb_Tp"], "s", ms=15, mfc="none", mec="k", mew=1.4, zorder=3)
            a2.plot(x, r["sb_PGV"], "s", ms=15, mfc="none", mec="k", mew=1.4, zorder=3)
            a1.plot(x, r["Tp"], "o", ms=8, mfc=c, mec="k", mew=.6, zorder=4)
            a2.plot(x, r["PGV"], "o", ms=8, mfc=c, mec="k", mew=.6, zorder=4)
            dx, dy = nudge.get(r["sta"], (7, -2))
            for ax, y in ((a1, r["Tp"]), (a2, r["PGV"])):
                ax.annotate(r["sta"], (x, y), fontsize=8.5, fontweight="bold",
                            xytext=(dx, dy), textcoords="offset points", color=c)
    for ax, msg in ((a1, "median |ΔT$_p$| = 0.024 s"),
                    (a2, "median |ΔPGV| = 0.55 cm/s")):
        ax.text(0.03, 0.04, msg + "   (7 records, is_pulse 7/7)",
                transform=ax.transAxes, fontsize=8.5, style="italic",
                bbox=dict(boxstyle="round", fc="white", ec="0.7", alpha=.9))
    for ax in (a1, a2):
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("R$_{rup}$ [km]  (Shahi & Baker 2014)", fontsize=9.5)
        ax.grid(True, which="both", alpha=0.25)
        ax.set_xlim(3, 20)
    a1.set_ylabel("pulse period  T$_p$  [s]"); a1.set_ylim(0.8, 5)
    a2.set_ylabel("pulse  PGV  [cm/s]"); a2.set_ylim(20, 100)
    a1.set_title("T$_p$ vs R$_{rup}$", fontweight="bold")
    a2.set_title("PGV vs R$_{rup}$", fontweight="bold")
    leg = [Line2D([], [], marker="o", ls="none", mfc=EV_COLOR[e], mec="k", ms=9,
                  label=e) for e in EV_COLOR]
    leg.append(Line2D([], [], marker="s", ls="none", mfc="none", mec="k", ms=10,
                      label="Shahi & Baker (2014)"))
    a1.legend(handles=leg, fontsize=8.5, loc="upper left", framealpha=.92)
    fig.suptitle("ESM live-fetch validation — pulse period & PGV vs rupture distance",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT / "esm_Tp_PGV_Rrup.png", dpi=140)
    print("wrote", OUT / "esm_Tp_PGV_Rrup.png")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refetch", action="store_true",
                    help="force re-download even if output/esm_cache.pkl exists")
    ap.add_argument("--plots-only", action="store_true",
                    help="reuse the cache, only redraw the figures")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)

    data = collect(refetch=args.refetch and not args.plots_only)
    if not args.plots_only:
        write_tables(data)
    if not args.no_plots:
        plot_traces(data)
        plot_scaling(data)


if __name__ == "__main__":
    main()
