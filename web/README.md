# Showcase site

Map of near-fault velocity-pulse results at https://mingslab.com/pulse_database/.
A React + TypeScript app (Vite) with Leaflet (react-leaflet) and Chart.js
(react-chartjs-2). All data comes from a small API (`functions/api/`, Cloudflare Pages Functions) over the Cloudflare D1
database `pulse_api`. **D1 is the source of truth**; there are no data files in
the repo.

```
web/             the page: src/App.tsx, src/components/{Sidebar,MapView,Panel}.tsx,
                 src/api.ts (types + fetchers), src/style.css; build -> web/dist
functions/api/   catalogs.js  events.js  event.js  _lib.js (derivation, shared)
functions/       _middleware.js (one public URL, see below)
db/schema.sql    site_catalogs + pipeline tables (idempotent)
```

The "Data source" selector switches between the pipeline results and each
published catalog; events that appear in more than one are cross-linked. The
filter form narrows records by magnitude, Tp and distance (Rrup, else Rhyp);
the active filters are kept in the page URL.

## Data in D1

| table | holds | written by |
|---|---|---|
| `pulse_records`, `event_sources`, `finite_fault_segments`, … | the audited reference workbook, one table per sheet, original column names | `scripts/import_workbook.py` (initial load), then edited in D1 |
| `site_catalogs` | the selector's catalogs: label, citation, link, which `active_sheet` | `db/schema.sql`, then edited in D1 |
| `pipeline_events`, `pipeline_records` | pipeline results incl. pulse traces | `scripts/build_site_data.py` |

The published catalogs are derived from the workbook tables on every request
(`functions/api/_lib.js`), so an edit in D1 is live within a minute (API
cache). Only display fields are published; audit notes and local evidence
paths in the workbook never leave the API.

* **S&B — Shahi & Baker (2014)**: `active_sheet = 'S&B'`, NGA-West2 records with
  fault-normal-pulse flags; each links to its jackwbaker.com page.
* **NCREE Taiwan**: `active_sheet = 'NCREE'`, with event hypocentres.
* **YEN**: `active_sheet = 'YEN'`, near-fault pulse records from Yen et al.
  (2022), Türker et al. (2024) and Yen et al. (2025).

Event and source-model parameters come from `event_sources` and
`finite_fault_segments`.

### Editing data

```bash
# look
wrangler d1 execute pulse_api --remote --command "SELECT * FROM pulse_records WHERE station_original = 'TCU052'"
# change (quote column names that have spaces or capitals, e.g. "Tp (s)")
wrangler d1 execute pulse_api --remote --command "UPDATE event_sources SET catalog_magnitude = 6.4 WHERE event_source_key = '<event_source_key>'"
```

or use the D1 console in the Cloudflare dashboard. Then run
`python scripts/check_site_api.py https://mingslab.com/pulse_database`.

Replacing the workbook tables wholesale from a new `.xlsx` (drops any edits
made in D1 since; export first):

```bash
wrangler d1 export pulse_api --remote --output backup.sql
python scripts/import_workbook.py path/to/pulse_table.xlsx
wrangler d1 execute pulse_api --remote --file db/workbook.sql --yes
```

### Pipeline results

Each event: fetch strong-motion waveforms (GeoNet FDSN / ESM) → `run_pulse`
(Kamai baseline correction · Arias 5–95 % window · 50 Hz) → one row in
`pipeline_events` plus its stations in `pipeline_records`. Event parameters and
a schematic rupture rectangle (moment-tensor nodal plane + Wells & Coppersmith
scaling) come from USGS where available.

```bash
pip install -r ../requirements.txt
python ../scripts/build_site_data.py --curated               # rebuild the curated events
python ../scripts/build_site_data.py --event 2010_darfield   # just one
python ../scripts/build_site_data.py --poll --min-mag 5.8    # add new live events (USGS)
python ../scripts/d1_pipeline.py list                        # what is in D1
```

These write to the remote D1 (needs `wrangler login`); add `--local` to write
to the local copy used by `wrangler pages dev`.

## API

| endpoint | returns |
|---|---|
| `GET /api/catalogs` | every catalog with its event and record counts |
| `GET /api/events?catalog=sb&mag_min=7&tp_min=2&dist_max=15` | events with at least one matching record; `n` / `n_pulse` count the matching records only |
| `GET /api/event?catalog=sb&key=…&tp_min=2` | one event with its stations narrowed to the filters and stats for them |

Filter parameters: `mag_min`, `mag_max`, `tp_min`, `tp_max`, `dist_min`,
`dist_max`.

## Run locally

From the repo root:

```bash
wrangler d1 export pulse_api --remote --output /tmp/pulse_api.sql   # copy the data
wrangler d1 execute pulse_api --local --file /tmp/pulse_api.sql --yes
(cd web && npm ci && npm run build)
wrangler pages dev                                    # web/dist + API on :8788
(cd web && npm run dev)                               # hot reload on :5173, api/* -> :8788
python scripts/check_site_api.py http://localhost:8788
node --test tests/api_lib.test.mjs                    # API unit tests
```

## Deploy

The site is hosted on Cloudflare Pages (project `pulse-extraction`, production
branch `main`) and served at https://mingslab.com/pulse_database/ through a
proxy in the personal site (mingshen-yen/minghsuan,
`functions/pulse_database/[[path]].js`). That proxy marks its requests with
`X-Pulse-Proxy`; `functions/_middleware.js` sends direct visits to
`pulse-extraction.pages.dev` to mingslab.com, so there is one public URL.

* `.github/workflows/deploy.yml` builds `web/` and uploads `web/dist` +
  `functions/` on every push to `main` that touches them, applies
  `db/schema.sql` (idempotent, never touches data) and checks the live API.
* `.github/workflows/site-data.yml` runs `--poll` every 6 h and writes new
  events straight into D1; nothing is committed or redeployed.
* `.github/workflows/d1-backup.yml` exports D1 every Monday as a workflow
  artifact (kept 90 days), on top of D1's 30-day Time Travel.

All three need the repo secret `CLOUDFLARE_API_TOKEN` (Account → Cloudflare
Pages → Edit, Account → D1 → Edit) and the repo variable
`CLOUDFLARE_ACCOUNT_ID`.

Manual deploy:

```bash
(cd web && npm ci && npm run build)
wrangler pages deploy web/dist --project-name pulse-extraction --branch main
```
