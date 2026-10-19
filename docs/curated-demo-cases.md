# Measured demo cases

The primary **Load demo cases** button adds nine spectra in three project-owned
folders. Loading is one undoable command; existing project data remain intact.
Folders and explicitly linked references survive saved-project and native Athena
round trips. The earlier copper fitting tutorial remains a secondary shortcut.

| Folder | Loaded spectra | Demonstration |
| --- | --- | --- |
| Ni · transmission + fluorescence | NiO transmission; NiO fluorescence | Compare two measured channels from the same APS 20-BM scan, with a common E0 and independently normalized edge steps. |
| Cu · oxides + measured foils | Cu₂O; its Cu foil; CuO; its Cu foil | Compare oxide XANES/EXAFS and inspect real paired references. Each sample links only to the foil column in its own source file. |
| Fe · oxide series | FeO; Fe₃O₄; Fe₂O₃ | Compare oxide near-edge features and EXAFS on the original energy axes. |

Only the NiO pair is initially marked. Select or mark spectra within one element
for subsequent comparisons. In the standalone app, loading selects NiO
transmission and opens EXAFS fitting with its archived result viewer first.
The spectrum viewers retain normalized E views. Model-only bundles and integrated
spectra-only loads open Processing instead.
The original source arrays are never smoothed, aligned, rebinned or truncated by
the example loader; ordinary processing creates the displayed derived arrays.

## Sources

The asset manifest is `examples/athena/curated_demo/manifest.json`. Its three
element directories include two-column native-grid absorption exports and
byte-preserved original beamline/XDI files. Each export has a required SHA-256;
source metadata also records the original-file hash, source columns, citation,
database record ID where applicable, and processing history.

- NiO: user-supplied `NiO_20BM_APS_data_package_20261018.zip`, original
  `20260211_NiO_CAS_1313-99-1.0001`. Transmission is `ln(I0/It)` from columns 4/5;
  fluorescence is `XMAP12B:NiKa_Sum/I0` from columns 9/4; energy is column 1 in eV.
  Both exports were checked numerically against the attachment's supplied CSV.
  The scan header identifies APS 20-BM; the sample catalogue's blank beamline
  field is not used to infer a different provenance.
- Cu: Dr.XAS Database LISA records 10578 (`Cu2O_111.xdi`) and 10566
  (`CuO_111.xdi`), ESRF BM08-LISA, 300 K, Si(111). `mutrans` supplies sample
  absorption; the separate `murefer` column supplies the measured foil.
- Fe: LISA records 10588 (`FeO_311.xdi`), 10595 (`Fe3O4_311.xdi`) and 10600
  (`Fe2O3_311_XANES.xdi`), ESRF BM08-GILDA, 300 K, Si(311). The Fe foil columns
  remain in the originals but are not loaded as additional spectra.

LISA sample and Cu foil exports were checked against both the local database
arrays and original XDI columns. The Fe₂O₃ file with XANES in its name was chosen
for its denser near-edge sampling; it also contains an extended post-edge range.

## Processing and limits

NiO retains the attachment's shared header E0, pre/post-edge windows and AUTOBK
range. No additional fluorescence dead-time or self-absorption correction is
applied. The two modes are a comparison case; differences are not measurement
uncertainty estimates.

Cu and Fe use independent automatic E0 estimates. Initial FT kmax is
11.5 Å⁻¹, with kweight 2 and a Hanning window. Cu background extraction is also
limited to 12 Å⁻¹ so the FT window finishes its taper before a common narrow
high-k feature near 12.1 Å⁻¹ observed in the previews. All measured points remain available for inspection.
These initial processing choices are not fit-validated usable-k limits.
Fourier magnitudes are uncorrected for scattering phase and are not bond lengths.

The Fe spectra were recorded on different dates, and no reference calibration
is applied on loading. Their precise edge offsets should not be interpreted as
a calibrated oxidation-state scale.

## NiO transmission EXAFS model and saved fit

The NiO transmission spectrum includes a saved Artemis model and an attached
Bunsenite NiO CIF, AMCSD 0011371 (Wyckoff, *Crystal Structures*, 1963).
Its cubic reference cell has a = 4.1684 Å; its measurement temperature is not
specified. This is a reference structure, not a structural refinement of the
demo sample. The fluorescence spectrum is not assigned a fitting model.

Five Ni K-edge FEFF8L paths were calculated from Ni site 1, with a 6 Å atomic
cluster, RPATH 4 Å and at most four legs. The initial model enables two paths:

| Path | Scatterers | R_eff / Å | Degeneracy | Default |
| --- | --- | --- | --- | --- |
| feff0001 | Ni–O | 2.0842 | 6 | Enabled |
| feff0002 | Ni–Ni | 2.9475 | 12 | Enabled |
| feff0003 | Ni–O–O | 3.5580 | 24 | Optional, disabled |
| feff0004 | Ni–Ni–O | 3.5580 | 48 | Optional, disabled |
| feff0005 | Ni–O | 3.6099 | 8 | Optional, disabled |

The two-shell starter fits k = 3–11.5 Å⁻¹ with kweight 2 in R = 1–3 Å.
It uses one bounded amplitude and ΔE0, with separate ΔR and σ² for the O and Ni
shells. Coordination counts remain the FEFF degeneracies; the site multiplicity
is not another amplitude factor. S0² has not been independently calibrated.
The optional paths carry fixed provisional ΔR/σ² expressions; review their
parameterization and fit range before enabling them. Loading restores one existing
fit archive; it never runs the optimizer. Editable parameter starting values remain
the original recipe, while the result report displays the fitted values.

The archive is the previously reviewed NiO transmission fit, not a newly generated
fit on each load. It includes the complete k/R curves, complex residual, fitted
parameters and uncertainties, correlations, path contributions, raw fit report,
original timestamp and provenance. Its numerical result is unchanged: R-factor
0.0157888, reduced chi-square 225.979, six variables and 11.8225 independent points.
Ni–O and Ni–Ni distances are 2.0724 and 2.9608 Å. The saved result retains all original
warnings and adds clearly labelled `Demo review:` notes covering the large reduced
chi-square, threshold/distance and amplitude/disorder correlations, uncalibrated
S0² with fixed coordination counts, and the limited two-shell fit range. It is a
demonstration result, not a claim of a complete structural refinement.

`Ni/feff/` retains the CIF, FEFF input, all five path files, calculation metadata,
native log and saved model/fit bundle. File, input, CIF and executable hashes identify the
calculation. The native log reports a path-radius warning with a zero reported
atom extent, although the input ATOMS extend to 5.89501 Å, beyond the requested
4 Å. That disagreement and the original diagnostic remain visible in path
provenance; they are not silently discarded.

The model and archive embed the path contents and CIF snapshot, so they survive
temporary FEFF-job expiry and project JSON/PRJ save-and-reopen. The imported archive
keeps its original input fingerprint; changing the processing recipe, or a future
processing change that alters chi(k), marks it stale rather than relabelling old
curves as a new fit. Reused CIF attachment IDs are remapped without changing the
underlying CIF or numerical result. Select **NiO · transmission → EXAFS fitting**
to inspect its saved result, edit the model or explicitly run a new fit.

The `hard-xray-screening-v3` screen cannot assign an overall score to these
native grids: the Ni pair has an insufficiently sampled noise-estimation window,
and the LISA scans have sparse pre-edge steps. These values remain unavailable;
no interpolation or altered thresholds were used to manufacture a score.
Selection therefore combines source verification, coverage, visual inspection
and successful XAScraft processing. It is not a claim of absence of systematic
errors, or an experimental uncertainty assessment.

## API and failure behavior

Use `action: "example"` with `options: {"dataset":"curated-three-elements"}`.
The response includes `last_operation.curated_demo` with the created folder and
spectrum IDs. Each `fitting_models` entry also includes `fit_id` when an archived
result was loaded. The legacy default (`dataset: "copper"`, or omitted) preserves
the existing copper API fixture and Cu₂O fitting tutorial.

Missing assets, checksum mismatches or invalid recipes fail before saving the
project. The loader has no database, network or private absolute-path dependency
at runtime. It reads only the bundled manifest and data files.
