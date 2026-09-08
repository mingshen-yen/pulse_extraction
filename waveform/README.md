# `waveform/` — record → corrected velocity → pulse verdict

Bridges `00_BASC_Fling_rm/BASC/` (baseline correction) to
`pulse_classification/` (Shahi & Baker wavelet pulse extraction).

```
fetch.py      MiniSEED / FDSN
response.py     └─ resolve_response(): file → cache → FDSN → other-epoch → routed
                   → nominal sensitivity → assumed-physical → (else fail)
   │          instrument-response removal  →  acceleration [cm/s²]
   │
qc.py         check_record(): response provenance / finite / sampling / duration /
              dead / clipping / spikes / units / event-present  →  pass|warn|fail
   │
basc.py       Kamai path:  detrend_poly(6) → taper → baseline_ka → (opt) flingstep_rm
ebasco.py     eBASCO path: pre/strong/post-event trilinear detrend  (keeps permanent disp)
   │
classify.py   classify_velocity(vel_n, vel_e, dt) → the pulse dict  (standalone;
              the single PulseData→dict contract)
pipeline.py   acc_to_velocity(method=…) → classify_velocity → JSON-friendly dict
```

`waveform/` is the entry point for new work. The legacy file-based tooling
(`pulse_classification/{preprocess.py, parse.py, main.py}`, MATLAB-parity) is
kept for reproducing the original results only.

To run **just the classifier** on an already-corrected velocity pair (no fetch /
QC / baseline correction), call `waveform.classify_velocity(vel_n, vel_e, dt)` —
it returns `{dt, npts, pulses[…], any_pulse}`, the same `pulses` schema
`run_pulse` embeds. `include_waveforms=False` drops the three per-pulse arrays.

## Missing StationXML (`response.py`)

`resolve_response()` tries, in order, and tags the result so downstream knows
how much to trust the amplitudes:

| source | how | level |
|--------|-----|-------|
| `file` | caller's StationXML | ok |
| `cache` | `data/stationxml/<net>.<sta>.xml` from a past run | ok |
| `fdsn` | primary FDSN client, response for the time window (cached on success) | ok |
| `fdsn-other-epoch` | same client, response for *any* epoch | warn |
| `fdsn-routed` | IRIS federator / EIDA routing / `IRIS,ORFEUS,GFZ,RESIF` | warn |
| `nominal` | caller-supplied scalar sensitivity (counts per m/s²), flat deconvolution | warn |
| `assumed-physical` | no response, but sample amplitudes look like gal / m/s² → pass through | warn |
| `none` | data looks like raw counts and nothing resolved | **fail** (QC gates it) |

`fetch.read_three_component(paths, stationxml=…, client=…, routing=…,
nominal_sensitivity=…)` and `fetch_event_acc(…)` return `ThreeComponentAcc`
whose `.meta["response"]` carries the source + messages; pass that to
`check_record(..., response=…)` / `run_pulse(..., response=…)` and it folds into
the QC verdict. `run_record` flags `--stationxml`, `--nominal-sensitivity`,
`--routing` / `--no-routing`.

## QC gate

`run_pulse(..., qc="gate")` (the default) runs `qc.check_record` first and
raises `QCError` if the record **fails**; `qc="attach"` runs it without gating,
`qc="off"` skips. The result is at `out["qc"]`. `run_record` writes `S_qc.json`
and, in `--qc gate`, aborts before processing a failing record.

| level | examples | pipeline behaviour |
|-------|----------|--------------------|
| `fail` | non-finite samples, dead channel, >1 % clipped, PGA ≳ 8 g (wrong units), < 20 s | gated out |
| `warn` | 20–40 s, mild clipping, spike-like samples, PGA > 1.5 g, energy not concentrated (possible noise), Arias-5 % onset < 2 s | processed, output flagged |
| `pass` | — | processed |

On the 23-station 2023 Türkiye set: 20 pass, 3 warn, 0 fail. Thresholds are all
in `QCThresholds` (`check_record(..., thresholds=QCThresholds(...))`).

## Quick use

```python
from waveform.fetch import read_three_component
from waveform.pipeline import run_pulse

acc = read_three_component(
    ["TK.NAR..HNE….mseed", "TK.NAR..HNN….mseed", "TK.NAR..HNZ….mseed"],
    stationxml=None,            # give a StationXML to deconvolve raw counts
)
out = run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt, method="kamai")
print(out["any_pulse"], out["pulses"][0]["Tp"], out["pulses"][0]["PGV"])
```

`out` is `{method, dt, npts, fling_removed, fling_params, vel_n, vel_e,
pulses[…], any_pulse, qc, ebasco?}`.  `run_pulse_variants(...)` returns the same
block twice under `out["variants"]["basc"]` (fling retained) and
`out["variants"]["fling_removed"]`, with `qc` / `fling_params` / `method` /
`dt` at the top.

Near-real-time from a data centre:

```python
from waveform.fetch import fetch_event_acc
acc = fetch_event_acc("TK", "NAR", "2023-02-06T01:17:36", channel="HN?", client="IRIS")
out = run_pulse(acc.acc_e, acc.acc_n, acc.acc_z, acc.dt, method="ebasco")
```

## Baseline-correction methods

| `method`   | source | notes |
|------------|--------|-------|
| `"kamai"`  | `BASC_poly.ipynb` chain | `obspy detrend('polynomial', order=6)` → `funclib.baseline_KA`. Deterministic. `remove_fling=True` subtracts a Kamai (2014) fling step (`fling_params` hand-set, or auto-estimated from the displacement). |
| `"ebasco"` | `eBASCO_FRM.ipynb` + `funclib_eBASCO.py` (vendored verbatim as `_ebasco.py`) | Samples T1/T3 from the Arias intensity, sweeps T1×T3×T2, keeps solutions within `eps` of the raw acceleration at T1/T2, picks the flattest displacement tail. Preserves permanent displacement. Heavier (~300 inner iterations). |

**Recommended method: `"kamai"`.** On the 2023 Türkiye M7.8 set it reproduces
the EarthScope published pulse table more closely than the eBASCO port
(median |ΔTp| 0.13 s vs 0.45, |ΔPGV| 2 vs 7 cm/s), never fails (eBASCO: 3–5 / 23),
and the corrected acceleration is ~40× less noise-sensitive and invariant to the
start window. Use `"ebasco"` only when the permanent (fling) displacement itself
matters. See `tests/compare_methods.py` / `tests/compare_corrected_acc.py`.

### Fling-retained vs fling-removed pair (`run_pulse_variants`)

Plain `baseline_ka` always kills the permanent displacement, so to get a
genuine "with fling / without fling" pair the fit carries an explicit,
separable fling term (`basc.kamai_fling_decompose`): the displacement is fitted
to `p2 t² + … + p6 t⁶ + Dsite·unit_fling(t; t1, Tf)`, then

* `basc`          — subtract only the polynomial → **permanent displacement kept**
* `fling_removed` — subtract polynomial + fling term → permanent displacement ≈ 0

…returned under `out["variants"]["basc"]` and `out["variants"]["fling_removed"]`.

`t1` auto-defaults to the Arias-5 % onset and `Tf` to 2 s, with `Dsite` from the
fit; pass `fling_params={"t1":…, "Tf":…, "Dsite":…}` to pin them (the original
`BASC_poly.py` hand-tuned all three). The `waveform.run_record` CLI writes both
variants as `S_VEL_{N,E}_basc.txt` / `_frm.txt` plus `S_pulse_{basc,frm}.json`.

## Deviations from the original (intentional)

- `funclib.detrend` is only ever called by `BASC_poly.py` (not the notebook), and
  there with its arguments swapped (`detrend(wave, time)` regresses *time* on
  *acceleration*). The Kamai path uses ObsPy's polynomial detrend instead, as
  `BASC_poly.ipynb` does.
- `FlingStep_rm` hard-coded `t1 / Tf / Dsite` in its body; `basc.flingstep_rm`
  actually uses the arguments.
- `basc.*` copy their inputs; the originals mutate in place.
- eBASCO is vendored unmodified. The original integrates in float32 (mseed
  dtype); `ebasco.py` works in float64, so results match the reference to
  ~1e-4 relative — same T1/T2/T3 solution, same permanent displacement.

Tests: `python -m pytest tests/test_basc.py` (golden arrays from the original
code on TK.NAR, 2023 Türkiye M7.8).
