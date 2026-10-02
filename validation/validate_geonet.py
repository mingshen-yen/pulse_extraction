"""Validate the GeoNet FDSN fetch path against Shahi & Baker (2014).

Downloads two Canterbury (NZ) events straight from GeoNet's FDSN service --
raw counts + StationXML, so this exercises the full instrument-response
deconvolution path -- runs ``fetch -> Kamai -> Arias 5-95 % + 50 Hz ->
classifier`` and compares Tp / PGV / is_pulse for the SB2014 pulse records.

    2010 Darfield      Mw 7.0   2010-09-03T16:35:41  (long-period pulses, Tp 6-13 s)
    2011 Christchurch  Mw 6.2   2011-02-21T23:51:42

Reference: ``data/reference/table_SB2014.csv`` (git-ignored).
Outputs mirror ``validate_esm.py`` under ``output/`` with the ``geonet`` prefix;
records cache to ``output/geonet_cache.pkl``.

    python validation/validate_geonet.py [--refetch] [--plots-only] [--no-plots]
"""

from __future__ import annotations

import argparse
import csv
import pickle
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from waveform.fetch import fetch_event_acc                        # noqa: E402
from waveform.pipeline import run_pulse                           # noqa: E402
from validation._pulse_validation import (compute_stats, plot_scaling,  # noqa: E402
                                     plot_traces, write_tables)

OUT = ROOT / "output"
CACHE = OUT / "geonet_cache.pkl"
SB2014 = ROOT / "data" / "reference" / "table_SB2014.csv"
REF_LABEL, REF_SHORT = "Shahi & Baker (2014)", "S&B"

COLORS = {"2010 Darfield": "#1f77b4", "2011 Christchurch": "#d62728"}

# label -> (origin time, SB2014 "Earthquake Name", output dir, extra non-ref stations)
EVENTS = {
    "2010 Darfield": ("2010-09-03T16:35:41", "Darfield, New Zealand",
                      "2010_Darfield", []),
    "2011 Christchurch": ("2011-02-21T23:51:42", "Christchurch, New Zealand",
                          "2011_Christchurch", []),
}
DIRS = {k: v[2] for k, v in EVENTS.items()}
NET, CHAN, CLIENT = "NZ", "HN?", "GEONET"

# GeoNet serves these for the event but the three components have large data
# gaps (unequal length) -> only an ~18 s fragment survives the merge, so the
# pulse result is meaningless.  Excluded from the comparison, not a port issue.
GAPPY = {("2011 Christchurch", "CMHS")}


def _sb_rows(eqname):
    """{station code: (rrup, Tp, PGV)} for every SB2014 row of this event."""
    out = {}
    for r in csv.DictReader(open(SB2014, encoding="utf-8-sig")):
        if r["Earthquake Name"] == eqname:
            out[r["sta"].strip()] = (float(r["rrup"]), float(r["Tp"]),
                                     float(r["PGV"]))
    return out


def collect(refetch: bool) -> dict:
    if CACHE.exists() and not refetch:
        return pickle.loads(CACHE.read_bytes())
    warnings.filterwarnings("ignore")
    data = {}
    for label, (t0, eqname, _, extra) in EVENTS.items():
        sb = _sb_rows(eqname)
        recs = []
        for sta in list(sb) + list(extra):
            if (label, sta) in GAPPY:
                print(f"  {label:18} {sta:5} SKIP  gappy record (unequal-length "
                      f"components)")
                continue
            try:
                acc = fetch_event_acc(NET, sta, t0, channel=CHAN, client=CLIENT,
                                      pre_seconds=30, post_seconds=140)
            except Exception as exc:            # noqa: BLE001
                print(f"  {label:18} {sta:5} SKIP  {str(exc).splitlines()[0][:60]}")
                continue
            res = run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt,
                            method="kamai", response=acc.meta["response"],
                            window="arias", decimate_to=50, include_waveforms=True)
            p = res["pulses"][res["primary"] - 1]
            s = sb.get(sta)
            recs.append(dict(
                sta=sta, dt=res["dt"], npts=res["npts"], dist_km=None,
                vs30=None, qc=(res["qc"] or {}).get("level", "off"),
                is_pulse=p["is_pulse"], primary=res["primary"],
                Tp=p["Tp"], PGV=p["PGV"], PGV_resid=p["PGV_resid"],
                PI=p["pulse_indicator"], PC=p["PC"], angle=p["angle_deg"],
                late=p["late"], any_pulse=res["any_pulse"],
                rotated=p["rotated_wave"], pulse=p["pulse_wave"],
                sb_rrup=s[0] if s else None, sb_Tp=s[1] if s else None,
                sb_PGV=s[2] if s else None))
            print(f"  {label:18} {sta:5} resp={acc.meta['response']['source']:5} "
                  f"is_pulse={p['is_pulse']!s:5} Tp={p['Tp']:6.2f} "
                  f"PGV={p['PGV']:6.1f} PI={p['pulse_indicator']:5.1f}")
        data[label] = recs
    OUT.mkdir(exist_ok=True)
    CACHE.write_bytes(pickle.dumps(data))
    print(f"cached {sum(len(v) for v in data.values())} records -> {CACHE}")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--plots-only", action="store_true")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)

    data = collect(refetch=args.refetch and not args.plots_only)
    if not args.plots_only:
        write_tables(data, DIRS, OUT, prefix="geonet", ref_label=REF_LABEL)
    stats = compute_stats(data)
    if not args.no_plots:
        plot_traces(data, COLORS, OUT, prefix="geonet", ref_short=REF_SHORT,
                    xmax=60.0, title="GeoNet records — rotated velocity vs "
                    "extracted pulse (raw counts → response → Kamai → Arias + 50 Hz)")
        plot_scaling(data, COLORS, OUT, prefix="geonet", ref_label=REF_LABEL,
                     stats=stats, title="GeoNet live-fetch validation — "
                     "pulse period & PGV vs rupture distance")


if __name__ == "__main__":
    main()
