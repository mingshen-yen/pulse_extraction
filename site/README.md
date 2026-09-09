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
python ../scripts/import_reference_tables.py                 # rebuild data/reference/ from the master table
```

`import_reference_tables.py` builds three published catalogs from the single
consolidated table `references/tables/pulse_records_with_coords.csv` (which
already carries a resolved coordinate per record):

* **Shahi & Baker (2014)** — `Baker(2014)` sheet, 243 records, 241 mapped, with
  fault-normal-pulse flags; each record links to its jackwbaker.com page.
* **NCREE Taiwan** — 340 records, all mapped, with event hypocentres.
* **Yen et al. (2022)** — 84 near-fault pulse records, 83 mapped.

Each event also gets a **source model** from USGS ComCat: moment-tensor /
focal-mechanism nodal planes and, where a finite-fault inversion exists, its
geometry — used to draw the rupture polygon (solid = inversion, dashed =
magnitude-scaled). USGS responses cache to `site/data/reference/_cache/`
(git-ignored); `--no-net` reuses them. The generated `site/data/reference/*.json`
is committed; each catalog carries its citation.

Each event: fetch strong-motion waveforms (GeoNet FDSN / ESM) → `run_pulse`
(Kamai baseline correction · Arias 5–95 % window · 50 Hz) → one `data/events/*.json`.
Event parameters and a schematic rupture rectangle (moment-tensor nodal plane +
Wells & Coppersmith magnitude scaling) come from USGS where available.

## View locally

```bash
python -m http.server -d site 8000   # then open http://localhost:8000
```

(Needs to be served over http — `file://` blocks the `fetch()` calls.)

## Deploy

`.github/workflows/pages.yml` publishes `site/` to GitHub Pages on push to
`main`. `.github/workflows/site-data.yml` runs `--poll` every 6 h and commits new
event JSON. Enable Pages (Settings → Pages → Source: GitHub Actions) once.
