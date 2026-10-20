# Larch patch queue

XAScraft runs upstream [xraylarch](https://github.com/xraypy/xraylarch) at a pinned commit
plus the patches in this folder. Nothing else in the repository changes Larch.

| Path | What it is |
| --- | --- |
| `PIN` | The upstream URL and commit, the upstream version string at that commit, and the `larch/` tree and `pyproject.toml` blob that applying the series must give. |
| `series/NNNN-*.patch` | `git format-patch` files, applied in order with `git am`. Each keeps its author, date and message. The team patches come first; each carries an `XAScraft-commit: <sha>` trailer naming the XAScraft commit it came from. The [temporary patches](#patches) after them come from no XAScraft commit and carry no trailer. |
| `build.py` | Builds the patched Larch: source tree, wheel, sdist and `IDENTITY`. See [Building](#building). |
| `installed.py` | Checks that the Larch an interpreter imports is the patched build (version, distribution, site-packages); `install-dev.sh`, the deploy script and the backend tests use it. |
| `run-upstream-tests.sh` | Runs upstream's own test suite, from a built source tree, against the installed Larch. See [Running the tests](#running-the-tests). |
| `tests/test_series.py` | Applies the series to the pin in a scratch clone and checks the result against `PIN` and the original commits. |
| `tests/test_build.py` | Runs `build.py` and checks its output, its version and its failure modes. |
| `tests/test_installed.py` | Runs `installed.py` against the installed build, another version and a source-tree `larch/`. |
| `tests/test_upstream_suite.py` | Runs `run-upstream-tests.sh` on a built tree: the main run, and the known pre-existing failures. |
| `tests/test_*.py` (others) | The team's Larch regression tests. They run against whatever Larch is installed. |

## Building

```sh
python3 larch-patches/build.py --out build/larch                      # fetches the pin from GitHub
python3 larch-patches/build.py --out build/larch --upstream ~/xraylarch  # or reads a local clone
```

`build.py` needs Python 3.12 and git, nothing else. It checks out upstream at the pin (a
one-commit fetch, or `git clone --shared` of a local clone, which is only read), applies the
series with `git am --committer-date-is-author-date` and a fixed committer, and writes, all or
nothing, into `--out` (which must be absent or empty):

| Output | What it is |
| --- | --- |
| `xraylarch-src/` | The patched upstream tree, without `.git` and without a generated `larch/_version.py`. Installing from it needs `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_XRAYLARCH` set to the version in `IDENTITY`. |
| `dist/` | `xraylarch-<version>-py3-none-any.whl` and `xraylarch-<version>.tar.gz`. |
| `IDENTITY` | JSON: `pin`, `upstream_version`, `patch_set_id`, `version`, `pure_upstream`, `patches` (number, file, `xascraft_commit`: the patch's trailer, or `null` for a temporary patch), `excluded`, `larch_tree`. |

- **Version**: `<upstream-version from PIN>.xascraft.<patch-set id>`. The patch-set id is the
  first 12 hex digits of the sha256 of the applied patch files' bytes, in order
  (`cat series/*.patch | sha256sum`). It changes only when the pin or a patch file changes; a
  reworded message counts. To print the version the current pin and series give, without
  building: `python3 -I -c 'import sys; sys.path.insert(0, "larch-patches"); import build; print(build.expected_version())'`.
- **Per-patch builds** (for the per-patch report, `scripts/refactor-checks/per_patch/`): `--exclude 0003` (repeatable) leaves patches out
  and marks the version, e.g. `….xascraft.<id of the rest>.without0003`. `--pure-upstream` applies
  nothing and gives upstream's own version, `2026.3.1.post78+g247278cef`.
- **Stops** with a non-zero exit, and writes nothing, when a patch does not apply, when the full
  series gives another `larch/` tree than `patched-larch-tree` in `PIN`, or when setuptools would
  change the version string.
- **Build backend**: by default a fresh venv with `setuptools`, `wheel` and `setuptools-scm` at the
  versions pinned in `deploy/python-release-constraints.txt` (needs PyPI or a pip cache).
  `--build-python PYTHON` uses an interpreter that already has them, e.g. a venv made from the
  release constraints; this is what the tests and offline builds use.
- **Reproducible**: two builds from the same inputs give the same tree, `IDENTITY`, wheel and
  sdist, byte for byte. File times come from the last applied commit (`SOURCE_DATE_EPOCH`).
  setuptools does not make the sdist reproducible by itself (build-time stamps on the generated
  files, the builder's uid and gid, the gzip time), so `build.py` rewrites it with those fixed.

## Installing for development

The backend's environment gets Larch from this build; the repository holds no Larch source,
and `backend/requirements.txt` does not install Larch. From the repository root:

```sh
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r deploy/python-release-constraints.txt -c deploy/python-release-constraints.txt
larch-patches/install-dev.sh --upstream ~/xraylarch       # omit --upstream to fetch the pin from GitHub
(cd backend && .venv/bin/pip install -r requirements.txt -c ../deploy/python-release-constraints.txt)
```

`install-dev.sh` runs `build.py` with the venv's interpreter as the build backend, installs the
wheel under the release constraints (replacing any Larch already installed, an editable one
included), and checks with `installed.py` that `import larch` gives IDENTITY's version from
site-packages. `python -I larch-patches/installed.py` makes the same check in any environment
against the build of the current pin and series.
`--python PYTHON` installs into another environment; `--keep DIR` keeps the build output.
Run it again after the pin or a patch changes: `backend/tests/test_larch_dependency.py` fails
while the installed Larch is not the current build.

## Running the tests

```sh
# Regression tests, against the Larch installed in the active environment (tests/conftest.py
# marks every file but the queue checks below `regression`):
pytest larch-patches/tests -m regression

# The series check. It needs git, this repository's history, and upstream:
XASCRAFT_LARCH_UPSTREAM=/path/to/local/xraylarch/clone pytest larch-patches/tests/test_series.py

# The build script (about 1.5 minutes; the test interpreter is the build backend, so it must
# have the pinned setuptools, wheel and setuptools-scm, as a release-constraints venv has):
XASCRAFT_LARCH_UPSTREAM=/path/to/local/xraylarch/clone pytest larch-patches/tests/test_build.py

# run-upstream-tests.sh, both modes (builds a tree first, like test_build.py; about 1 minute):
XASCRAFT_LARCH_UPSTREAM=/path/to/local/xraylarch/clone pytest larch-patches/tests/test_upstream_suite.py

# All three queue checks at once:
XASCRAFT_LARCH_UPSTREAM=/path/to/local/xraylarch/clone pytest larch-patches/tests -m "not regression"
```

```sh
# Upstream's own suite, from build.py's source tree, against the Larch installed in PYTHON's
# environment (runs in a scratch copy of the tree; about 10 seconds):
larch-patches/install-dev.sh --python PYTHON --keep build/larch
larch-patches/run-upstream-tests.sh build/larch/xraylarch-src --python PYTHON
# The known pre-existing failures (below) alone; succeeds while exactly those fail:
larch-patches/run-upstream-tests.sh build/larch/xraylarch-src --python PYTHON --known-failures
```

- The upstream suite runs the files upstream's `tests/run_tests.sh` names at the pin, plus
  `test_xrf_model.py`. Expected: 201 passed, 2 skipped (`test_plot_rixsdata_import.py` needs
  `wx`; `test_xafs_rebin.py`'s benchmark runs only with `LARCH_REBIN_TIMING=1`), 11 deselected.
- **Known pre-existing failures.** The 11 deselected tests are `test_larchexamples_xafs.py`
  scripts that call wx plotting commands (`plot_bkg`, `plot_chifit`, ...), which do not exist
  without wxPython; they fail the same way on plain upstream, and XAScraft's environments have
  no wxPython: `test02_autobk`, `test03_autobk2`, `test05_autobk_with_std`, `test07_xafsft1`,
  `test08_xafsft2`, `test09_xafsft3`, `test10_xafsft3`, `test13_feffit1`, `test15_feffit2`,
  `test16_feffit3`, `test18_feffit_save_fit_stale_paths` (`KNOWN_FAILURES` in
  `run-upstream-tests.sh`). They are recorded, not hidden: `--known-failures` runs only them,
  lists them, and succeeds while exactly they fail. It fails, naming the test, when one passes,
  errors, is skipped or does not run; then update `KNOWN_FAILURES` and this list.
- The CI workflow `.github/workflows/larch-patches.yml` runs all of the above: build from
  GitHub, the queue checks (`-m "not regression"`), the regression tests, the upstream suite,
  and, as its own step, the known pre-existing failures, so every run shows them (also as a
  warning annotation) without failing on them.
- The pytest session header names the Larch that was tested.
- `XASCRAFT_LARCH_UPSTREAM` takes a local clone path or a URL. Unset, the test fetches the
  pinned commit from the URL in `PIN`. A local clone is only read (`git clone --shared`).
- The FEFF tests read `examples/feffit/Feff_Cu` from this repository's `examples/` folder.
  `XASCRAFT_EXAMPLES_DIR` points them at another `examples/` copy.
- On the patched build, every regression item passes. On plain upstream at the pin
  (`build.py --pure-upstream`), every one fails: each tests a behavior a patch gives.

## Patches

| Patch | XAScraft commit | Author, date | Larch files | Ledger entries |
| --- | --- | --- | --- | --- |
| 0001 | `e47015166` | jhuang165, 2026-08-17 | `io/csvfiles.py` | [CSV reader](#3-csv-reader) |
| 0002 | `3ca0a9716` | jhuang165, 2026-08-18 | `pyproject.toml` | [Packaging: no `mkl_fft`](#packaging-no-mkl_fft) |
| 0003 | `ab60c3776` | Juanjuan Huang, 2026-09-10 | `xafs/xafsft.py`, `xafs/autobk.py` | [FT window names](#1-fourier-transform-window-names), [AUTOBK](#2-autobk) |
| 0004 | `cc099c125` | Xiangyu Yin, 2026-10-06 | `io/xafs_beamlines.py`, `io/xdi.py`, `xrf/xrf_model.py` | [Beamline labels](#4-beamline-column-labels), [XDI reader](#5-xdi-reader), [XRF model](#8-xrf-model) |
| 0005 | `b334e57f8` | Xiangyu Yin, 2026-10-12 | `xafs/autobk.py`, `xafs/estimate_noise.py`, `xafs/feffdat.py` | [AUTOBK](#2-autobk), [Noise estimate](#6-noise-estimate), [FEFF path data](#7-feff-path-data) |
| 0006 | `8d37ac358` | Xiangyu Yin, 2026-10-12 | `xafs/autobk.py`, `xafs/feffdat.py` | [AUTOBK](#2-autobk), [FEFF path data](#7-feff-path-data) |
| 0007 | `aee4bb5e6` | Xiangyu Yin, 2026-10-12 | `xafs/feffdat.py` | [FEFF path data](#7-feff-path-data) |
| 0008 | none (temporary) | XAScraft refactor, 2026-10-20 | `xafs/feffdat.py` | [FEFF path parameters (temporary)](#9-feff-path-parameters-temporary) |
| 0009 | none (temporary) | XAScraft refactor, 2026-10-20 | `xafs/fluo.py` | [Self-absorption E0 (temporary)](#10-self-absorption-e0-temporary) |

The patches also carry the team's changes to upstream test files: `tests/test_xafs_defects.py`
(0005 to 0007), `tests/test_xrf_model.py` and the APS 12-BM test in `tests/test_read_beamlinedata.py`
(0004), and the `tests/run_tests.sh` line that runs `test_xafs_defects.py` (0007).
The subjects of 0001 to 0004 describe mostly app work, because those commits also changed the app.
Their messages are kept as written; this ledger says what each patch does to Larch.

0001 to 0007 come from the team's commits, from the time XAScraft vendored Larch, and carry
their `XAScraft-commit` trailers. Every later patch comes from no XAScraft commit, so it has no
trailer. It is one of two kinds:

- A **team patch**: a fix the team wants in Larch for good, to be offered upstream. Like 0005 to
  0007, it may carry its regression test into upstream's `tests/`.
- A **temporary** patch (all of them so far: 0008 and 0009). It is written while tracking
  upstream, and either undoes an upstream bug or regression, or keeps an app result that upstream
  changed on purpose until the owner decides whether to adopt the change. Its subject starts
  with `Temporary:`; it changes only `larch/`; and its regression tests are in
  `larch-patches/tests/` only.

`tests/test_series.py` checks all of this, and that the table above matches the series.

## Ledger

Each entry gives: why the patch exists, its numeric effect, the test that covers it, and its
exit condition. "Gap" means no Larch-level test exists; the backend tests named next to it cover
the behavior only indirectly.

Every entry has the same exit condition: **upstream contains an equivalent fix**. The per-patch
report (`scripts/refactor-checks/per_patch/`) proves this: on the new pin, a build without the patch gives the same outputs as a build
with it, and the entry's covering test passes without the patch. Then the patch is retired (see
below). The exception is entry 10, which keeps an intentional upstream change out: it is
retired when **the owner adopts upstream's behavior**.

### 1. Fourier transform window names

- **Patch:** 0003 (`larch/xafs/xafsft.py`).
- **Why:** `ftwindow` rejects `bessel`, the legacy Ifeffit name for its Kaiser-Bessel window, as
  an invalid name, although its own window code still implements `bessel`. Athena projects
  store `bessel`, and the app needs it.
- **Numeric effect:** none. Without the patch, the call raises instead of returning a window.
- **Covering test:** gap. Indirectly: `backend/tests/test_athena_prj_compatibility.py`.
- **App needs it:** yes.

### 2. AUTOBK

- **Patches:** 0003, 0005, 0006 (`larch/xafs/autobk.py`).
- **Why:**
  - 0003: a singular fit covariance (`covar is None`) made `autobk` fail. Now the fitted
    spline is kept and `coefs_std` is `None`.
  - 0005: the endpoint clamps weighed chi in the raw units of mu, so the same absorption in
    other units gave another background. Now the clamps act on chi in edge-step units.
  - 0006: `delta_chi` was in the units of mu, but feffit takes it as dimensionless, like chi.
    Now it is in edge-step units.
- **Numeric effect:** none without clamps (round-off). With clamps, χ moves where the edge
  step differs from 1. Measured as k²χ relative RMS over k = 3–12 (per-patch report):
  the app's copper examples move by ≤1e-5 and the curated demo by ≤4e-4. On the 82 bundled
  Athena projects (clamp_hi 24) the median is 7e-4, the 90th percentile 0.11 and the maximum
  1.4; raw-count spectra move by 10–140%. The Cu₂O 4-path fit's parameters move by ≤3e-5
  relative. `delta_chi` is divided by the edge step, but no app output carries it.
- **Covering test:** `test_xafs_defects.py::test_autobk_chi_does_not_depend_on_the_units_of_mu`
  covers the clamps and `delta_chi`. Gap: the missing-covariance path (0003) has no test.
- **App needs it:** yes.

### 3. CSV reader

- **Patch:** 0001 (`larch/io/csvfiles.py`).
- **Why:** `read_csv` left its file open and read it in the platform's default encoding. Now it
  closes the file and reads it as UTF-8 (`sys.getdefaultencoding()`).
- **Numeric effect:** none.
- **Covering test:** gap. Indirectly: `backend/tests/test_athena_file_plugins.py` and the CSV
  tests in `backend/tests/test_parsing.py`.
- **App needs it:** yes.

### 4. Beamline column labels

- **Patch:** 0004 (`larch/io/xafs_beamlines.py`).
- **Why:** APS 12-BM headers write labels as `N_name`. A name containing `_` (`5_I0_corr`)
  made the read fail. A label written without its number was dropped, which shifted every
  later label one column to the left.
- **Numeric effect:** none. Columns get their correct labels.
- **Covering test:**
  `test_read_beamlinedata.py::test_aps12bm_label_with_two_underscores_or_no_number_keeps_its_column`.
- **App needs it:** yes.

### 5. XDI reader

- **Patch:** 0004 (`larch/io/xdi.py`).
- **Why:** a `Mono.d_spacing` value that carries a unit (`3.1356369 Ang`) failed to parse. The
  angle-to-energy conversion already assumes such values.
- **Numeric effect:** none. Files that failed to load now load.
- **Covering test:** gap. Indirectly: `backend/tests/test_athena_angle_files.py` and
  `backend/tests/test_beamline_examples.py`.
- **App needs it:** yes.

### 6. Noise estimate

- **Patch:** 0005 (`larch/xafs/estimate_noise.py`).
- **Why:** `estimate_noise` passed its window as `kwindow=`, a keyword the transform ignores,
  so it always used the default Kaiser window.
- **Numeric effect:** only for non-Kaiser windows.
- **Covering test:** `test_xafs_defects.py::test_estimate_noise_uses_the_window_it_is_given`.
- **App needs it:** no. The app never reaches this code.

### 7. FEFF path data

- **Patches:** 0005, 0006, 0007 (`larch/xafs/feffdat.py`).
- **Why:** lmfit copies Parameters into a new interpreter, but the σ² procedures
  (`sigma2_debye`, `sigma2_eins`, user-defined ones) stayed bound to the old one. Every path then
  got the last path's σ², and a fitted Debye temperature moved with the path order (348 K
  forward, 307 K reversed, true 315 K). 0005 rebinds the built-in models. 0006 rebinds every
  copied procedure, instead of reinstalling Larch's defaults over a user's custom ones. 0007
  rebinds on every path evaluation, and also procedures held in default arguments and containers.
- **Numeric effect:** in plain Larch, for fits with two or more paths that use Debye or
  Einstein σ². The app already works around the defect, so its numbers do not change.
- **Covering test:** in `test_xafs_defects.py`:
  `test_reversing_the_path_list_leaves_every_path_its_own_debye_sigma2`,
  `test_copied_parameters_keep_custom_procedures_and_read_the_current_path`,
  `test_procedures_reached_later_or_indirectly_read_the_current_path`.
- **App needs it:** no; the app works around it. Plain Larch scripts in the same environment
  get correct results.

### 8. XRF model

- **Patch:** 0004 (`larch/xrf/xrf_model.py`).
- **Why:** `XRF_Model.calc_spectrum` added the escape term even when escape peaks were off, and
  then needed an escape energy that was never set (an `AttributeError`). With escape on, the
  interpolation filled NaN outside the window, and that NaN erased the component itself wherever
  the shifted axis left the window. For a detector whose escape energy exceeds the window width,
  that is everywhere. Now the escape term is added only when enabled, with 0 outside the window.
- **Numeric effect:** in plain Larch, the crash is gone and components are no longer zeroed.
- **Covering test:** all of `test_xrf_model.py` (6 items).
- **App needs it:** no; the app has its own version.

### 9. FEFF path parameters (temporary)

- **Patch:** 0008 (`larch/xafs/feffdat.py`), temporary.
- **Why:** upstream `c18a4ed63` (2026-10-11, "move hashkey to FeffDatFile, several cleanups")
  changed three `FeffPathGroup` behaviors. The patch restores those of `8d6cd41c2`, one hunk each:
  - `FeffPathGroup.hashkey` came from the Feff.dat content alone (`FeffDatFile.hashkey`). Two
    paths with identical content, such as a split shell or one file added twice, got the same
    parameter names (`sigma2_<dataset>_<hashkey>`), and the last path's values overwrote the
    others'. The hashkey is again made from the filename, degeneracy, shell, geometry and reff
    (`__geom2label`). `FeffDatFile.hashkey` stays as upstream has it.
  - `path2chi(path, params=<lmfit Parameters>)` set up the path parameters but did not calculate
    chi: the `_calc_chi` call was indented into the `else` branch.
  - Without an explicit `k`, `_calc_chi` clamped `kmax` to the Feff.dat k grid only when `kmax`
    was None (indentation), so a given `kmax` past the grid extrapolated.
- **Numeric effect:** with the patch, everything is as at `8d6cd41c2`. Without it, in the app,
  an Artemis fit with two enabled paths of identical content keeps correct fitted parameters
  and statistics, but reports wrong per-path values and per-path χ(k) (four
  `test_artemis.py::test_distinct_fitted_path_contributions_match_native_final_parameters`
  cases fail). The app never calls `path2chi` with lmfit Parameters or `_calc_chi` without `k`;
  plain Larch scripts in the same environment get chi = None and a k grid up to the given
  `kmax`. Default path labels follow the hashkey, so they also return to the `8d6cd41c2` values;
  the app sets its own labels, so none of its outputs carry them.
- **Covering test:** `test_feffdat_regressions.py` (3 items).
- **Exit condition:** upstream fixes the three regressions (offer each upstream as an issue,
  submitted by a person).
- **App needs it:** yes, for fits whose paths share FEFF content.

### 10. Self-absorption E0 (temporary)

- **Patch:** 0009 (`larch/xafs/fluo.py`), temporary: a revert of upstream `d6d27ccca` ("fluo:
  force recalculation of e0", 2026-10-09).
- **Why:** since `d6d27ccca`, `fluo_corr` drops the `e0` it is given, and both of its
  `pre_edge()` calls find their own. The app's FLUO correction passes the group's E0 (the one the
  import found, or one the user set), so the corrected curve is normalized around another E0
  than the curve it corrects. This is an intentional upstream change to an app result, so the
  patch keeps the old behavior until the owner decides. After the revert, an explicit `e0` wins,
  a group's own `e0` is used when none is passed (upstream `11448b7b3`), and `pre_edge()` finds
  one only when neither gives it. `nvict` is again forced to 0; the app never passes another value.
- **Numeric effect:** with the patch, the app's numbers are those it had on the previous pin
  (`8d6cd41c2` with the team patches), bit for bit. Without it, measured through the HTTP API on Cu, Fe₃C and Ni (`examples/xafsdata`),
  FLUO at 45°/45°, each with the imported E0 and with E0 set to the tabulated edge:
  - The normalized corrected curve (`norm_corr`: the preview's "Corrected" curve, and the saved
    group's `norm`) moves in every case, because upstream's second `pre_edge()` finds an E0 5 to
    14 eV above the group's. Its largest change is 3.7% of the edge step (Fe₃C, tabulated E0);
    the other cases move by 0.7% to 2.1%.
  - The corrected μ (`mu_corr`) moves only when the group's E0 differs from `find_e0`'s (here,
    the tabulated E0): by up to 1.3% of its largest value (Ni). With the imported E0 it is
    bit-identical.
  - The measured curve and the reported E0 do not change. Booth, and the FLUO branch with a
    fixed step or `nvict`, use the app's own formula and do not change.
- **Covering test:** `test_xafs_fluo.py::test_fluo_corr_normalizes_around_the_e0_it_is_given`;
  through the HTTP API, `backend/tests/test_athena_self_absorption_matches_larch_3461938ac.py`. Upstream's
  `tests/test_xafs_fluo.py` still passes with the patch.
- **Exit condition:** the owner adopts upstream's behavior. Then retire the patch, and re-pin the
  backend test's numbers to upstream's.
- **App needs it:** yes, until the owner decides.

### Packaging: no `mkl_fft`

- **Patch:** 0002 (`pyproject.toml`).
- **Why:** removes the `mkl_fft ; platform_system != 'Darwin'` dependency, which the app's
  release environments do not install. This is a packaging change, not a Larch behavior, so it is
  not one of the numbered entries above.
- **Numeric effect:** none at the baseline, whose release constraints do not include `mkl_fft`.
  Where `mkl_fft` is missing, `larch/xafs/xafsft.py` uses `scipy.fftpack` instead.
- **Covering test:** `test_series.py` checks the patched `pyproject.toml` blob.
- **Exit condition:** XAScraft's environments can install `mkl_fft` on every platform they
  support, or upstream drops it.

## Maintaining the queue

All work happens in a scratch clone of upstream (`git clone --shared <local clone>`), never
in the local upstream clone itself. Agents never push anything to xraypy/xraylarch.

The patch files are written with:

```sh
git format-patch -1 <commit> --start-number <N> --no-signature --full-index -o larch-patches/series -- \
    larch tests/test_xafs_defects.py tests/test_xrf_model.py \
    tests/test_read_beamlinedata.py tests/run_tests.sh pyproject.toml
git interpret-trailers --in-place --trailer "XAScraft-commit: <full sha>" larch-patches/series/<file>
```

`--full-index` and `--no-signature` keep the files independent of the repository and the git
version. The series is applied with:

```sh
GIT_COMMITTER_NAME="XAScraft patch queue" GIT_COMMITTER_EMAIL="patches@xascraft.invalid" \
  git am --committer-date-is-author-date larch-patches/series/*.patch
```

### Adding a patch

1. Apply the series to the pin in a scratch clone. Commit the fix there with its author and
   message, dated after the last patch, so the series stays in date order.
   - A **temporary** patch changes only `larch/`, and its subject starts with `Temporary:`. Say
     in its message which upstream commit it undoes and when it can go.
   - A **team** patch may also add its regression test to an upstream test file the series
     already carries (`tests/test_xafs_defects.py` and the others in the `format-patch`
     command). A new upstream test file also goes into that command, into `CARRIED_PATHS` in
     `tests/test_series.py`, and, unless upstream's `tests/run_tests.sh` names it, into `FILES`
     in `run-upstream-tests.sh`.
2. Write it as the next numbered file with the `format-patch` command above (no trailer: only
   0001 to 0007 come from XAScraft commits).
3. Put its regression test in `larch-patches/tests/` (a team patch's test is a copy of the one
   it adds upstream). Check that it passes on the patched build and fails with
   `build.py --exclude <NNNN>`.
4. Add a ledger entry (why, numeric effect, covering test, exit condition) and a row in the
   Patches table.
5. Update `patched-larch-tree` (and `patched-pyproject-blob`, if it changed) in `PIN` to
   `git rev-parse HEAD:larch` (and `HEAD:pyproject.toml`) of the scratch clone, and the same
   values in `test_pin_is_the_reviewed_one` in `tests/test_series.py`.
6. Reinstall (`install-dev.sh`) and run all tests here and the backend tests. If the patch
   changes a Larch file that a backend fixture manifest pins (`backend/tests/fixtures/athena-*-fixtures.json`),
   those tests fail: review the change and add it to `REVIEWED_LARCH_CHANGES` in
   `backend/tests/larch_source.py`, or record a new oracle. A patch that moves an app result
   also changes the backend tests that pin it, and its ledger entry says by how much.

Nothing else names the patch count or the version: the tests read them from `series/` and
`PIN`.

### Retiring a patch

A patch is retired when the per-patch report on a new pin shows that upstream contains an
equivalent fix (the entry's exit condition).

1. Delete the file and renumber the later files, so the numbers stay contiguous.
2. Move its ledger entry under a "Retired" heading, with the pin that made it unnecessary.
3. Keep its regression test while it still guards upstream's fix; delete the test only if
   upstream carries an equivalent one.
4. Update `PIN`, `test_pin_is_the_reviewed_one` and the Patches table as for adding a patch,
   and run the same tests.

### Re-pinning

Re-pin only when the owner asks.

1. In a scratch clone, check out the new upstream commit and apply the series with `git am`.
   If a patch fails, use `git am -3` or redo it by hand, keeping its author, date, message and
   trailer.
2. Regenerate every file from the new commits with the `format-patch` command above. Use the
   new commits' SHAs as `<commit>`, but keep the original `XAScraft-commit` trailers. The
   trailer line is already in each message, so do not add it a second time.
   `git am --continue` after a conflict does not keep `--committer-date-is-author-date`, so
   apply the regenerated files once more with the command above and regenerate from those
   commits: then each file's `From <sha>` line is the commit that applying the series gives.
3. Update `PIN`: `upstream-commit`; `upstream-version` from
   `git describe --tags --long --match '*[0-9]*' <commit>` (`2026.3.1-78-g247278cef` becomes
   `2026.3.1.post78+g247278cef`, with a 9-character short SHA); and the patched hashes.
4. Update what encodes the pin outside `PIN`: `test_pin_is_the_reviewed_one` in
   `tests/test_series.py`, `FILES` in `run-upstream-tests.sh` (upstream's `tests/run_tests.sh`
   list at the pin), and the expected counts under [Running the tests](#running-the-tests).
   For every Larch file a backend fixture manifest pins that upstream changed, review the diff
   and add it to `REVIEWED_LARCH_CHANGES` in `backend/tests/larch_source.py` (or record a new
   oracle when the change matters).
5. Run all tests here and the per-patch report. Retire patches that upstream made unnecessary.
   Give every other difference from the previous pin that the app could see a verdict:
   - an upstream bug or regression: a temporary patch that undoes it, until upstream fixes it;
   - a change to a private Larch API the app calls: an adapter in the app that works on both pins;
   - an intentional upstream change to an app result: a temporary patch that keeps the old
     result, with before/after numbers for the owner, until the owner adopts the change;
   - a change with no effect on the app's results, shown and not assumed: adopted.

At `247278cef` (from `8d6cd41c2`), 0001 to 0006 applied with offsets only. 0007 failed on
`tests/run_tests.sh`, whose last lines upstream rewrote (`34be3ef37`); its hunk was redone on
upstream's file and still adds `test_xafs_defects.py` to the last line. Its `larch/` part
applied unchanged. Upstream's list gained `test_xafs_rebin.py`.
