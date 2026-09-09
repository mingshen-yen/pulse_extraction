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
    reference/<catalog>.json      NCREE / Shahi & Baker 2014 / Yen 2022 / Türkiye 2023
```

The "Data source" selector on the page switches between the pipeline results and
each published catalog; events that appear in more than one are cross-linked.

## Build the data

```bash
pip install -r ../requirements.txt
python ../scripts/build_site_data.py --curated          # rebuild the 6 curated events
python ../scripts/build_site_data.py --event 2010_darfield   # just one
python ../scripts/build_site_data.py --poll --min-mag 5.8    # append new live events (USGS)
python ../scripts/import_reference_tables.py                 # rebuild data/reference/ from data/reference/*.csv
```

`import_reference_tables.py` reads the published pulse tables in
`../data/reference/*.csv` (git-ignored, local) and writes the catalog JSON.
Run it locally when those tables change; the generated `site/data/reference/`
JSON is committed. Each catalog carries its citation and is shown on the page.

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
