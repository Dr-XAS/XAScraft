# Baseline match (check 1)

Runs a fixed list of scenarios through the backend's public HTTP API on two trees (the
baseline and the refactored build) and compares the JSON responses exactly. Only the
fields declared below may differ.

## Use

Run each tree with its own backend venv; the runner imports that tree's backend.

```sh
# capture (one normalized JSON file per scenario, plus _run.txt describing the run)
<tree>/backend/.venv/bin/python scripts/refactor-checks/baseline_match/run.py \
    --backend <tree>/backend --out <capture dir> [--only NAME ...]
python scripts/refactor-checks/baseline_match/run.py --list      # scenario names

# compare: prints every differing path, exits 1 if there is any
python scripts/refactor-checks/baseline_match/compare.py <capture A> <capture B>
```

- Each scenario gets a fresh scratch data root and a `TestClient(create_app(Settings(data_root=…)))`.
  `XRAYLARCH_DATA_ROOT` is pointed at scratch before `xraylarch_web.main` is imported, so the
  import-time app never touches a real data root. Nothing external is configured.
- The runner sets `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`,
  `VECLIB_MAXIMUM_THREADS` and `XRAYLARCH_XRF_WORKERS` to 1 before numpy loads.
- Input files (the bundled `.prj` projects) are read from the `examples/` folder next to the
  harness, so both trees get identical inputs.
- A step a scenario depends on that fails stops that scenario; the failure is part of the
  capture (`error`), so it compares like any other response.
- A full run takes about 70 s and writes about 450 MB.
- Tests: `backend/.venv/bin/python -m pytest scripts/refactor-checks/baseline_match/tests`.

## What is recorded

For every HTTP call: the step name, method and URL, status, `content-type`,
`content-disposition` (if any) and the body.

- JSON bodies are recorded as parsed JSON.
- gzip bodies (`.prj` exports) are decompressed first (`"gzip": true`); the gzip header and
  its mtime are not compared.
- Other text bodies (CSV exports, `.prj` text) are recorded as a list of lines. A line that
  carries a JSON object, such as `.prj`'s `# Athena-Web {...}` header, is recorded as
  `{"prefix", "json"}` so the masks below apply inside it.
- Floats are written with `repr` precision (Python's `json`), never rounded. The comparison
  is exact: a float differs if its `repr` differs, and `1` differs from `1.0`.

## Normalization (declared up front, in `normalize.py`)

Renumbered, consistently within one scenario, in order of first appearance:

- **Random ids** (`secrets.token_urlsafe(18)`, 24 url-safe characters, and `uuid4().hex`).
  An id is found in an id field: the value of `id`, `parent`, `*_id` or `*Id`; the items of
  `parents`, `*_ids` or `*Ids`; the keys of `group_versions` and `group_added_orders`. Once
  found it becomes `ID#n` wherever it appears: as a value, as a dict key, or inside longer
  text (file names, messages, URLs). Strings of the same shape elsewhere (snake_case names,
  data labels) are kept.

Masked:

- **Timestamps minted by the run**: ISO 8601 date-times (`T` or space separator) dated on a
  day the scenario ran, in values and inside text, become `<timestamp>`. Dates carried in
  the data (e.g. an XDI scan time) are kept.
- **`larch_version`**: the running Larch's version string, wherever it appears, becomes
  `<larch_version>`.
- **`input_sha256` and `current_input_sha256`** (they hash the Larch version with k and chi)
  become `<input_sha256>`.
- **A fit's `metadata.seconds`** (wall-clock timings) becomes `<seconds>`.

Nothing else is masked.

## Scenarios (`scenarios.py`, run in this order)

| Name | What it does |
|---|---|
| `copper-examples` | Load the copper examples; open the project; export every group in E, k, R and q; export the project as json and prj |
| `cuprite-4-path-fit` | Copper examples; get the Cu₂O example model; fit it on the Cu₂O spectrum (full and summary views) |
| `curated-demo` | Load the curated demo (`curated-three-elements`); open; export as json |
| `reference-library-lcf` | Import `AsKa.prj`; `lcf_suggest` on the unknown; add the suggested library standards; `lcf_search`; `lcf` |
| `operation--merge` | Copper examples; merge preview and merge of the three foils (`demeter-larch`, mu) |
| `operation--sum` | Sum of two foils with weights 1 and 0.5 (no preview in the UI) |
| `operation--difference` | Difference preview and difference of the 300 K foil against the 10 K foil (norm) |
| `operation--align` | Foils detached from the shared reference; alignment preview and align of 50 K and 300 K to 10 K |
| `operation--calibrate` | Calibration preview and calibrate (observed 8980, target 8982) |
| `operation--rebin` | Rebin preview and rebin |
| `operation--deglitch` | Point-edit preview and deglitch (9100–9110 eV) |
| `operation--truncate` | Point-edit preview and truncate (8800–11000 eV) |
| `operation--smooth` | Smoothing preview and smooth (Savitzky–Golay, window 7, order 2) |
| `operation--convolve` | Convolution preview and convolve (Gaussian, 1 eV) |
| `operation--deconvolve` | Deconvolve (Gaussian, 1 eV, 8950–9100 eV; no preview route) |
| `operation--self-absorption` | Self-absorption preview and correction (Cu, 45°/45°) |
| `operation--mee-removal` | MEE preview and multi-electron removal (arctangent) |
| `analysis--lcf` | LCF of the 300 K foil against the 10 K foil and Cu₂O |
| `analysis--pca` | PCA of the five copper spectra |
| `analysis--peak-fit` | Peak fit on Cu₂O: a Gaussian and a Lorentzian on an arctangent step |
| `analysis--log-ratio` | Common transform parameters on two foils, then log-ratio |
| `project-open-vs-import` | Copper examples with a merge, an LCF report and a saved Cu₂O fit; export json and prj; **open**: restart the app on the same data root, list and open the project; **import**: the json via `restore` and the prj via `preview-project` + `restore-upload` into new projects, and the prj into the project itself |
| `fit-history` | Save a model; save fits at kmax 12 and 10 (`fit-saved`) and one through `fits`; list; read both fits in full (what the comparison view reads) and as summaries; remove one; list; export as prj and import it, then list the imported fits |
| `artemis-path-preview` | Inspect `examples/feffit/feffcu01.dat`; path preview of it at the example values, at perturbed values, at k weight 3 to kmax 20, and twice (the same FEFF content with its own S0² and σ² each); the Cu₂O example's 4 paths at its values, at perturbed values and at k weight 1 |
| `artemis-theory-simulation` | Attach AMCSD 15851 (Cu₂O) to a new project; run FEFF on it (Cu site 1, cluster 5 Å, paths 4 Å; the start and the polls are not recorded, since the job record carries wall-clock times and a process id); simulate every path, with Debye disorder at k weight 3, and the first two paths at k weight 1; add the simulation to the project; replay the saved theory at its own k weight and at 1 |
| `bundled-project--<path>` | One per `.prj` under `examples/` (82, the corpus `test_athena_prj_compatibility.py` uses): preview, preview the first group normalized, import every group, restart the app and open the project. `danger.prj` is refused at preview, by design |
