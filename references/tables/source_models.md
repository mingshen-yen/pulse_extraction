# Event source models — provenance

`source_models.csv` lists every event in the site's reference catalogs that was
given a **source model** by `scripts/import_reference_tables.py`
(67 events / 46+56+6 total). Use it to spot-check reliability.

## How each event was matched

The published pulse tables carry no event **date** (only a year), so each event
is matched to a USGS ComCat event by:

1. year window `YYYY-01-01 … YYYY+1-01-01`
2. hypocentre within **55 km** of the table's epicentre
3. magnitude within **±0.6** of the table's `Mw`
4. of the survivors, the **closest** one is used

If one ComCat event ends up matched to several *distinct* catalog events
(aftershock sequences — 1999 Chi-Chi -03/-05/-07, 1999 Chiayi -01/-02, 2013
Nantou -01/-02), the model is kept only on the nearest and **dropped** from the
rest (4 events dropped). USGS ids still shared by two rows are the *same*
earthquake appearing in both the NCREE and the Shahi & Baker catalog —
expected.

Always confirm against `usgs_event_url` in the CSV.

## What the geometry means

| `fault_kind` | count | what to trust |
|---|---|---|
| `USGS finite-fault (slip-model outline)` | 7 | The map polygon is the **convex hull of the USGS finite-fault slip model's subfaults with slip ≥ 15 % of peak** — a schematic footprint of the actual published model (`finite_fault_url`), not a rectangle. `fault_L_km` × `fault_W_km` and strike/dip are the model's reported values, `max_slip_m` is the model peak. Still one polygon, so shallow thrusts (2015 Gorkha, W ≈ 168 km down-dip) still project to a large surface area. |
| `mag-scaled from NP1` | 60 | Only the **orientation** (`NP1_strike/dip/rake`, from the USGS moment tensor or focal mechanism) is real. `fault_L_km` × `fault_W_km` is **Wells & Coppersmith (1994)** magnitude scaling — a schematic size, not a rupture model. Which nodal plane is the fault plane is **not** resolved (NP1 is used arbitrarily; NP2 is in the CSV). |

The 7 finite-fault events:

| year | event | USGS id | L×W km |
|---|---|---|---|
| 1999 | Chi-Chi, Taiwan | `usp0009eq0` | 144 × 51 |
| 1999 | Kocaeli, Turkey | `usp0009d4z` | 175 × 34 |
| 2002 | Denali, Alaska | `ak002e435qpj` | 40 × 28 |
| 2008 | Wenchuan, China | `usp000g650` | 132 × 28 |
| 2015 | Gorkha, Nepal | `us20002926` | 193 × 168 |
| 2016 | Kaikōura, New Zealand | `us1000778i` | 98 × 26 |
| 2016 | Kumamoto, Japan | `us20005iis` | 90 × 26 |

## Known weak spots to check first

* **Pre-~1995 events** — ComCat moment tensors / focal mechanisms for 1978–1994
  events are often from later reviewed catalogs; cross-check with the source
  literature (Tabas 1978, Imperial Valley 1979, Irpinia 1980, Loma Prieta 1989…).
* **Small events** (M ≤ 6) — the ±0.6 magnitude gate can still admit a nearby
  larger event; the W&C rectangle is tiny and the mechanism less certain
  (Yountville 2000 M5.0, Mammoth Lakes 1980, several Taiwan M5.7–6.3).
* **Offshore / doublet events** — Hengchun 2006, Hualien Offshore 2002/2009:
  the year-window query can pick the wrong member of a doublet.
