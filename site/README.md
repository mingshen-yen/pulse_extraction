# Showcase site

Static map of near-fault velocity-pulse results. No build step — plain HTML +
Leaflet + Chart.js from CDNs, reading JSON in `data/`.

```
site/
  index.html  style.css  app.js
  data/
    index.json                    pipeline event list (built)
    events/<key>.json             per-event: event + fault + stations + stats + pulse traces
    reference/index.json          published-catalog list
    reference/<catalog>.json      taiwan_ncree, shahi_baker_2014
```

The "Data source" selector on the page switches between the pipeline results and
each published catalog; events that appear in more than one are cross-linked.

## Build the data

```bash
pip install -r ../requirements.txt
python ../scripts/build_site_data.py --curated          # rebuild the 6 curated events
python ../scripts/build_site_data.py --event 2010_darfield   # just one
python ../scripts/build_site_data.py --poll --min-mag 5.8    # append new live events (USGS)
python ../scripts/build_reference_catalogs.py                # rebuild published catalogs from the audited workbook
```

`build_reference_catalogs.py` builds three published catalogs from the audited
workbook `references/tables/pulse_table.xlsx`. Only fields used by the public
interface are exported; audit notes and local evidence paths stay out of the
site JSON.

* **Shahi & Baker (2014)** — `Baker(2014)` sheet, 243 records, all mapped, with
  fault-normal-pulse flags; each record links to its jackwbaker.com page.
* **NCREE Taiwan** — 340 records, all mapped, with event hypocentres.
* **YEN** — 118 near-fault pulse records, all mapped, combining Yen et al.
  (2022), Türker et al. (2024), and Yen et al. (2025).

Event and source-model parameters come from the workbook's audited
`Event_sources` and `Finite_fault_segments` sheets. The generated
`site/data/reference/*.json` is committed; each catalog carries its citation.

Each event: fetch strong-motion waveforms (GeoNet FDSN / ESM) → `run_pulse`
(Kamai baseline correction · Arias 5–95 % window · 50 Hz) → one `data/events/*.json`.
Event parameters and a schematic rupture rectangle (moment-tensor nodal plane +
Wells & Coppersmith magnitude scaling) come from USGS where available.

## View locally

```bash
python -m http.server -d site 8000   # then open http://localhost:8000
```

(Needs to be served over http — `file://` blocks the `fetch()` calls.)

## API (Cloudflare D1)

`functions/api/*` (Pages Functions) serve the same data from the D1 database
`pulse_db`, with record filters on magnitude, Tp and distance (Rrup, else Rhyp):

| endpoint | returns |
|---|---|
| `GET /api/catalogs` | every catalog with its event and record counts |
| `GET /api/events?catalog=sb&mag_min=7&tp_min=2&dist_max=15` | events with at least one matching record; `n` / `n_pulse` count the matching records only |
| `GET /api/event?catalog=sb&key=…&tp_min=2` | one event as in the static file, with stations narrowed to the filters and stats recomputed |

Filter parameters: `mag_min`, `mag_max`, `tp_min`, `tp_max`, `dist_min`,
`dist_max`. The page keeps the active filters in its URL, so filtered views
can be shared. Served without the API (`python -m http.server`), the page
reads `data/*.json` directly and the filter form is disabled.

D1 is loaded from `site/data/*.json`, so the JSON stays the single build output:

```bash
python scripts/build_d1_seed.py                                   # -> db/seed.sql
wrangler d1 execute pulse_db --local --file db/seed.sql --yes     # local copy
wrangler pages dev                                                # site + API on :8788
python scripts/check_api_parity.py http://localhost:8788          # API == static files
```

## Deploy

The site is hosted on Cloudflare Pages (project `pulse-extraction`).
`.github/workflows/deploy.yml` reloads D1 and uploads `site/` + `functions/` on
every push to `main` that touches them, and `.github/workflows/site-data.yml`
runs `--poll` every 6 h, commits new event JSON and then calls the deploy
workflow. Both need the repo secret `CLOUDFLARE_API_TOKEN` (Account →
Cloudflare Pages → Edit, Account → D1 → Edit) and the repo variable
`CLOUDFLARE_ACCOUNT_ID`.

Manual deploy:

```bash
python scripts/build_d1_seed.py
wrangler d1 execute pulse_db --remote --file db/seed.sql --yes
wrangler pages deploy site --project-name pulse-extraction --branch feat/showcase-site
```
