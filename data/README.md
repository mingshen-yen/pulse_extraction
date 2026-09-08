# `data/` — local input data (git-ignored)

Everything under `records/`, `reference/` and `stationxml/` is **git-ignored**
(only the `.gitignore` files are tracked). Put your own waveforms / reference
tables here; nothing large or third-party is committed.

```
data/
├── records/              3-component acceleration to process / validate
│   └── <event>/            e.g. 2023_turkey/
│       TK.NAR..HNE.<evid>.ACC.CV.mseed
│       TK.NAR..HNN.<evid>.ACC.CV.mseed
│       TK.NAR..HNZ.<evid>.ACC.CV.mseed
│       ...
├── reference/            ground-truth tables the validation scripts compare to
│       ES_published_pulse_table.csv
└── stationxml/           instrument-response cache (auto-written by fetch)
        <net>.<sta>.xml
```

## Filename convention (what the validation scripts expect)

```
<NET>.<STA>..<CHA><E|N|Z>.<EVID>.ACC.CV.mseed
```

* `NET` — `TK`, `KO`, … (network code)
* `CHA` — 2-letter band/instrument code, e.g. `HN` (strong-motion accel)
* `EVID` — event id string, e.g. `INT-20230206_0000008`; same for all channels
* units — acceleration in **cm/s²** (gal). Raw counts also work if a StationXML
  is available (`data/stationxml/`, `--stationxml`, or FDSN).

Any ObsPy-readable format works for ad-hoc runs; the fixed name above is only
needed for the batch validation scripts that iterate a station list.

## Running

### One record (any location, any name)

```bash
python -m waveform.run_record --sta NAR \
    --mseed data/records/2023_turkey/TK.NAR..HN{E,N,Z}.INT-20230206_0000008.ACC.CV.mseed \
    --out out/NAR
```

Writes `out/NAR/NAR_VEL_{N,E}_{basc,frm}.txt`, `NAR_pulse_{basc,frm}.json`,
`NAR_qc.json`.

### Batch validation vs the EarthScope published table

Put the records in `data/records/2023_turkey/` and the CSV at
`data/reference/ES_published_pulse_table.csv`, then:

```bash
python tests/historical_2023_turkey.py            # per-station Tp/PGV/PI vs ES
python tests/compare_methods.py --quick           # Kamai vs eBASCO accuracy+stability
python tests/compare_corrected_acc.py --reps 8    # corrected-acceleration stability
```

Each script also takes `--mseed <dir>` / `--es <csv>` to point elsewhere.

### Small fixtures for `pytest`

`tests/fixtures/` holds the committed TK.NAR record + golden arrays used by
`pytest`. Add only small files there.
