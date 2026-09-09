# Reference pulse tables

## `pulse_records_with_coords.csv`

A single row-per-record table that merges the published near-fault
velocity-pulse catalogs and resolves a station coordinate for every record.
It is the source for the showcase site's reference catalogs
(`scripts/import_reference_tables.py` → `site/data/reference/*.json`).

`source_sheet` says which published table each row came from:

| `source_sheet` | rows | reference |
|---|---|---|
| `Baker(2014)` | 243 | Shahi & Baker (2014), *BSSA* 104(5); jackwbaker.com/pulse_classification_v2 |
| `Baker_moderate` | 157 | same records, moderate-directivity annotation |
| `Tf_Kamai(2014)` | 84 | Kamai, Abrahamson & Graves (2014) fling table |
| `Taiwan database(NCREE)` | 340 | NCREE Taiwan near-fault pulse database |
| `Yen(2022)` | 84 | Yen et al. (2022) |
| `Yen_corr_fling(2023)` / `Yen_uncorr_fling(2023)` | 34 + 34 | Yen et al. (2023) fling study |

Key columns: `event_original`, `year`, `station_original`, `latitude_deg` /
`longitude_deg` / `coord_status` (`matched` / `original` / `unresolved`),
`NGA_RSN`, `Mw`, `Tp_s` (or `Tp_H_s`), `PGV_cm_s`, `Rrup_km` /
`closest_distance_km`, `orientation_north_deg`, `fault_normal_pulse` /
`Ipulse_H`, `fling`, `hypo_lat_deg` / `hypo_lon_deg` (NCREE sheet).

The site currently builds catalogs from `Baker(2014)`, `Taiwan database(NCREE)`
and `Yen(2022)`; add more in `CATALOGS` in `scripts/import_reference_tables.py`.
