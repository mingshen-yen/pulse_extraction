"""CLI: one 3-component record -> Kamai baseline correction -> two products.

Writes, for station ``S``:

    <out>/S_VEL_N_basc.txt   <out>/S_VEL_E_basc.txt    baseline-corrected velocity
    <out>/S_VEL_N_frm.txt    <out>/S_VEL_E_frm.txt     + Kamai (2014) fling removed
    <out>/S_pulse_basc.json  <out>/S_pulse_frm.json    pulse-classification summary

Input is either local files or an FDSN request:

    python -m waveform.run_record --sta NAR \
        --mseed  TK.NAR..HNE.mseed TK.NAR..HNN.mseed TK.NAR..HNZ.mseed \
        [--stationxml NAR.xml] --out results/

    python -m waveform.run_record --sta NAR --net TK \
        --origin 2023-02-06T01:17:36 --client IRIS --out results/

Fling parameters are auto-estimated per component; override with
``--fling t1 Tf Dsite`` (applied to both horizontals).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .pipeline import run_pulse_variants
from .qc import QCError, check_record


def _load(args):
    from .fetch import fetch_event_acc, read_three_component
    if args.mseed:
        acc = read_three_component(
            args.mseed, stationxml=args.stationxml,
            client=args.client if args.net else None,
            routing=args.routing,
            nominal_sensitivity=args.nominal_sensitivity)
    else:
        if not (args.net and args.origin):
            raise SystemExit("need --mseed, or --net and --origin for FDSN")
        acc = fetch_event_acc(args.net, args.sta, args.origin,
                              location=args.loc, channel=args.chan,
                              client=args.client, routing=not args.no_routing,
                              nominal_sensitivity=args.nominal_sensitivity)
    return acc


def _dump_variant(out_dir: Path, sta: str, tag: str, v: dict, dt: float):
    np.savetxt(out_dir / f"{sta}_VEL_N_{tag}.txt", np.asarray(v["vel_n"]), fmt="%.8e")
    np.savetxt(out_dir / f"{sta}_VEL_E_{tag}.txt", np.asarray(v["vel_e"]), fmt="%.8e")
    perm = {"E": float(np.asarray(v["disp_e"])[-1]),
            "N": float(np.asarray(v["disp_n"])[-1])} if "disp_e" in v else None
    summary = {
        "station": sta, "dt": dt, "tag": tag,
        "fling_removed": v["fling_removed"], "npts": v["npts"],
        "permanent_disp_cm": perm,
        "any_pulse": v["any_pulse"],
        "pulses": [{k: p[k] for k in
                    ("index", "is_pulse", "angle_deg", "Tp", "PGV", "PGV_resid",
                     "pulse_indicator", "PC", "late")}
                   for p in v["pulses"]],
    }
    (out_dir / f"{sta}_pulse_{tag}.json").write_text(json.dumps(summary, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sta", required=True)
    ap.add_argument("--mseed", nargs="+", help="1 or 3 local waveform files")
    ap.add_argument("--stationxml", help="StationXML for response removal")
    ap.add_argument("--nominal-sensitivity", type=float,
                    help="fallback scalar response, counts per m/s**2")
    ap.add_argument("--no-routing", action="store_true",
                    help="FDSN: do not try the federator / other nodes for metadata")
    ap.add_argument("--routing", action="store_true",
                    help="local files: DO try the FDSN federator / nodes for a missing response")
    ap.add_argument("--net")
    ap.add_argument("--origin", help="origin time for the FDSN request")
    ap.add_argument("--loc", default="*")
    ap.add_argument("--chan", default="HN?")
    ap.add_argument("--client", default="IRIS")
    ap.add_argument("--fling", nargs=3, type=float, metavar=("T1", "TF", "DSITE"),
                    help="fixed fling params for both horizontals (else auto)")
    ap.add_argument("--qc", choices=["gate", "attach", "off"], default="gate",
                    help="gate: abort on QC fail (default); attach: report only; off")
    ap.add_argument("--out", default=".", type=Path)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    acc = _load(args)
    args.out.mkdir(parents=True, exist_ok=True)

    resp = acc.meta.get("response")
    if resp:
        print(f"response: {resp['source']} ({resp['level']})"
              + ("".join(f"\n  - {m}" for m in resp.get("messages", []))))
    qc = check_record(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt, response=resp)
    print(qc)
    (args.out / f"{args.sta}_qc.json").write_text(json.dumps(qc.to_dict(), indent=2))
    if args.qc == "gate" and qc.level == "fail":
        raise SystemExit(f"\n{args.sta}: QC FAILED — not processed "
                         f"(use --qc attach to override)")

    fp = None
    if args.fling:
        fp = {"t1": args.fling[0], "Tf": args.fling[1], "Dsite": args.fling[2]}

    res = run_pulse_variants(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt,
                             fling_params=fp, qc="off", verbose=not args.quiet)

    _dump_variant(args.out, args.sta, "basc", res["basc"], acc.dt)
    _dump_variant(args.out, args.sta, "frm", res["fling_removed"], acc.dt)
    if qc.level != "pass":
        print(f"\n  NOTE: QC level = {qc.level} "
              f"({len(qc.warnings)} warning(s)) — results written but flagged")

    fp = res["fling_params"]
    print(f"\nstation {args.sta}   dt={acc.dt}")
    for c in ("e", "n"):
        print(f"  fling {c.upper()}: t1={fp[c]['t1']:.1f}s  Tf={fp[c]['Tf']:.1f}s  "
              f"Dsite={fp[c]['Dsite']:+.1f} cm")
    for tag, key in (("basc (fling retained)", "basc"),
                     ("frm  (fling removed) ", "fling_removed")):
        v = res[key]
        p1 = v["pulses"][0]
        pd = f"permDisp E={np.asarray(v['disp_e'])[-1]:+.1f} N={np.asarray(v['disp_n'])[-1]:+.1f} cm"
        print(f"  {tag}: {pd}  any_pulse={v['any_pulse']!s:5}  "
              f"pulse1 Tp={p1['Tp']:.2f}s PGV={p1['PGV']:.1f} PI={p1['pulse_indicator']:.2f}")
    print(f"\nwrote 6 files to {args.out}/  (*_basc.* keep fling, *_frm.* remove it)")


if __name__ == "__main__":
    main()
