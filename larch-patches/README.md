# Larch patch queue

XAScraft runs upstream [xraylarch](https://github.com/xraypy/xraylarch) at a pinned commit
plus the patches in this folder. Nothing else in the repository changes Larch.

| Path | What it is |
| --- | --- |
| `PIN` | The upstream URL and commit, the upstream version string at that commit, and the `larch/` tree and `pyproject.toml` blob that applying the series must give. |
| `series/NNNN-*.patch` | `git format-patch` files, applied in order with `git am`. Each keeps the original author, date and message, and carries an `XAScraft-commit: <sha>` trailer naming the XAScraft commit it came from. |
| `build.py` | Builds the patched Larch: source tree, wheel, sdist and `IDENTITY`. See [Building](#building). |
| `tests/test_series.py` | Applies the series to the pin in a scratch clone and checks the result against `PIN` and the original commits. |
| `tests/test_build.py` | Runs `build.py` and checks its output, its version and its failure modes. |
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
| `IDENTITY` | JSON: `pin`, `upstream_version`, `patch_set_id`, `version`, `pure_upstream`, `patches` (number, file, `xascraft_commit`), `excluded`, `larch_tree`. |

- **Version**: `<upstream-version from PIN>.xascraft.<patch-set id>`, today
  `2026.3.1.post35+g8d6cd41c2.xascraft.9b231a511159`. The patch-set id is the first 12 hex digits
  of the sha256 of the applied patch files' bytes, in order (`cat series/*.patch | sha256sum`).
  It changes only when the pin or a patch file changes; a reworded message counts.
- **Per-patch builds** (for the per-patch report): `--exclude 0003` (repeatable) leaves patches out
  and marks the version, e.g. `….xascraft.<id of the rest>.without0003`. `--pure-upstream` applies
  nothing and gives upstream's own version, `2026.3.1.post35+g8d6cd41c2`.
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

The backend's environment gets Larch from this build, never from the repository's `larch/`
folder (`backend/requirements.txt` does not install Larch). From the repository root:

```sh
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r deploy/python-release-constraints.txt -c deploy/python-release-constraints.txt
larch-patches/install-dev.sh --upstream ~/xraylarch       # omit --upstream to fetch the pin from GitHub
(cd backend && .venv/bin/pip install -r requirements.txt -c ../deploy/python-release-constraints.txt)
```

`install-dev.sh` runs `build.py` with the venv's interpreter as the build backend, installs the
wheel under the release constraints (replacing any Larch already installed, an editable one
included), and checks that `import larch` gives IDENTITY's version from site-packages.
`--python PYTHON` installs into another environment; `--keep DIR` keeps the build output.
Run it again after the pin or a patch changes: `backend/tests/test_larch_dependency.py` fails
while the installed Larch is not the current build.

Start Python from `backend/` (or any directory but the repository root) while the root `larch/`
folder exists: `python -m` and `python -c` put the current directory first on `sys.path`, so at
the root the folder would shadow the installed build.

## Running the tests

```sh
# Regression tests, against the Larch installed in the active environment:
pytest larch-patches/tests -k "not test_series and not test_build"

# The series check. It needs git, this repository's history, and upstream:
XASCRAFT_LARCH_UPSTREAM=/path/to/local/xraylarch/clone pytest larch-patches/tests/test_series.py

# The build script (about 1.5 minutes; the test interpreter is the build backend, so it must
# have the pinned setuptools, wheel and setuptools-scm, as a release-constraints venv has):
XASCRAFT_LARCH_UPSTREAM=/path/to/local/xraylarch/clone pytest larch-patches/tests/test_build.py
```

- Use the `pytest` command, not `python -m pytest` from the repository root. While the root
  `larch/` folder still exists, `python -m` puts it on `sys.path` ahead of the installed Larch.
  The session header names the Larch that was tested.
- `XASCRAFT_LARCH_UPSTREAM` takes a local clone path or a URL. Unset, the test fetches the
  pinned commit from the URL in `PIN`. A local clone is only read (`git clone --shared`).
- The FEFF tests read `examples/feffit/Feff_Cu` from this repository's `examples/` folder.
  `XASCRAFT_EXAMPLES_DIR` points them at another `examples/` copy.
- On the patched build at this pin, all 12 regression items pass. On plain upstream
  `8d6cd41c2`, all 12 fail.

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

The patches also carry the team's changes to upstream test files: `tests/test_xafs_defects.py`
(0005 to 0007), `tests/test_xrf_model.py` and the APS 12-BM test in `tests/test_read_beamlinedata.py`
(0004), and the `tests/run_tests.sh` line that runs `test_xafs_defects.py` (0007).
The subjects of 0001 to 0004 describe mostly app work, because those commits also changed the app.
Their messages are kept as written; this ledger says what each patch does to Larch.

## Ledger

Each entry gives: why the patch exists, its numeric effect, the test that covers it, and its
exit condition. "Gap" means no Larch-level test exists; the backend tests named next to it cover
the behavior only indirectly.

Every entry has the same exit condition: **upstream contains an equivalent fix**. The per-patch
report proves this: on the new pin, a build without the patch gives the same outputs as a build
with it, and the entry's covering test passes without the patch. Then the patch is retired (see
below).

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
- **Numeric effect:** small on normal spectra: k²χ RMS changes by 8e-8 to 1.5e-4. When mu is
  in raw counts, chi changes by 1 to 6%. `delta_chi` is divided by the edge step.
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

### Packaging: no `mkl_fft`

- **Patch:** 0002 (`pyproject.toml`).
- **Why:** removes the `mkl_fft ; platform_system != 'Darwin'` dependency, which the app's
  release environments do not install. This is a packaging change, not a Larch behavior, so it is
  not one of the eight entries above.
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

1. Apply the series to the pin in a scratch clone. Commit the fix there with its author, date and
   message, and add a regression test under that clone's `tests/`.
2. Write it as the next numbered file with the `format-patch` command above. If the fix comes
   from an XAScraft commit, add that commit's `XAScraft-commit` trailer.
3. Copy the regression test into `larch-patches/tests/`. Check that it passes on the patched
   build and fails without the patch.
4. Add a ledger entry and a row in the Patches table.
5. Update `patched-larch-tree` (and `patched-pyproject-blob`, if it changed) in `PIN` to
   `git rev-parse HEAD:larch` (and `HEAD:pyproject.toml`) of the scratch clone. Update the commit
   list in `tests/test_series.py`.

### Retiring a patch

A patch is retired when the per-patch report on a new pin shows that upstream contains an
equivalent fix (the entry's exit condition).

1. Delete the file and renumber the later files, so the numbers stay contiguous.
2. Move its ledger entry under a "Retired" heading, with the pin that made it unnecessary.
3. Keep its regression test while it still guards upstream's fix; delete the test only if
   upstream carries an equivalent one.
4. Update `PIN` and `tests/test_series.py` as for adding a patch.

### Re-pinning

Re-pin only when the owner asks.

1. In a scratch clone, check out the new upstream commit and apply the series with `git am`.
   If a patch fails, use `git am -3` or redo it by hand, keeping its author, date, message and
   trailer.
2. Regenerate every file from the new commits with the `format-patch` command above. Use the
   new commits' SHAs as `<commit>`, but keep the original `XAScraft-commit` trailers. The
   trailer line is already in each message, so do not add it a second time.
3. Update `PIN`: `upstream-commit`; `upstream-version` from
   `git describe --tags --long --match '*[0-9]*' <commit>` (`2026.3.1-35-g8d6cd41c2` becomes
   `2026.3.1.post35+g8d6cd41c2`, with a 9-character short SHA); and the patched hashes.
4. Run all tests here and the per-patch report. Retire patches that upstream made unnecessary.
   Give every other difference from the previous pin a verdict, as the decisions record
   describes.

Known for the next pin: at upstream `946eeeca0`, 0007 fails on `tests/run_tests.sh`, which upstream
changed. The `larch/` part of 0007 still applies. The simplest fix is to drop the
`run_tests.sh` hunk, since the new CI names test files explicitly.
