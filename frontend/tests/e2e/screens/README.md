# Screenshot comparison suite

Pixel-for-pixel comparison of every page, menu, viewer and main dialog against
snapshots recorded earlier. It guards changes that must not change the UI: any
pixel that differs fails the test.

```sh
# record (or re-record) snapshots
npx playwright test --config=playwright.screens.config.ts --update-snapshots
# compare against them
npx playwright test --config=playwright.screens.config.ts
```

The specs here end in `.screens.ts`, so `playwright.config.ts` and
`playwright.ci.config.ts` never pick them up; only `playwright.screens.config.ts`
runs them. Both frontend servers are production builds (`next build` then
`next start`), so expect a few minutes of building before the first test.

## Settings

Set in `playwright.screens.config.ts`:

- **Projects**: `desktop-light`, `desktop-dark` (1440×1000), `phone-light`,
  `phone-dark` (390×844), all standalone; `mounted-desktop-light` (1440×1000, the
  build served under `/advanced-xas/app`).
- **Browser**: Playwright's pinned Chromium (headless shell), device scale 1,
  locale en-US, time zone UTC, theme from the system colour scheme.
- **WebGL**: through SwiftShader, Chromium's CPU renderer
  (`--use-angle=swiftshader --enable-unsafe-swiftshader`), because the headless
  shell has no WebGL and the 3Dmol viewers and the 3D wavelet surface need it.
- **Repeatable raster and compositing**: `--disable-gpu-rasterization
  --num-raster-threads=1 --disable-partial-raster --disable-gpu-compositing`,
  so the page itself is drawn and composited on the CPU. Without the first three,
  some pixels (blurred dialog backdrops, rounded borders, form controls) changed
  by one or two levels between runs; without the last, about one Process dialog
  in twenty showed a stale tile (a piece of a plot where the menu had been)
  behind its blurred backdrop (8 diffs in 171 compared dialogs, against 0 of 171
  with it). The same flags are used for every run.
- **Settled screens**: before each screenshot the page has had no request in
  flight for 1.5 s (tool previews fetch after a debounce longer than Playwright's
  `networkidle`), fonts are loaded, nothing is `aria-busy`, and the project bar
  no longer reads "Working…".
- **Comparison**: `toHaveScreenshot` with `threshold: 0`, `maxDiffPixels: 0`,
  animations disabled, caret hidden. Each screen is a soft assertion, so one diff
  does not hide the rest of a test.
- **Pinned instead of masked**: `APP_BUILD_DATE`, `APP_BUILD_COUNT`,
  `APP_BUILD_SHA` (the version badge), the browser clock
  (`page.clock.setFixedTime`, 2026-01-02 03:04:05 UTC), the backend's
  `XRAYLARCH_GIT_REVISION`, and single-threaded numerics.
- **Masked** (the one list is `volatile-fields.css`), painted as a magenta box by
  that stylesheet, which the config applies to every screenshot (Playwright's own
  `mask` is drawn under modal dialogs):
  - Open a project › Recent local projects: the line under each name, "5 data
    items · <save time>", a single text run
  - Project journal › Processing history: the time of each step
- **Filtered**: in the Open a project dialog, Recent local projects is cut down to
  the project that is open, because the list holds every project the run created.

## Environment variables

| Variable | Default | Use |
| --- | --- | --- |
| `XRAYLARCH_SCREENS_SNAPSHOT_DIR` | `frontend/test-results/screens-snapshots` | Where snapshots are read and written (`<dir>/<project>/<name>.png`). |
| `XRAYLARCH_SCREENS_APP_ROOT` | this repository | Checkout whose `backend/.venv` and `frontend/` serve the app. Lets this tree's suite record another tree's UI without changing that tree's tracked files (it writes only ignored build folders there). |
| `XRAYLARCH_SCREENS_BACKEND_PORT` | `18306` | Backend port. |
| `XRAYLARCH_SCREENS_FRONTEND_PORT` | `13304` | Standalone frontend port. |
| `XRAYLARCH_SCREENS_MOUNT_PORT` | frontend port + 1 | Mounted frontend port. |
| `XRAYLARCH_SCREENS_REUSE_SERVERS` | unset | `1` reuses servers already on those ports; for writing specs only. |

## Data

Each run starts a backend on a new scratch data root. `workbench.screens.ts`
seeds two projects through the API: the copper examples (File › Load copper
examples: Cu foil 10/50/300 K, Cu₂O, shared Cu foil reference, Cuprite CIF and
FEFF paths) and the curated demo cases (Ni, Cu and Fe series with an archived
NiO fit). Three spectra are screened:

- **copper**: Cu foil · 10 K
- **cu2o**: Cu₂O · room temperature
- **demo**: NiO · transmission

## Coverage

Each line is one snapshot per project (five projects; the mounted project runs
`workbench.screens.ts` under its base path as well).

### Pages (`workbench.screens.ts › pages`)

- `page-empty-workbench`: `/` on a new, empty project
- `page-classic`: `/classic`
- `page-element-picker`, `page-element-picker-open`: `/artefacts/element-picker`, closed and open
- `page-copper-examples-loaded`: the workbench right after File › Load copper examples
- `page-demo-cases-loaded`: the workbench right after Load demo cases

### Menus (`› menus`)

- `menu-empty-<menu>` and `menu-copper-<menu>` for File, Edit, Data, Process,
  Analysis and Search menu (Help), on an empty project and with copper data
- `menu-copper-data-actions`: the ⋯ actions menu of the data list
- `menu-copper-viewer-export`: a viewer's export menu

### Workbench, panels and viewers, for copper, cu2o and demo

- `<spectrum>-workbench`: the viewport
- `<spectrum>-data-list`: the data list
- `<spectrum>-parameters-processing`, `<spectrum>-parameters-exafs-fitting`: the parameter panel, both tabs
- `<spectrum>-single-spectrum-viewer-<space>` and
  `<spectrum>-multiple-spectra-viewer-<space>`, for the E, k, R and q tabs
- `<spectrum>-wavelet-plotter` (2D heatmap, 3D surface, χ(k) and |χ(R)|)
- `<spectrum>-cif-structure-viewer` (3Dmol)
- `<spectrum>-feff-path-viewer` (3Dmol)
- `<spectrum>-exafs-fit-results` (with the fit report on demo)

### Dialogs, with copper data (`› dialogs · copper`)

- File: Open project, Import data, Save Craft project (.prj), Save complete web
  project, Save marked project (.prj), Export column data, Project journal,
  Plugin registry, Beamline identification
- Edit: Review spectra, Compare spectra, Excel report on all data, Excel report
  on marked data
- Data: Mark / freeze data, Group spectra, Processing settings, File metadata,
  Data information, Assign reference foil
- Process: Calibrate energy, Align scans, Merge marked data, Difference spectrum,
  Sum marked data, Rebin data, Deglitch data, Truncate data, Smooth data,
  Convolve data, Deconvolve data, Fluorescence self-absorption, Dispersive energy
  calibration, Fluorescence XAS from XRF fit, Raw XRF spectra and maps,
  Multi-electron excitation, Copy parameter series, Plot shortcuts, Diagnostic
  plots
- Analysis: Linear combination fitting, Principal component analysis, XANES
  peak fitting, Log-ratio & phase difference
- Help: Report a bug or feedback

Snapshot names: `dialog-<menu>-<command>`.

### Mounted build only (`mounted.screens.ts`)

A project created and launched through the signed Dr.XAS integration API:

- `linked-empty`: the launched, empty linked project
- `linked-import-dialog`: Import spectra with `tests/fixtures/cu_rt01.xmu` chosen
- `linked-workbench`: after the import
- `linked-menu-file`, `linked-menu-edit`, `linked-menu-data`: the menus of a linked project
- `linked-dialog-data-information`

### Not covered

- Commands that act at once, download a file or open the system file picker
  (New project, Import model JSON, Export Larix session, Export model JSON,
  Duplicate, Freeze, Remove, Tie/Untie reference, Undo/Redo).
- Process › Saved merge spread: disabled until a merge has been saved.
- States reached only by editing values, running a fit or dragging.
