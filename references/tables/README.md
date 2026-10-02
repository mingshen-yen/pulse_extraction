# Reference pulse table

The audited reference workbook (`pulse_table.xlsx`) now lives in the Cloudflare
D1 database `pulse_api`, one table per sheet with the sheet's own column names,
and **D1 is the source of truth**: edit the data there. The site derives the
three published catalogs from it on every request (`functions/api/_lib.js`).
It has 701 active station records:

| `active_sheet` | records | public catalog |
|---|---:|---|
| `S&B` | 243 | Shahi & Baker (2014) |
| `NCREE` | 340 | NCREE Taiwan pulse database |
| `YEN` | 118 | Yen et al. (2022), Türker et al. (2024), Yen et al. (2025) |

| sheet | D1 table |
|---|---|
| Pulse_records | `pulse_records` (the catalogs read this) |
| Event_sources | `event_sources` (hypocentre, magnitude, mechanism, planes) |
| Finite_fault_segments | `finite_fault_segments` |
| Station_coords, Sources_method, Event_match_audit, Distance_check, Overview | same name, lowercase (audit trail; not published) |
| S&B, NCREE, YEN | `sheet_sb`, `sheet_ncree`, `sheet_yen` (original source tables) |

Only public display fields are published; audit notes, filesystem paths and
other working columns stay in D1. The one rename: the S&B sheet has both
`Mechanism` and `mechanism`, and SQLite column names ignore case, so the second
is `sheet_sb."mechanism_col23"`.

How to edit, re-import a new workbook, and back up: see `site/README.md`.
