#!/usr/bin/env python3
"""Turn the published pulse tables in ``data/reference/*.csv`` into catalog JSON
for the showcase site (``site/data/reference/<catalog>.json`` + ``index.json``).

    python scripts/import_reference_tables.py

Catalogs
--------
* ``taiwan_ncree``       -- NCREE Taiwan pulse database: hypocentre + station
                           coordinates, so it maps fully.
* ``shahi_baker_2014``   -- Shahi & Baker (2014), NGA-West2: station *names*
                           only, so records are a table; epicentres from NCREE
                           where the event overlaps, else a small lookup.
* ``yen_2022`` / ``turkey_2023`` -- small pulse catalogs, same treatment.

These are third-party research tables; every catalog JSON carries its
``citation`` and ``url`` and the site shows them.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from waveform.site_export import haversine_km                     # noqa: E402

REF = ROOT / "data" / "reference"
OUT = ROOT / "site" / "data" / "reference"

CITATIONS = {
    "taiwan_ncree": dict(
        label="NCREE Taiwan pulse database", short="NCREE",
        citation="Chao et al. — NCREE near-fault pulse-like ground-motion "
                 "database, Taiwan (updated). Hypocentre & station coordinates "
                 "included.",
        url="https://www.ncree.org/"),
    "shahi_baker_2014": dict(
        label="Shahi & Baker (2014)", short="S&B 2014",
        citation="Shahi, S.K. & Baker, J.W. (2014). An efficient algorithm to "
                 "identify strong-velocity pulses in multicomponent ground "
                 "motions. Bull. Seismol. Soc. Am. 104(5). NGA-West2 records.",
        url="https://doi.org/10.1785/0120130191"),
    "yen_2022": dict(
        label="Yen et al. (2022)", short="Yen 2022",
        citation="Yen et al. (2022) near-fault velocity-pulse catalog "
                 "(Kumamoto, Iburi, Meinong, Hualien, Darfield).",
        url=""),
    "turkey_2023": dict(
        label="2023 Türkiye sequence", short="Türkiye 2023",
        citation="Pulse metrics for the 2023 Kahramanmaraş (Türkiye) doublet "
                 "and 2022 Düzce, from a regional study.",
        url=""),
}

# epicentres for SB2014 / Yen / Turkey events NOT covered by NCREE.
# lat, lon, depth_km, mag  (well-constrained mainshock hypocentres)
EXTRA_EPI = {
    "loma_prieta|1989": (37.04, -121.88, 17.5, 6.93),
    "chuetsu_oki|2007": (37.54, 138.45, 10.0, 6.8),
    "whittier_narrows_01|1987": (34.05, -118.08, 14.6, 5.99),
    "coalinga_02|1983": (36.23, -120.32, 10.0, 5.09),
    "coalinga_05|1983": (36.24, -120.28, 8.4, 5.77),
    "coalinga_07|1983": (36.17, -120.27, 9.6, 5.21),
    "wenchuan_china|2008": (31.00, 103.40, 19.0, 7.9),
    "iwate|2008": (39.03, 140.88, 7.8, 6.9),
    "niigata_japan|2004": (37.31, 138.83, 13.0, 6.63),
    "morgan_hill|1984": (37.31, -121.68, 8.4, 6.19),
    "san_fernando|1971": (34.44, -118.41, 8.4, 6.61),
    "tottori_japan|2000": (35.27, 133.35, 10.0, 6.61),
    "kalamata_greece_02|1986": (37.04, 22.14, 8.0, 5.4),
    "westmorland|1981": (33.10, -115.62, 2.4, 5.9),
    "n_palm_springs|1986": (33.99, -116.61, 11.0, 6.06),
    "joshua_tree_ca|1992": (33.96, -116.32, 12.3, 6.1),
    "mammoth_lakes_06|1980": (37.56, -118.83, 14.0, 5.94),
    "san_salvador|1986": (13.67, -89.16, 7.3, 5.8),
    "northern_calif_03|1954": (40.29, -124.05, 15.0, 6.5),
    "northwest_china_03|1997": (35.07, 87.33, 10.0, 6.1),
    "imperial_valley_07|1979": (32.93, -115.51, 8.0, 5.01),
    "iburi|2018": (42.69, 141.93, 37.0, 6.6),
    "kumafore|2016": (32.74, 130.81, 11.4, 6.1),
    "duzce|2022": (40.83, 31.08, 10.0, 6.0),
    "turkey_1|2023": (37.17, 37.03, 8.6, 7.8),
    "turkey_2|2023": (38.02, 37.20, 7.0, 7.5),
    "taiwan_smart1_40|1986": (24.68, 121.77, 8.0, 6.32),   # Lotung SMART1 array
    "yountville|2000": (38.38, -122.41, 10.1, 5.0),
}


def key(name, year=""):
    s = re.sub(r"[^a-z0-9]+", "_", f"{name}".lower()).strip("_")
    return f"{s}|{year}" if year else s


def _f(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _stats(stations):
    pul = [s for s in stations if s["is_pulse"]]
    tps = sorted(s["Tp"] for s in pul if s["Tp"])
    import statistics as st
    return {
        "n": len(stations), "n_pulse": len(pul),
        "pulse_fraction": round(len(pul) / len(stations), 3) if stations else None,
        "Tp_median": round(st.median(tps), 3) if tps else None,
        "PGV_median": (round(st.median(sorted(s["PGV"] for s in pul)), 2)
                       if pul else None),
        "Tp_range": [tps[0], tps[-1]] if tps else [None, None],
        "by_distance": _bins(stations),
        "scatter": [{"code": s["code"], "repi_km": s.get("repi_km"),
                     "rrup_km": s.get("rrup_km"), "Tp": s["Tp"], "PGV": s["PGV"],
                     "is_pulse": s["is_pulse"]}
                    for s in stations
                    if (s.get("rrup_km") or s.get("repi_km")) is not None],
    }


def _bins(stations, edges=(0, 5, 10, 20, 40, 80, 160)):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        g = [s for s in stations
             if (s.get("rrup_km") or s.get("repi_km")) is not None
             and lo <= (s.get("rrup_km") or s["repi_km"]) < hi]
        if not g:
            continue
        npul = sum(1 for s in g if s["is_pulse"])
        tps = sorted(s["Tp"] for s in g if s["is_pulse"] and s["Tp"])
        out.append({"r_lo": lo, "r_hi": hi, "n": len(g), "n_pulse": npul,
                    "pulse_fraction": round(npul / len(g), 3),
                    "Tp_median": tps[len(tps) // 2] if tps else None})
    return out


# --------------------------------------------------------------------------- #
def build_ncree():
    rows = list(csv.DictReader(open(REF / "Taiwan_NCREE.csv", encoding="utf-8-sig")))
    events = {}
    for r in rows:
        ek = key(r["EQ_name"])
        ev = events.setdefault(ek, dict(
            key=ek, name=r["EQ_name"].replace("_", " "),
            year=re.match(r"(\d{4})", r["EQ_name"]).group(1)
            if re.match(r"\d{4}", r["EQ_name"]) else None,
            lat=_f(r["Hypo lat"]), lon=_f(r["hypo lon"]),
            depth_km=_f(r["hypo depth"]), mag=_f(r["Mw"]),
            fault_type=r["fault type"] or None, stations=[]))
        pgv = max(_f(r["PGV_EW"], 0), _f(r["PGV_NS"], 0)) or None
        ev["stations"].append(dict(
            code=r["sta id"], lat=_f(r["sta lat"]), lon=_f(r["sta lon"]),
            vs30=_f(r["vs30"]), rrup_km=_f(r["rrup"]),
            is_pulse=str(r["Ipulse_H"]).strip().upper() == "TRUE",
            Tp=_f(r["Tp"]), PGV=pgv,
            fling=str(r["fling"]).strip().upper() == "TRUE",
            pga=max(_f(r["PGA_EW"], 0), _f(r["PGA_NS"], 0)) or None))
    return _finish_events(events, use_rrup=True)


def _generic_table(fname, name_col="Earthquake Name", year_col="Year"):
    rows = [r for r in csv.DictReader(open(REF / fname, encoding="utf-8-sig"))
            if r.get(name_col)]
    events = {}
    for r in rows:
        nm, yr = r[name_col].strip(), (r.get(year_col) or "").strip()
        ek = key(nm, yr)
        ev = events.setdefault(ek, dict(
            key=ek, name=nm, year=yr or None, lat=None, lon=None,
            depth_km=None, mag=_f(r.get("mag")), fault_type=None, stations=[]))
        ev["stations"].append(dict(
            code=str(r["sta"]).strip(), lat=None, lon=None, vs30=None,
            rrup_km=_f(r.get("rrup")), rhyp_km=_f(r.get("rhypo")),
            is_pulse=(str(r.get("Fault Normal Pulse", "1")).strip() in ("1", "1.0")
                      if "Fault Normal Pulse" in r else True),
            Tp=_f(r.get("Tp")), PGV=_f(r.get("PGV")),
            ori_fp=_f(r.get("Ori_FP")), ori_n=_f(r.get("Ori_N"))))
    return events


def build_from_table(fname, ncree_epi):
    events = _generic_table(fname)
    for ek, ev in events.items():
        epi = ncree_epi.get(_match_ncree(ev["name"], ev["year"])) or EXTRA_EPI.get(ek)
        if epi:
            ev["lat"], ev["lon"], ev["depth_km"], m = epi
            ev["mag"] = ev["mag"] or m
    return _finish_events(events, use_rrup=True)


_NCREE_ALIASES = {
    "chi_chi_taiwan": "1999_chichi_taiwan",
    "chi_chi_taiwan_03": "1999_chichi_03_taiwan",
    "chi_chi_taiwan_04": "1999_chichi_07_taiwan",
    "chi_chi_taiwan_06": "1999_chichi_05_taiwan",
    "northridge_01": "1994_northridge_01_usa",
    "imperial_valley_06": "1979_imperialvalley_06_usa",
    "parkfield_02_ca": "2004_parkfield_02_ca",
    "darfield_new_zealand": "2010_darfield_newzealand",
    "christchurch_new_zealand": "2011_christchurch_newzealand",
    "kobe_japan": "1995_kobe_japan",
    "kocaeli_turkey": "1999_kocaeli_turkey",
    "duzce_turkey": "1999_duzce_turkey",
    "cape_mendocino": "1992_capemendocino_usa",
    "coyote_lake": "1979_coyotelake_usa",
    "landers": "1992_landers_usa",
    "el_mayor_cucapah": "2010_elmayor_cucapah_mexico",
    "superstition_hills_02": "1987_superstitionhills_02_usa",
    "l_aquila_italy": "2009_laquila_italy",
    "montenegro_yugo": "1979_montenegro_yugoslavia",
    "irpinia_italy_01": "1980_irpinia_01_italy",
    "denali_alaska": "2002_denali_alaska",
    "tabas_iran": "1978_tabas_iran",
    "bam_iran": "2003_bam_iran",
    "kumamoto": "2016_kumamoto_japan",
    "meinong": "2016_meinong_taiwan",
    "hualien": "2018_hualien_taiwan",
    "darfield": "2010_darfield_newzealand",
}


def _match_ncree(name, year):
    k = key(name)
    return _NCREE_ALIASES.get(k, key(name, year))


def _finish_events(events, *, use_rrup):
    out = []
    for ev in events.values():
        for s in ev["stations"]:
            if s.get("lat") is not None and ev["lat"] is not None:
                s["repi_km"] = round(
                    haversine_km(ev["lat"], ev["lon"], s["lat"], s["lon"]), 2)
            for k in ("Tp", "PGV", "rrup_km", "repi_km", "vs30", "pga",
                      "ori_fp", "ori_n", "rhyp_km"):
                if isinstance(s.get(k), float):
                    s[k] = round(s[k], 3)
        ev["stats"] = _stats(ev["stations"])
        ev["n_mappable"] = sum(1 for s in ev["stations"] if s.get("lat"))
        out.append(ev)
    out.sort(key=lambda e: (e.get("year") or "", e["name"]))
    return out


def write_catalog(cid, events):
    meta = CITATIONS[cid]
    OUT.mkdir(parents=True, exist_ok=True)
    doc = dict(schema="pulse-extraction/reference/1", catalog=cid,
              **meta, n_events=len(events),
              n_records=sum(e["stats"]["n"] for e in events),
              pulse_only=cid != "shahi_baker_2014", events=events)
    (OUT / f"{cid}.json").write_text(json.dumps(doc, indent=1))
    print(f"{cid:18} {len(events):3} events  "
          f"{doc['n_records']:4} records  "
          f"{sum(e['n_mappable'] for e in events):4} mappable stations")
    return dict(id=cid, label=meta["label"], short=meta["short"],
               url=meta["url"], n_events=len(events), n_records=doc["n_records"],
               pulse_only=cid != "shahi_baker_2014")


def main():
    ncree = build_ncree()
    ncree_epi = {e["key"]: (e["lat"], e["lon"], e["depth_km"], e["mag"])
                 for e in ncree if e["lat"] is not None}
    catalogs = [
        write_catalog("taiwan_ncree", ncree),
        write_catalog("shahi_baker_2014",
                      build_from_table("table_SB2014.csv", ncree_epi)),
        write_catalog("yen_2022", build_from_table("table_YEN2022.csv", ncree_epi)),
        write_catalog("turkey_2023",
                      build_from_table("table_turkey2023.csv", ncree_epi)),
    ]
    (OUT / "index.json").write_text(json.dumps({"catalogs": catalogs}, indent=1))
    print(f"\nwrote {OUT}/index.json  ({len(catalogs)} catalogs)")


if __name__ == "__main__":
    main()
