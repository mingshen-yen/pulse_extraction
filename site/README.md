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

## Deploy

The site is hosted on Cloudflare Pages (project `pulse-extraction`).
`.github/workflows/deploy.yml` uploads `site/` on every push to `main` that
touches `site/**`, and `.github/workflows/site-data.yml` runs `--poll` every
6 h, commits new event JSON and then calls the deploy workflow. Both need the
repo secret `CLOUDFLARE_API_TOKEN` (Account → Cloudflare Pages → Edit) and the
repo variable `CLOUDFLARE_ACCOUNT_ID`.

Manual deploy:

```bash
wrangler pages deploy site --project-name pulse-extraction --branch feat/showcase-site
```
