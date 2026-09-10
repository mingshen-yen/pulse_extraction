# Reference-catalog database (Cloudflare D1 / SQLite)

**Option A skeleton.** The published pulse catalogs (Shahi & Baker 2014, NCREE
Taiwan, Yen 2022) move out of the hand-built `site/data/reference/*.json` and
into a SQLite database. Cloudflare **Pages Functions** (`functions/api/*`) query
it and return the *same JSON shapes* `site/app.js` already consumes, so the
frontend change is one fetch-URL swap.

The pulse **pipeline** (`scripts/build_site_data.py`, needs obspy/scipy) is
unchanged: it stays a local / CI batch job and keeps writing
`site/data/events/*.json` as static files.

```
references/tables/pulse_table_audited.xlsx   audited source of truth (12 sheets)
        │  scripts/load_workbook.py
        ▼
db/schema.sql + db/migrations/0001_init.sql  5 tables: catalogs, events,
db/seed.sql                                  fault_segments, stations, pulse_records
        │  wrangler d1
        ▼
D1 "pulse_db"  ◄── functions/_lib.js ──►  /api/catalogs , /api/catalog/:id
                                                 │
                                          site/app.js (REF_API)
```

## Regenerate the SQL from the workbook

```bash
pip install openpyxl
python scripts/load_workbook.py                       # -> db/seed.sql
python scripts/load_workbook.py --sqlite db/site.dev.db   # + a local SQLite DB
```

`db/seed.sql` and `db/site.dev.db` are generated artefacts (git-ignored).
`db/schema.sql` is the human-owned schema; `db/migrations/0001_init.sql` is the
identical first migration wrangler applies.

## Prove the API matches the current site before switching

```bash
node scripts/check_api_parity.mjs        # diffs functions/_lib.js output vs site/data/reference/*.json
```

Expected: **all checks passed**, with a note that 36 event *keys* change
(the audited table carries clean display names — "San Fernando" instead of
"1971 SanFernando USA"). The key is only an internal Map id in `app.js`; no
deep links use it. Per-station numbers may also drift slightly because the
audited workbook carries USGS hypocentres rather than the old NGA ones.

## One-time Cloudflare setup

```bash
npm install -g wrangler
wrangler login

# 1. create the database, paste the printed database_id into wrangler.toml
wrangler d1 create pulse_db

# 2. apply the schema
wrangler d1 migrations apply pulse_db --remote      # drop --remote for local

# 3. load the data
wrangler d1 execute pulse_db --file=db/seed.sql --remote
wrangler d1 execute pulse_db --remote --command \
  "SELECT catalog_id, count(*) FROM pulse_records WHERE catalog_id IS NOT NULL GROUP BY catalog_id"
# expect: shahi_baker_2014|243  taiwan_ncree|340  yen_2022|84
```

## Deploy

The repo already builds as a static site; Functions ship automatically.

* **Pages → Connect to Git**: build command *none*, output directory `site`,
  root `/`. `wrangler.toml` binds D1 as `DB` and sets `pages_build_output_dir`.
* Or from the CLI: `wrangler pages deploy site`.

The static `site/data/reference/*.json` stays in the repo as a fallback, so the
site keeps working on plain GitHub Pages. Point the frontend at D1 with either:

```html
<!-- site/index.html, before app.js -->
<script>window.PULSE_REF_API = "/api";</script>
```

or, ad hoc, `…/index.html?refapi=/api`.

## Refresh workflow

1. update `references/tables/pulse_table_audited.xlsx`
2. `python scripts/load_workbook.py`
3. `node scripts/check_api_parity.mjs`
4. `wrangler d1 execute pulse_db --file=db/seed.sql --remote`

`seed.sql` begins with `DELETE FROM …` for every table, so re-running it is a
full replace, not an append.

## Not yet in the skeleton

* `fault.trace` for the 9 finite-fault events is a straight along-strike line
  through the hypocentre (segment-1 strike, summed length), not the USGS
  slip-model footprint the old importer drew. The segment geometry is in
  `fault_segments`; projecting a real trace is a follow-up.
* The `Baker_moderate`, `Tf_Kamai(2014)`, and `Yen_*_fling(2023)` sheets load
  into `pulse_records` with `catalog_id = NULL` (stored, not shown). Give them
  ids in `CATALOG_MAP` / `CATALOGS` in `scripts/load_workbook.py` to surface
  them.
* Pipeline events stay static JSON; only move them to D1 if the read path there
  needs to be dynamic too.
