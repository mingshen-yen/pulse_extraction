# Pulse Classification — Python port

Python re-implementation of the MATLAB near-fault velocity-pulse classifier in
`../classification_matlab/` (Shahi & Baker stratified wavelet algorithm).

The `waveform/` package adds the front end: raw 3-component acceleration →
StationXML resolution → QC gate → baseline correction → the classifier, so a
record goes straight from a MiniSEED file or an FDSN data centre to a pulse
verdict. See [waveform/README](waveform/README.md).

**`waveform/` is the entry point for new work.** `pulse_classification/` keeps
its own file-based tooling (`preprocess.py`, `parse.py`, `main.py`) for
reproducing the original MATLAB results; for anything new, feed acceleration
through `waveform.run_pulse` / `run_pulse_variants`, or run only the classifier
on a corrected velocity pair with `waveform.classify_velocity(vel_n, vel_e, dt)`.

## Layout

| Python | replaces MATLAB | notes |
|---|---|---|
| `pulse_classification/matlab_wavelets.py` | `cwt` / `intwave` / `scal2frq` / `centfrq` | old-style CWT driven by a **discrete** wavelet (`db4`); `pywt.cwt` cannot do this, so MATLAB's convolve-the-integrated-wavelet-then-differentiate algorithm is reproduced directly |
| `pulse_classification/parse.py` | `parse_segment.m` | `parse_segment` keeps the hard-coded `dt = 0.01`; `parse_asc` added to rebuild the `*_VEL_N.txt` inputs from ESM `.ASC` files |
| `pulse_classification/preprocess.py` | `parseAT2/CWB/JP/iceland.m`, `parse_ASC.m`, `convert_dis_vel_acc.m` | raw record → `*_VEL_[NE].txt`: format readers, unit conversion, de-trend/taper, Butterworth band-pass, `acc↔vel↔dis`, resampling |
| `pulse_classification/analyze_record.py` | `analyze_record.m` (+ nested `fn_extract_one_wavelet`) | |
| `pulse_classification/classification_algo.py` | `classification_algo.m` / `cont_wavelet_trans.m` | |
| `pulse_classification/plotting.py` | `make_plot.m` | matplotlib |
| `pulse_classification/main.py` | `classify_record_main.m` | CLI driver |

## Run

```bash
pip install numpy scipy PyWavelets pandas matplotlib      # + obspy only for miniSEED
```

### 1. Pre-process raw records → `*_VEL_[NE].txt` (optional)

Skip this if you already have single-column velocity (cm/s) files.

```bash
python -m pulse_classification.preprocess \
    --stations stations.txt --in-dir RAW --out-dir TXT \
    --pattern-n '{sta}_ACC_N.txt' --pattern-e '{sta}_ACC_E.txt' \
    --in-kind acc --dt 0.01 \
    --detrend linear --fmin 0.02          # band-pass / taper / --target-dt optional
```

`--pattern-*` may contain `{sta}` and shell globs (e.g.
`'TK.{sta}..HNN.*.ASC'`). Format is taken from the extension: `.AT2` (PEER,
g-acc), `.ASC` (ESM, unit + `dt` from header), `.mseed` (ObsPy), anything else
is plain text and needs `--dt`. With every optional flag off, the acc→vel step
is exactly MATLAB `cumtrapz` (and dis→vel is `gradient`).

### 2. Classify

```bash
python -m pulse_classification.main \
    --data TXT --stations stations.txt \
    --figures Results/Figures --out Results \
    [--dt 0.01] [--limit N]
```

Inputs per station `S`: `S_VEL_N.txt`, `S_VEL_E.txt` (one velocity sample per
line, cm/s). Outputs: `S_j_rotated.txt`, `S_j_pulseth.txt`, `S_j_pulse.png` for
each pulse-like component, plus a combined `pulseData.csv`.

## Test / validate with your own data

`pytest` runs anywhere on the committed fixtures in `tests/fixtures/`. For batch
validation against the EarthScope 2023 Türkiye pulse table, drop the records in
`data/records/2023_turkey/` and the CSV in `data/reference/` (both git-ignored)
and run `tests/historical_2023_turkey.py`, `tests/compare_methods.py`,
`tests/compare_corrected_acc.py`. Layout and filename convention:
[data/README.md](data/README.md).

## Validation (classifier port)

`tests/validate.py` regenerated the `TK.3123` / `TK.2712` inputs from the ESM
`.ASC` files and compared against `classification_matlab/Results/2023_Turkey/`.
It is kept as an **offline record** — it needs the original MATLAB data/results
tree and is not runnable inside this stand-alone repo. `tests/test_matlab_wavelets.py`
runs anywhere. Measured agreement:

| quantity | agreement |
|---|---|
| rotation angle `max_Dir`, `Tp`, `PGV` | exact (rel ≤ 1e-13) |
| rotated waveform `*_rotated.txt` | rel L2 ≈ 2e-8 |
| `PC` | rel ≤ 1.4e-3 |
| `pulse_indicator` | rel ≤ 6e-3 (abs ≤ 0.1); larger *relative* error only when the value is itself near 0 |
| `is_pulse`, `late` decisions | identical on all tested pulses |
| extracted pulse `*_pulseth.txt` | rel L2 ≈ 0.5–2 % |

The residual ~1 % on the reconstructed pulse comes from small differences
between `pywt` and MATLAB in the sampled wavelet function `wavefun('db4', 4)`
and the single-level `dwt`; it does not change any classification outcome in the
reference set.

## Behavioural differences from the MATLAB (intentional fixes)

- **`classify_record_main.m`** hard-codes `for i = 1:2` and uses `return`
  (aborts the whole script) on a bad record. The port iterates the full station
  list and `continue`s past bad records, filling their rows with `-999`.
- **`parse_segment.m`** leaves `dt` unset when the file is missing (assigns to a
  stray `record_dt`); the port always returns a valid `Segment` with
  `err_code = -1`.
- **`pulseData.csv` header** in the MATLAB is mislabelled — `writetable` pairs
  `{'Ipulse','late','PI','PC'}` with the columns
  `pulse_indicator, PC, is_pulse, late`. The port writes correct column names.
- `find(z == max(z))` (can return several indices, then breaks `scales(row)`)
  → `np.argmax` (first max).
- `--dt` flag exposes the true sampling interval instead of the fixed `0.01`.

## Known upstream fragilities left as-is (not bugs in the port)

- `analyze_record` reuses `col` as both a scalar and a growing vector, and grows
  `coefs` dynamically; the port pre-allocates but follows the same logic.
- `fn_extract_one_wavelet` matches the windowed max against the **whole** CWT
  row, so a duplicate max outside the search window would mislocate the wavelet.
- `late` is computed but never used in `is_pulse` (`% & ~late` is commented out).
