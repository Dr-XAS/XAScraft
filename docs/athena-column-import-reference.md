# Athena column import and live preview

This checkpoint covers part of the full Athena duplication goal. It does not
include Artemis. The remaining requirements retain their original IDs in the
[parity matrix](athena-parity.md).

## Primary-source contract

The reference is Demeter revision
`06afc8da08a5a7d5a26ee14992170fcf5dc67406`. Source bytes were verified against
the pinned Git tree; SHA-256 hashes are in [the source manifest](athena-primary-sources.json).

- [Column-selection manual](https://bruceravel.github.io/demeter/documents/Athena/import/columns.html): inspect file contents, select energy and detector columns, see the resulting equation and spectrum, choose energy units and input type, sum MED channels or save them separately, select column ranges, clear numerators, and pause plotting.
- [Reference-channel manual](https://bruceravel.github.io/demeter/documents/Athena/import/ref.html): shared energy column, reference plot, natural-log and Same element choices, reference below its sample, and tied energy shifts.
- [ColumnSelection.pm](https://github.com/bruceravel/demeter/blob/06afc8da08a5a7d5a26ee14992170fcf5dc67406/lib/Demeter/UI/Athena/ColumnSelection.pm): range selection checks numerator buttons, accepts reversed endpoints, skips the energy column, and pause suppresses automatic redraws.
- [IO.pm](https://github.com/bruceravel/demeter/blob/06afc8da08a5a7d5a26ee14992170fcf5dc67406/lib/Demeter/UI/Athena/IO.pm), reference import: copy the sample data type; when Same element is enabled, copy element/edge identity. Initialize the reference independently. If its E0 is too far from the sample, use the shared identity's atomic edge. A different-element reference uses its own derivative E0. The sample's fractional-E0 policy is not applied to the foil.
- [process.demeter_conf](https://github.com/bruceravel/demeter/blob/06afc8da08a5a7d5a26ee14992170fcf5dc67406/lib/Demeter/configuration/process.demeter_conf): `rebin.use_atomic` defaults to 25 eV.

## Implemented flow

Multi-file batches ask whether to use the same import parameters before the
first import. Choosing Yes applies the reviewed column positions, units,
and signal/reference settings to the remaining files without another
confirmation. Renamed headers, missing selected columns, known labels moving
to different positions, and mandatory reader
reviews pause the batch for that file. Choosing No retains individual review.
Each new file selection asks again, including ZIP or SPEC selections expanded
into multiple entries. Failed imports retain the pending file and accepted
earlier imports, so retry resumes without duplicating successful files.

The Measurement choice **Transmission + fluorescence + reference** imports
three spectra from the same file: transmission `ln(I0/It)`, fluorescence
`If/I0`, and reference `ln(It/Iref)`. Files with all four detector signals
identified default to this choice, unless matching remembered choices or the
reader's sample-or-foil evidence select a different workflow. Missing or
ambiguous columns require a manual choice.

**Transmission**, **Fluorescence**, and **Reference** tabs switch column controls
without changing the preview's signal selection. The preview initially overlays
all three curves. Transmission and fluorescence have independent detector
selections, channel grouping, sign, and scale. Both samples link to one shared
reference, and share the energy column and units.
Imported spectra are ordered Transmission, Fluorescence, Reference and retain
their own arithmetic and source columns. **Transmission + fluorescence** remains
available for files without a reference.

Normal import contains the column calculation and the controls needed to read
the file. It does not apply remembered rebinning, marking, parameter copying,
alignment, or an old import edge policy. Input normalization remains explicit;
EXAFS eligibility and E0 are resolved for each imported spectrum. The
**Ordering** section remains available for sorting an unsorted energy axis and
averaging repeated-energy rows, because a strictly increasing axis is required
before import can finish.

Rebinning and alignment are available after import under **Process → Rebin
data** and **Process → Align scans**. The rebin tool retains its grid defaults
and previews, and **Copy / reset parameters…** in the processing panel copies
or resets parameters for the chosen data. Mark data in the data list before
applying a batch operation. These operations retain their own preview and undo
behavior.

Reader detector suggestions are applied when choosing the initial columns.
The normal import form does not repeat them in a separate reader toolbar;
switching a single measurement selects its detected columns, while leaving a
combined import preserves that signal's reviewed columns. Manual corrections
use the signal tabs. Reader notes, warnings, and required
I0-correction review remain visible. An ambiguous sample-or-foil scan still
requires an explicit choice before import. Reference options appear only in
the Reference tab.

Every selected signal is validated and saved together as one project revision
and undo step; an invalid signal does not leave a partial import.
Shared-parameter batches reuse all selected detector columns. Combined import
requires energy data and is cleared when switching to extracted chi(k).

`AthenaColumnSelection` displays the original file header and initial rows,
column numbers, the selected expression, and a live Plotly figure. Each change
requests `/preview-columns` after a 180 ms debounce. Cancelled or superseded
responses cannot replace the current selection's plot. During automatic
refresh the previous curve is hidden. The import preview always updates
automatically; the native pause and manual-replot controls are not included.
**Retry preview** appears only after a failed API preview request and retries
the current selection. Invalid local column settings must be corrected before
a preview can run. Reference visibility can be toggled without repeating the
calculation.

`athena_columns.map_columns` is shared by preview and import. It evaluates
every point for direct signal, logarithmic transmission, and fluorescence or
yield division. keV conversion, stable row sorting and summed/individual MED
channels follow the same path. Zero divisors, zero logarithm arguments, duplicate channel IDs and nonfinite
results are reported. Empty operand selections use constant 1, as in Athena. Errors at
points omitted from display sampling still prevent import. A preview can show
an unordered axis with a warning so column selection remains inspectable;
actual import requires a strictly increasing axis.

Preview changes neither project version, groups, history nor undo. Display
sampling keeps bucket minima/maxima and endpoints with at most 2,400 points
per curve, preserving single-point detector glitches. Import retains every
source point. Original input columns and their units are preserved for project exchange.
The selected signal array follows native sign/scale adjustments; the saved
mu array includes those adjustments independently of later plot scaling.

Separate-channel import creates a sample per numerator. For a single measurement
mode, each sample receives its own unmarked reference immediately below it.
Combined transmission/fluorescence import instead shares one unmarked reference
across all samples, including individual fluorescence channels. The entire import
has one saved revision and one undo step. References
keep the sample's input type, independently determined E0, and optionally its
identity. A reference with a distant derivative E0 is reset to the tabulated
edge with a visible warning. Raw, finite reference data remain inspectable
with an explicit processing error when normalization cannot run. Invalid
arithmetic still rejects the entire import. If the same-element tabulated
edge lies outside the scan, a warning retains the measured derivative choice
rather than inventing an out-of-range E0.

## Evidence and limits

### Reselecting a stored group's columns

The data-list context menu includes **Reselect import columns…** for groups
with retained import columns. This action targets the right-clicked row, loads
its saved column choices on demand, and reuses the existing live preview.
**Apply column changes** replaces that group's spectrum in one undoable
revision, retaining its ID, name, list position, notes, marks, plot styling,
and reference links. Processing parameters are initialized again for the new
signal; linked energy shifts remain tied. Cancel and preview do not change the
project.

Replacement retains rebin controls for replaying or adjusting a stored
import-time grid against the original columns. It also keeps explicit EXAFS
processing and reader-suggestion controls; these belong to rebuilding the
existing spectrum and are not shown in normal import.

Replacement creates one spectrum, so batch import, separate detector groups,
dual measurement import, and new reference creation remain in the ordinary
import workflow. Frozen groups and groups without retained source columns
cannot use this action. The server prefers the original staged upload and can
reconstruct missing uploads from retained columns, including the original
table for import-time rebinning. If point removal has destroyed the complete
original table and its upload is missing, import the source file again.

There is no new background calculation or extra copy of source columns in
normal project responses. Inspection and preview run only while the dialog is
used; applying recalculates the replacement and affected background dependents.

- `backend/tests/test_athena_columns.py`: direct/ratio/log arithmetic, summed
  and individual channels, reverse-order keV, raw chi axes, reference formulas,
  native reference type/identity/E0 behavior, separate reference pairs, undo,
  invalid late detector channels, bounded original-file text, extrema
  preservation, and HTTP immutability/version conflicts.
- `frontend/components/athena-import-preview.test.tsx`: debouncing, stale
  success/failure replies, cancellation, automatic refresh, conditional retry, upload/version
  isolation, plot data/axes, references and display-sampling warnings. Plotly
  is mocked here; these are component contracts rather than browser evidence.
- `frontend/components/athena-column-selection.test.tsx`: range parsing,
  additive selection, clear, invalid-range recovery, individual channels,
  reference options, independent signal tabs with keyboard navigation, chi
  eligibility, file contents and busy controls.
- `backend/tests/test_athena_dual_mode_import.py`: shared reference arithmetic,
  links, rebinning, alignment, capacity limits, reimport, and atomic undo/redo.
- `frontend/tests/e2e/athena-three-channel-import.spec.ts`: automatic three-signal
  selection, tab-independent Plotly overlays, reference edits, persisted formulas,
  shared reference links, and project reload using synthetic detector counts.
- `frontend/tests/e2e/athena-columns.spec.ts`: the repository's measured
  `examples/xafsdata/cu_10k.xmu` is transformed into deterministic detector
  counts whose inverse formulas recover the original mu. This fixture is
  explicitly a transformation of measured data, not an independently measured
  detector record. Chromium tests compare actual Plotly data, preview results
  and persisted groups, verify automatic updates after detector/scale edits,
  and capture desktop/mobile views.

Passing counts and actual browser results are recorded in the
[verification log](athena-verification.md). These checks use the Larch backend
and pinned source contracts; they are not a replay in the native wx Athena UI.

## Native arithmetic and suggestion extension, 2026-09-10

Further review of `Data/Mu.pm::put_data` established three behaviors that the
older implementation missed: the denominator can be a sum, logarithmic input
uses the absolute detector ratio, and sign/scale controls alter the imported
signal. The UI now provides the native combinations:

- Numerator and denominator checkbox sums, with 1 for an empty selection.
  The existing single-column denominator API remains compatible; multiple
  columns are sent as an array. Clear controls update the live expression and
  preview, including a valid constant curve.
- Natural log evaluates `ln(abs(numerator / denominator))`. Negative ratios
  produce a polarity notice; zero or nonfinite results are rejected over the
  entire input before any group is saved. The earlier tests that rejected
  negative ratios were corrected against the pinned source and replaced with
  independent absolute-log oracles plus zero-ratio rejection cases.
- Flip exchanges the complete numerator and denominator selections, and the
  multiplicative constant scales the imported mu. The column-table checkboxes,
  live expression and preview all update from the exchanged operands. Legacy
  saved sign inversion is folded into a negative constant so reopening older
  mappings preserves their signal. Reference data use their own expression
  without the sample's scale. The group plot multiplier stays 1.
- Reference selections may use a single column or constant 1 for either
  operand. Both empty selections disable reference import; choosing the
  explicit Constant 1 option permits a constant-only reference.
- Switching to chi(k) disables/resets units, division, natural log, flipping,
  scale and reference controls while retaining the numerator. The backend also
  ignores inactive absorption transforms for chi and canonicalizes its saved
  mapping, matching the native direct chi-column path.

`Data/Mu.pm::guess_units` examines the first five values. An increasing
sequence is eV if its first value exceeds 100, otherwise keV. This rule is now
used for inspected energy-column suggestions and when choosing another energy
column. Explicit eV/keV column metadata takes precedence. Other sequences yield
no guess and the UI asks the user to inspect and select units; it does not
reproduce the native out-of-range `lambda` selection index in a two-item menu.
Full wavelength support remains open.

Detector suggestions use the pinned `file.demeter_conf` defaults: incident
`i(0$|o)`, transmission `^i($|1$|t)`, fluorescence/yield `i[fy]`. Transmission
is preferred to fluorescence when recognized. A named existing mu column is
used directly, and k/chi labels or a .chi extension identify extracted chi.
Unknown multi-column tables initially select their second column; a single
energy column uses constant 1. The live equation/figure lets the user correct
these suggestions. Explicit choices persist for compatible files in the same
batch, even when later files carry different recommendations. Successful imports
also [remember choices across sessions](athena-column-memory-reference.md),
including detector selections and references. Normal import ignores historical
preprocessing and rebin activation; the processing tools keep their own choices.
Native editable preference expressions and the complete beamline plugin
registry remain open.

The column dialog's native expression fields are read-only in
`ColumnSelection.pm`; earlier notes incorrectly implied a general expression
editor in this dialog. Its native checkbox sums and constants are now exposed.
General scientific engine command/expression input remains part of UI-12 in
the unchanged full parity matrix.

`test_athena_column_arithmetic.py` independently checks all three measurement
forms with multiple scales/signs, summed denominators, negative count polarity,
constant operands, independent reference scaling, chi behavior, strict field
validation, source-column preservation, and JSON/PRJ round trips. It also
covers detector aliases, unit-heuristic boundaries and single-column files.
Additional frontend tests cover emitted expressions/payloads, invalid scalar
editing, resets and batch reuse; real Chromium checks suggestions, denominator
  sums, scaling/flipping and type switching. The validation log records actual
run counts, not native wx execution.

A deliberate numerical difference from the native text widget: zero is a
valid explicit multiplier and gives a zero signal; nonnumeric/nonfinite values
are rejected rather than silently replaced with 1. Constant or inverted data
can remain inspectable with a processing error if no positive edge can be
normalized. The original table is retained for correction/reimport.

Still open: full type-conversion/eligibility, other FEFF layouts, full source-text inspection,
detector corrections, wavelength handling,
user-configurable import preferences, the beamline file-plugin registry, and
general engine commands. File/column/group resource limits and complete native
UI replay also require review. No full import row is promoted to Verified here.

The API's import-time three-region rebinning and marking/standard
copying/alignment remain documented by the [rebin](athena-import-rebin-reference.md)
and [preprocessing](athena-import-preprocessing-reference.md) extensions.
Normal browser import uses the post-import tools described above instead.

FEFF xmu.dat import, normalized processing, live column alternatives and native
project flags are now covered by the [FEFF extension](athena-feff-import-reference.md).
