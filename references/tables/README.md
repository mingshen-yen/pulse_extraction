# Reference pulse table

`pulse_table.xlsx` is the audited source of truth for the three published
catalogs displayed by the site. It contains 701 active station records:

| `active_sheet` | records | public catalog |
|---|---:|---|
| `S&B` | 243 | Shahi & Baker (2014) |
| `NCREE` | 340 | NCREE Taiwan pulse database |
| `YEN` | 118 | Yen et al. (2022), Türker et al. (2024), Yen et al. (2025) |

The site build reads `Pulse_records`, `Event_sources`, and
`Finite_fault_segments` with `scripts/build_reference_catalogs.py`. It exports
only public display fields to `site/data/reference/*.json`; audit notes,
filesystem paths, and other working columns are excluded.

Rebuild and validate with:

```bash
python scripts/build_reference_catalogs.py
pytest -q tests/test_reference_catalogs.py
```
