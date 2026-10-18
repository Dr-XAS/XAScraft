import type { AthenaGroup } from "./athena"
import { expect, it } from "vitest"
import type { InspectionResponse } from "./contracts"
import { columnPayload, columnProblem, defaultRebin, flipSignalColumns, initialColumnMapping, reuseColumnMapping, reuseProblem, batchCapacityWarning, batchExclusions, setDualMode, setThreeMode, prepareImportSignals, selectedColumnMapping, importSpectrumCount, changeInputType, changeImportProcessing, lastImportedSample, withoutImportProcessing, type ColumnMapping } from "./athena-import"
const previous: ColumnMapping = { energy_column: "old", numerator: ["old"], denominator: ["d1", "d2"], mode: "fluorescence",
  units: "eV", data_type: "xanes", reference_numerator: "r1", reference_denominator: "r2", signal_multiplier: 9, invert: true, sort: false }
const inspection: InspectionResponse = { upload_id: "u", display_name: "file.dat", row_count: 5, warnings: [], issues: [],
  columns: ["e", "i0", "it"].map((name, index) => ({ column_id: `c${index}`, name, index, preview: [8, 9, 10, 11, 12], role_hint: null, unit: null, numeric: true })),
  athena_suggestion: { energy_column: "c0", numerator: ["c1"], denominator: "c2", mode: "transmission", units: "keV", data_type: "mu" } }
it('normal import keeps reviewed detector choices without applying hidden saved processing', () => {
  const configured = { ...previous,
    additional_fluorescence: { numerator: ['if'], denominator: 'i0', signal_multiplier: 2 },
    preprocessing: { mark: true, standard_id: 'old-standard', copy_parameters: true, align: true },
    rebin: { ...defaultRebin, enabled: true, e0: 8980 },
  }
  const { preprocessing, rebin, ...columns } = configured
  const simple = withoutImportProcessing(configured)
  expect(simple).toEqual(columns)
  expect(columnPayload(simple)).toMatchObject({ preprocessing: { mark: false, standard_id: null, copy_parameters: false, align: false } })
  expect(columnPayload(simple)).not.toHaveProperty('rebin')
  expect(columnPayload(simple)).not.toHaveProperty('rebin_grid')
  // Retain the explicit recipe for API/replacement callers; sanitizing the
  // normal import is not a mutation of the saved scientific provenance.
  expect(configured.preprocessing).toBe(preprocessing)
  expect(configured.rebin).toBe(rebin)
})
it("initializes a new file from backend suggestions and clears previous transforms and references", () => {
  expect(initialColumnMapping(inspection, { ...previous, is_reference: true })).toEqual({ ...previous, ...inspection.athena_suggestion,
    is_reference: false, exafs: null,
    reference_numerator: "", reference_denominator: "", signal_multiplier: 1, invert: false, individual_channels: false })
  expect(initialColumnMapping(inspection, { ...previous, is_reference: true }, true, false).is_reference).toBe(true)
})
it("initializes extracted chi and constant-1 detector suggestions", () => {
  const chi = initialColumnMapping({ ...inspection, athena_suggestion: { ...inspection.athena_suggestion!, data_type: "chi", mode: "mu", denominator: null, numerator: ["c1"], units: "eV" } }, previous)
  expect(columnPayload(chi)).toMatchObject({ data_type: "chi", mode: "mu", denominator: null, units: "eV", signal_multiplier: 1, invert: false })
  const constant = initialColumnMapping({ ...inspection, athena_suggestion: { ...inspection.athena_suggestion!, numerator: [] } }, previous)
  expect(columnPayload(constant).numerator).toEqual([])
})
it('uses automatic EXAFS for normalized imports and batches while resetting normalization for fresh raw suggestions', () => {
  const mapping = changeImportProcessing({ ...previous, energy_column: 'c0', numerator: ['c1'], denominator: 'c2',
    reference_numerator: '', reference_denominator: '', invert: false }, { is_normalized: true })
  expect(columnPayload(mapping)).toMatchObject({ data_type: 'norm', is_normalized: true, exafs: null })
  expect(columnPayload(reuseColumnMapping(inspection, inspection, mapping)!)).toMatchObject({ data_type: 'norm', is_normalized: true, exafs: null })
  const remembered = { ...inspection, remembered_columns: { version: 1, matching_columns: true, mapping, warnings: [] } }
  expect(columnPayload(initialColumnMapping(remembered, previous))).toMatchObject({ data_type: 'norm', is_normalized: true, exafs: null })
  expect(initialColumnMapping(inspection, mapping)).toMatchObject({ data_type: 'mu' })
  expect(columnPayload(initialColumnMapping(inspection, mapping)).exafs).toBeNull()
  expect(initialColumnMapping(inspection, mapping).is_normalized).not.toBe(true)
  expect(changeInputType(mapping, 'chi')).toMatchObject({ data_type: 'chi', is_normalized: false })
})
it.each(['mu', 'norm', 'xanes'] as const)('uses automatic EXAFS for new %s imports but retains explicit replacement settings', data_type => {
  for (const exafs of [undefined, null, true, false]) {
    const mapping = { ...previous, data_type, exafs }
    expect(columnPayload(mapping)).toMatchObject({ data_type: data_type === 'norm' ? 'norm' : 'mu', exafs: null })
    expect(columnPayload(mapping, { automaticExafs: false })).toMatchObject({ data_type, exafs: data_type !== 'xanes' })
  }
})
it.each([false, true])('clears remembered XANES-only processing without losing normalized=%s or column choices', is_normalized => {
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: ['c1'], denominator: 'c2',
    data_type: 'xanes', is_normalized, exafs: false }
  const remembered = { ...inspection, remembered_columns: { version: 1, matching_columns: true, mapping, warnings: [] } }
  const selected = initialColumnMapping(remembered, previous)
  expect(selected).toMatchObject({ energy_column: 'c0', numerator: ['c1'], denominator: 'c2',
    data_type: is_normalized ? 'norm' : 'mu', is_normalized, exafs: null })
  expect(columnPayload(selected).exafs).toBeNull()
  expect(changeImportProcessing(mapping, { is_normalized: !is_normalized })).toMatchObject({
    data_type: is_normalized ? 'mu' : 'norm', is_normalized: !is_normalized, exafs: null })
})
it.each(['chi', 'xmudat'] as const)('omits ordinary-energy EXAFS settings for %s input', data_type => {
  const mapping = { ...previous, exafs: false }
  expect(columnPayload({ ...mapping, data_type })).not.toHaveProperty('exafs')
  expect(changeInputType(mapping, data_type)).not.toHaveProperty('exafs')
})
it.each([[[], null], [["one"], "one"], [["one", "two"], ["one", "two"]]])("keeps old single-column payloads compatible while supporting denominator %j", (denominator, expected) => {
  expect(columnPayload({ ...previous, denominator: denominator as string[] }).denominator).toEqual(expected)
})
it("flips complete numerator and denominator selections without reusing either array", () => {
  const mapping = { ...previous, numerator: ["n1", "n2"], denominator: ["d1", "d2"] }
  const flipped = flipSignalColumns(mapping)
  expect(flipped).toMatchObject({ numerator: ["d1", "d2"], denominator: ["n1", "n2"], invert: false, signal_multiplier: -9 })
  expect(flipped.numerator).not.toBe(mapping.denominator)
  expect(flipped.denominator).not.toBe(mapping.numerator)
  expect(flipSignalColumns(flipped)).toMatchObject({ numerator: ["n1", "n2"], denominator: ["d1", "d2"] })
})
it("preserves legacy sign inversion as a negative scale instead of sending invert", () => {
  expect(columnPayload(previous)).toMatchObject({ signal_multiplier: -9, invert: false })
  expect(columnPayload({ ...previous, signal_multiplier: -2 })).toMatchObject({ signal_multiplier: 2, invert: false })
})
it("sends the reference marker only when selected", () => {
  expect(columnPayload({ ...previous, is_reference: true }).is_reference).toBe(true)
  expect(columnPayload({ ...previous, is_reference: false })).not.toHaveProperty("is_reference")
})

it("retains batch preprocessing across column changes and clears energy operations for chi", () => {
  const mapping = { ...previous, preprocessing: { mark: true, standard_id: 'std', align: true, copy_parameters: true } }
  expect(initialColumnMapping(inspection, mapping).preprocessing).toEqual(mapping.preprocessing)
  expect(changeInputType(mapping, 'chi').preprocessing).toEqual({ mark: true, standard_id: null, align: false, copy_parameters: false })
})
it("selects the imported sample even when both it and its reference are unmarked", () => {
  const sample = { id: 'sample', reference_id: 'ref', marked: false } as AthenaGroup
  const reference = { id: 'ref', reference_id: null, marked: false } as AthenaGroup
  expect(lastImportedSample([sample, reference])).toBe(sample)
})

it('sends the grid without UI flags and resets only activation for fresh layouts and chi', () => {
  const rebin = { ...defaultRebin, enabled: true, e0: 17168, width: 4 }
  const mapping = { ...previous, rebin }
  expect(columnPayload(mapping).rebin).toEqual({ e0: 17168, emin: -30, emax: 50, pre: 10, xanes: .5, exafs: .05, width: 4 })
  expect(initialColumnMapping(inspection, mapping).rebin).toEqual({ ...rebin, enabled: false })
  expect(changeInputType(mapping, 'chi').rebin).toEqual({ ...rebin, enabled: false })
  expect(columnPayload({ ...mapping, rebin: { ...rebin, enabled: false } }).rebin).toBeNull()
  expect(mapping.rebin.enabled).toBe(true)
})

it.each([{ pre: 0 }, { xanes: -1 }, { exafs: '' }, { e0: -1 }, { width: 2.5 }, { width: 12 },
  { emin: 50, emax: 50 }, { emin: -50, emax: -10 }])('rejects invalid active grids but allows disabling them: %j', invalid => {
  const rebin = { ...defaultRebin, enabled: true, ...invalid } as NonNullable<ColumnMapping['rebin']>
  expect(columnProblem({ ...previous, rebin })).toBeTruthy()
  expect(columnProblem({ ...previous, rebin: { ...rebin, enabled: false } })).toBeNull()
})

it('restores accepted choices over guesses and keeps the recorded activation and preprocessing flags', () => {
  const remembered = { ...previous, energy_column: 'c0', numerator: ['c2'], denominator: ['c1', 'c2'],
    reference_numerator: 'c1', reference_denominator: '1',
    preprocessing: { mark: true, standard_id: 'standard', copy_parameters: true, align: true },
    rebin: { ...defaultRebin, enabled: true, pre: 7 } }
  const input = { ...inspection, remembered_columns: { version: 8, matching_columns: true, mapping: remembered, warnings: [] } }
  const selected = initialColumnMapping(input, previous)
  expect(selected).toMatchObject({ ...remembered, data_type: 'mu', exafs: null, signal_multiplier: -9, invert: false })
  expect(columnPayload(selected)).toMatchObject({ rebin: { pre: 7 }, rebin_grid: { pre: 7 }, preprocessing: remembered.preprocessing })
  expect(initialColumnMapping(input, previous, false)).toEqual(initialColumnMapping(inspection, previous))
  expect(remembered.rebin.enabled).toBe(true)
})

it('stores a disabled valid grid separately without sending file-specific E0, but omits invalid disabled edits', () => {
  const mapping = { ...previous, rebin: { ...defaultRebin, e0: 8000, pre: 7 } }
  const body = columnPayload(mapping)
  expect(body.rebin).toBeNull()
  expect(body.rebin_grid).toEqual({ emin: -30, emax: 50, pre: 7, xanes: .5, exafs: .05, width: 3 })
  expect(columnPayload({ ...mapping, rebin: { ...mapping.rebin, pre: '' } })).not.toHaveProperty('rebin_grid')
})

it('shares every parameter by column position across upload IDs when the layout is the same', () => {
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: ['c1', 'c2'], denominator: ['c2'],
    reference_numerator: '1', reference_denominator: 'c1', reference_log: false, reference_same_element: false,
    individual_channels: true, is_reference: true, preprocessing: { mark: true, standard_id: 'std', align: true, copy_parameters: true },
    rebin: { ...defaultRebin, enabled: true, e0: 8000 } }
  const target = { ...inspection, columns: inspection.columns.map(c => ({ ...c, column_id: `next-${c.index}` })) }
  expect(reuseColumnMapping(inspection, target, mapping)).toEqual({ ...mapping, energy_column: 'next-0',
    numerator: ['next-1', 'next-2'], denominator: ['next-2'], reference_denominator: 'next-1' })
})

it('pauses, naming the change, when a selected column is renamed: positions alone may be other detectors', () => {
  // Reusing positions across renamed headers silently imported the wrong ratio.
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: ['c1'], denominator: 'c2', mode: 'transmission',
    reference_numerator: '', reference_denominator: '' }
  const target = { ...inspection, columns: inspection.columns.map(c => ({ ...c, name: c.index === 2 ? 'Iref' : c.name })) }
  expect(reuseColumnMapping(inspection, target, mapping)).toBeNull()
  expect(reuseProblem(inspection, target, mapping)).toBe('selected column 3 was “it” and is “Iref” here.')
  const keV = { ...inspection, column_units: { c0: 'keV' as const } }
  expect(reuseProblem(inspection, keV, mapping)).toBe('this file’s energy reads as keV; the batch uses eV.')
})

it('pauses a batch on a sample-or-foil scan after a clear first scan, but not after the user answered for the batch', () => {
  // The reviewer's probe: a clear first scan, then an identically labelled scan
  // with a marginal I0/It edge, was imported as a sample without the question
  // it asks when imported alone.
  const reader = (ambiguous: boolean) => ({ id: 'aps-xsd-labview', name: 'APS XSD LabVIEW scan', facility: 'APS', beamline: '20-BM', format: 'LabVIEW', evidence: 'header',
    confidence: 'beamline' as const, measurement: { mode: 'transmission' as const, edge_energy: 8980, contrast: { transmission: ambiguous ? 13 : 3340, reference: 15600 }, notes: [], ambiguous } })
  const clear = { ...inspection, beamline_reader: reader(false) }
  const marginal = { ...inspection, upload_id: 'u2', beamline_reader: reader(true) }
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: ['c1'], denominator: 'c2', mode: 'transmission', units: 'eV', reference_numerator: '', reference_denominator: '' }
  expect(reuseProblem(clear, marginal, mapping)).toMatch(/may be a foil rather than a sample/)
  expect(reuseColumnMapping(clear, marginal, mapping)).toBeNull()
  // A first scan that asked carries the user's sample-or-foil answer to the rest.
  expect(reuseProblem(marginal, { ...marginal, upload_id: 'u3' }, mapping)).toBeNull()
  expect(reuseProblem(clear, { ...clear, upload_id: 'u3' }, mapping)).toBeNull()
})

it('pauses a mixed folder when matching columns lack the first file\'s measurement evidence', () => {
  const source: InspectionResponse = { ...inspection, beamline_reader: {
    id: 'test', name: 'Synthetic reader', facility: 'Test', beamline: 'Test', format: 'text',
    evidence: 'header', confidence: 'beamline', measurement: {
      mode: 'transmission', edge_energy: 9000, contrast: { transmission: 100 }, notes: [],
    },
  } }
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: ['c1'],
    denominator: 'c2', mode: 'transmission', units: 'eV', reference_numerator: '', reference_denominator: '' }
  for (const target of [
    { ...inspection, upload_id: 'u2', beamline_reader: undefined },
    { ...source, upload_id: 'u2', beamline_reader: { ...source.beamline_reader!, measurement: undefined } },
  ]) {
    expect(reuseProblem(source, target, mapping)).toMatch(/evidence is missing/)
    expect(reuseColumnMapping(source, target, mapping)).toBeNull()
  }
})

it('pauses a batch answered "foil" on a scan with a clear sample edge, and a sample batch on a foil-only scan', () => {
  // The reviewer's probe: the first scan asked sample-or-foil and was answered
  // foil; a later scan with a clear I0/It edge was imported as It/Iref.
  const columns = ['e', 'i0', 'it', 'iref'].map((name, index) => ({ ...inspection.columns[0], name, index, column_id: `c${index}` }))
  const foil = { energy_column: 'c0', numerator: ['c2'], denominator: 'c3', mode: 'transmission' as const, units: 'eV' as const, data_type: 'mu' as const }
  const sample = { ...foil, numerator: ['c1'], denominator: 'c2' }
  const scan = (evidence: 'ask' | 'sample' | 'foil', upload_id: string): InspectionResponse => ({ ...inspection, upload_id, columns,
    beamline_reader: { id: 'aps-xsd-labview', name: 'APS XSD LabVIEW scan', facility: 'APS', beamline: '20-BM', format: 'LabVIEW', evidence: 'header', confidence: 'beamline',
      reference: evidence === 'foil' ? undefined : { numerator: 'c2', denominator: 'c3', log: true, default: true },
      suggestions: { transmission: evidence === 'foil' ? foil : sample, ...(evidence === 'ask' ? { foil } : {}) },
      measurement: { mode: 'transmission', edge_energy: 8980, contrast: { transmission: { ask: 13, sample: 3340, foil: 1 }[evidence], reference: 15600 }, notes: [],
        ambiguous: evidence === 'ask', foil_spectrum: evidence === 'foil' } } })
  const answeredFoil: ColumnMapping = { ...previous, ...foil, reference_numerator: '', reference_denominator: '' }
  const answeredSample: ColumnMapping = { ...previous, ...sample, reference_numerator: 'c2', reference_denominator: 'c3' }
  expect(reuseProblem(scan('ask', 'u1'), scan('sample', 'u2'), answeredFoil)).toMatch(/clear I0\/It sample edge \(3340 times its noise\), but the batch imports It\/Iref/)
  expect(reuseColumnMapping(scan('ask', 'u1'), scan('sample', 'u2'), answeredFoil)).toBeNull()
  expect(reuseProblem(scan('ask', 'u1'), scan('foil', 'u2'), answeredSample)).toMatch(/I0\/It shows no edge and It\/Iref does/)
  // Evidence that agrees with the answer, or the same evidence the user already answered, imports.
  expect(reuseProblem(scan('ask', 'u1'), scan('sample', 'u2'), answeredSample)).toBeNull()
  expect(reuseProblem(scan('ask', 'u1'), scan('foil', 'u2'), answeredFoil)).toBeNull()
  expect(reuseProblem(scan('sample', 'u1'), scan('sample', 'u2'), answeredFoil)).toBeNull()
})

it('pauses sharing for a missing selected column, a nonnumeric column, or a known reordered label', () => {
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: ['c1'], denominator: '', reference_numerator: '', reference_denominator: 'c2' }
  expect(reuseColumnMapping(inspection, { ...inspection, columns: inspection.columns.slice(0, 2) }, mapping)).toBeNull()
  expect(reuseColumnMapping(inspection, { ...inspection, columns: inspection.columns.map(c => ({ ...c, numeric: false })) }, mapping)).toBeNull()
  expect(reuseColumnMapping(inspection, { ...inspection, columns: inspection.columns.map((c, i) => ({ ...c, name: ['e', 'it', 'i0'][i] })) }, mapping)).toBeNull()
  expect(reuseColumnMapping(inspection, inspection, { ...mapping, numerator: ['unknown'] })).toBeNull()
})

it('pauses for a changed layout even in unused columns, and preserves scalar denominators and constant signals', () => {
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: [], denominator: '', reference_numerator: '', reference_denominator: '1' }
  const target = { ...inspection, columns: inspection.columns.slice(0, 1) }
  expect(reuseProblem(inspection, target, mapping)).toBe('the file has 1 columns, the first had 3.')
  expect(reuseColumnMapping(inspection, inspection, mapping)).toEqual(mapping)
  expect(reuseColumnMapping(inspection, inspection, { ...mapping, denominator: 'c1' })?.denominator).toBe('c1')
})

const dualInspection: InspectionResponse = { ...inspection, columns: ['energy', 'i0', 'it', 'if1', 'if2'].map((name, index) => ({
  ...inspection.columns[0], name, index, column_id: `c${index}`,
})) }
const transmission: ColumnMapping = { ...previous, mode: 'transmission', energy_column: 'c0', numerator: ['c1'], denominator: 'c2',
  reference_numerator: '', reference_denominator: '', signal_multiplier: 1, invert: false }

it('adds an independent fluorescence recipe without changing reviewed transmission or shared settings', () => {
  const mapping = { ...transmission, units: 'keV' as const, signal_multiplier: 2, invert: true,
    rebin: { ...defaultRebin, enabled: true }, preprocessing: { mark: true, standard_id: 'std', align: true, copy_parameters: true } }
  const dual = setDualMode(mapping, dualInspection, true)
  expect(dual).toEqual({ ...mapping, additional_fluorescence: { numerator: ['c3'], denominator: 'c1',
    individual_channels: false, signal_multiplier: 1, invert: false } })
  expect(columnProblem(dual)).toBeNull()
  expect(setDualMode(dual, dualInspection, false)).toEqual(mapping)
})

it('keeps existing fluorescence choices when adding transmission and respects reader suggestions', () => {
  const mapping: ColumnMapping = { ...transmission, mode: 'fluorescence', numerator: ['c3', 'c4'], denominator: ['c1'],
    individual_channels: true, signal_multiplier: 3, invert: true }
  const dual = setDualMode(mapping, { ...dualInspection, plugin_suggestions: {
    transmission: { ...inspection.athena_suggestion!, numerator: ['c2'], denominator: 'c1' },
  } }, true)
  expect(dual).toMatchObject({ mode: 'transmission', numerator: ['c2'], denominator: 'c1', individual_channels: false,
    signal_multiplier: 1, invert: false, additional_fluorescence: { numerator: ['c3', 'c4'], denominator: ['c1'],
      individual_channels: true, signal_multiplier: 3, invert: true } })
  expect(columnPayload(dual).additional_fluorescence?.denominator).toBe('c1')
})

it('requires explicit channels for both modes and a finite independent fluorescence scale', () => {
  const missing = setDualMode(transmission, inspection, true)
  expect(missing.additional_fluorescence?.numerator).toEqual([])
  expect(columnProblem(missing)).toMatch(/fluorescence signal and I₀/)
  const dual = setDualMode(transmission, dualInspection, true)
  expect(columnProblem({ ...dual, denominator: '' })).toMatch(/transmission/)
  expect(columnProblem({ ...dual, mode: 'mu' })).toMatch(/Both modes/)
  for (const signal_multiplier of ['', Infinity] as const) expect(columnProblem({ ...dual,
    additional_fluorescence: { ...dual.additional_fluorescence!, signal_multiplier } })).toMatch(/fluorescence multiplicative constant/)
  expect(columnProblem({ ...transmission, numerator: [], denominator: '' })).toBeNull()
})

it('resets dual mode for chi and new layouts, restores remembered dual settings, and remaps both modes in a batch', () => {
  const dual = setDualMode(transmission, dualInspection, true)
  expect(changeInputType(dual, 'chi').additional_fluorescence).toBeNull()
  expect(initialColumnMapping(inspection, dual).additional_fluorescence).toBeUndefined()
  const remembered = { ...dualInspection, remembered_columns: { version: 1, matching_columns: true, mapping: dual, warnings: [] } }
  expect(initialColumnMapping(remembered, transmission).additional_fluorescence).toEqual(dual.additional_fluorescence)
  const target = { ...dualInspection, columns: dualInspection.columns.map(c => ({ ...c, column_id: `new-${c.index}` })) }
  const reused = reuseColumnMapping(dualInspection, target, dual)
  expect(reused).toMatchObject({ numerator: ['new-1'], denominator: 'new-2', additional_fluorescence: {
    numerator: ['new-3'], denominator: 'new-1', signal_multiplier: 1,
  } })
  expect(reuseColumnMapping(dualInspection, { ...target, columns: target.columns.slice(0, 3) }, dual)).toBeNull()
})

const threeInspection: InspectionResponse = { ...inspection, columns: ['energy', 'I0', 'It', 'If', 'Iref'].map((name, index) => ({
  ...inspection.columns[0], name, index, column_id: `c${index}`,
})) }

it('defaults the three detector checkboxes to checked while retaining reviewed signal choices', () => {
  const reviewed: ColumnMapping = { ...transmission, mode: 'fluorescence', numerator: ['c3'], denominator: ['c1'],
    signal_multiplier: 2, reference_numerator: 'c4', reference_denominator: 'c2', reference_log: false }
  const prepared = prepareImportSignals(reviewed, threeInspection)
  expect(prepared).toMatchObject({ import_signals: { transmission: true, fluorescence: true, reference: true },
    additional_fluorescence: { numerator: ['c3'], denominator: ['c1'], signal_multiplier: 2 },
    reference_numerator: 'c4', reference_denominator: 'c2', reference_log: false })
  const choices = { ...prepared, import_signals: { transmission: false, fluorescence: true, reference: false } }
  expect(prepareImportSignals(choices, threeInspection)).toBe(choices)
  const incomplete = prepareImportSignals(transmission, inspection)
  expect(incomplete.import_signals).toEqual({ transmission: true, fluorescence: true, reference: true })
  expect(columnProblem(incomplete)).toMatch(/fluorescence signal/)
})

it.each([true, false])('restores a remembered reference-only ratio to Reference before defaulting all three signals (log=%s)', reference_log => {
  const onlyReference = { ...prepareImportSignals(transmission, threeInspection), reference_log,
    import_signals: { transmission: false, fluorescence: false, reference: true } }
  // The server remembers the submitted primary recipe, then removes the
  // per-import reference designation before returning remembered columns.
  const { is_reference: _reference, ...saved } = selectedColumnMapping(onlyReference)
  const next: InspectionResponse = { ...threeInspection, remembered_columns: {
    version: 1, matching_columns: true, mapping: saved, warnings: [], primary_is_reference: true,
  } }
  const restored = prepareImportSignals(initialColumnMapping(next, onlyReference), next)
  expect(restored).toMatchObject({ import_signals: { transmission: true, fluorescence: true, reference: true },
    mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1' },
    reference_numerator: 'c2', reference_denominator: 'c4', reference_log })
  expect(columnProblem(restored)).toBeNull()
  expect(columnPayload(restored)).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    reference_numerator: 'c2', reference_denominator: 'c4', reference_log })
})

it('uses remembered reference provenance for custom ratios without restoring the sample reference flag', () => {
  const onlyReference: ColumnMapping = { ...prepareImportSignals(transmission, threeInspection),
    reference_numerator: 'c3', reference_denominator: '1', reference_log: false,
    import_signals: { transmission: false, fluorescence: false, reference: true } }
  const { is_reference: _reference, ...saved } = selectedColumnMapping(onlyReference)
  const next: InspectionResponse = { ...threeInspection, remembered_columns: {
    version: 1, matching_columns: true, mapping: saved, warnings: [], primary_is_reference: true,
  } }
  const restored = prepareImportSignals(initialColumnMapping(next, onlyReference), next)
  expect(restored).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1' },
    reference_numerator: 'c3', reference_denominator: '1', reference_log: false, is_reference: false })
  expect(columnPayload(restored)).not.toHaveProperty('is_reference')
  expect(columnPayload(restored)).not.toHaveProperty('primary_is_reference')
})

it('recognizes a reversed reference-only recipe from older server column memory', () => {
  const saved: ColumnMapping = { ...transmission, numerator: ['c4'], denominator: 'c2' }
  const next: InspectionResponse = { ...threeInspection, remembered_columns: {
    version: 1, matching_columns: true, mapping: saved, warnings: [],
  } }
  const restored = prepareImportSignals(initialColumnMapping(next, transmission), next)
  expect(restored).toMatchObject({ numerator: ['c1'], denominator: 'c2',
    reference_numerator: 'c4', reference_denominator: 'c2', reference_log: true,
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1' } })
})

it.each([undefined, true])('preserves explicit combined recipes even when their primary was marked as reference (%s)', primary_is_reference => {
  for (const extra of [
    { additional_fluorescence: { numerator: ['c3'], denominator: ['c1'], signal_multiplier: .5, individual_channels: true } },
    { reference_numerator: 'c2', reference_denominator: 'c4' },
  ]) {
    const saved: ColumnMapping = { ...transmission, numerator: ['c4'], denominator: 'c2', ...extra }
    const next: InspectionResponse = { ...threeInspection, remembered_columns: {
      version: 1, matching_columns: true, mapping: saved, warnings: [], primary_is_reference,
    } }
    const restored = prepareImportSignals(initialColumnMapping(next, transmission), next)
    expect(restored).toMatchObject({ numerator: ['c4'], denominator: 'c2', ...extra })
  }
})

it.each([
  [true, true, true, 3, 'transmission', ['c1'], 'c2'],
  [true, true, false, 2, 'transmission', ['c1'], 'c2'],
  [true, false, true, 2, 'transmission', ['c1'], 'c2'],
  [true, false, false, 1, 'transmission', ['c1'], 'c2'],
  [false, true, true, 2, 'fluorescence', ['c3'], 'c1'],
  [false, true, false, 1, 'fluorescence', ['c3'], 'c1'],
  [false, false, true, 1, 'transmission', ['c2'], 'c4'],
] as const)('submits only checked signals (transmission=%s, fluorescence=%s, reference=%s)', (t, f, r, count, mode, numerator, denominator) => {
  const mapping = { ...prepareImportSignals(transmission, threeInspection), is_reference: r,
    import_signals: { transmission: t, fluorescence: f, reference: r } }
  const body = columnPayload(mapping)
  expect(body).toMatchObject({ mode, numerator, denominator,
    reference_numerator: r && (t || f) ? 'c2' : null,
    reference_denominator: r && (t || f) ? 'c4' : null })
  expect(!!body.additional_fluorescence).toBe(t && f)
  expect(!!body.is_reference).toBe(!t && !f && r)
  expect(body).not.toHaveProperty('import_signals')
  expect(selectedColumnMapping(mapping)).not.toHaveProperty('import_signals')
  expect(columnProblem(mapping)).toBeNull()
  expect(importSpectrumCount(mapping)).toBe(count)
  // Lowering leaves unchecked recipes available to turn on again.
  expect(mapping.additional_fluorescence?.numerator).toEqual(['c3'])
  expect(mapping.reference_denominator).toBe('c4')
})

it('blocks empty selection and validates only the selected recipes', () => {
  const mapping = prepareImportSignals(transmission, threeInspection)
  const none = { ...mapping, import_signals: { transmission: false, fluorescence: false, reference: false } }
  expect(columnProblem(none)).toBe('Choose at least one signal to import.')
  expect(importSpectrumCount(none)).toBe(0)
  expect(batchCapacityWarning(none, threeInspection, [], 200)).toBeNull()
  const onlyFluorescence: ColumnMapping = { ...mapping, numerator: [], denominator: '', signal_multiplier: '',
    reference_numerator: '', reference_denominator: '', import_signals: { transmission: false, fluorescence: true, reference: false } }
  expect(columnProblem(onlyFluorescence)).toBeNull()
  expect(columnPayload(onlyFluorescence)).toMatchObject({ mode: 'fluorescence', signal_multiplier: 1 })
  expect(columnProblem({ ...onlyFluorescence, import_signals: { ...onlyFluorescence.import_signals!, transmission: true } })).toMatch(/transmission numerator/)
  expect(columnProblem({ ...onlyFluorescence, import_signals: { ...onlyFluorescence.import_signals!, reference: true } })).toMatch(/reference numerator/)
  expect(columnProblem({ ...onlyFluorescence, additional_fluorescence: null })).toMatch(/fluorescence signal/)
  expect(columnProblem({ ...onlyFluorescence, additional_fluorescence: { numerator: ['c3'], denominator: 'c1', signal_multiplier: '' } })).toMatch(/fluorescence multiplicative/)
  expect(columnProblem({ ...mapping, additional_fluorescence: { numerator: [], denominator: '', signal_multiplier: '' },
    import_signals: { transmission: true, fluorescence: false, reference: false } })).toBeNull()
})

it('imports the reference alone using its ratio, logarithm and reference identity', () => {
  const mapping: ColumnMapping = { ...prepareImportSignals(transmission, threeInspection), signal_multiplier: '',
    invert: true, individual_channels: true, reference_numerator: '1', reference_log: false,
    import_signals: { transmission: false, fluorescence: false, reference: true } }
  expect(columnProblem(mapping)).toBeNull()
  expect(columnPayload(mapping)).toMatchObject({ mode: 'fluorescence', numerator: ['1'], denominator: 'c4',
    signal_multiplier: 1, invert: false, individual_channels: false, is_reference: true,
    additional_fluorescence: null, reference_numerator: null, reference_denominator: null })
  const implicitConstant = { ...mapping, reference_numerator: '', reference_denominator: 'c4' }
  expect(columnProblem(implicitConstant)).toBeNull()
  expect(columnPayload(implicitConstant)).toMatchObject({ numerator: [], denominator: 'c4' })
  expect(columnProblem({ ...implicitConstant, reference_denominator: '' })).toMatch(/reference numerator/)
  expect(columnPayload({ ...mapping, reference_numerator: 'c4', reference_denominator: '1' })).toMatchObject({ numerator: ['c4'], denominator: '1' })
})

it('retains direct signal and constant arithmetic when just one detector recipe is checked', () => {
  const mapping = prepareImportSignals(transmission, threeInspection)
  const primary: ColumnMapping = { ...mapping, mode: 'fluorescence', numerator: [], denominator: '',
    import_signals: { transmission: true, fluorescence: false, reference: false } }
  expect(columnProblem(primary)).toBeNull()
  expect(columnPayload(primary)).toMatchObject({ mode: 'fluorescence', numerator: [], denominator: null })
  const fluorescence = { ...mapping, additional_fluorescence: { numerator: ['c3'], denominator: '' },
    import_signals: { transmission: false, fluorescence: true, reference: false } }
  expect(columnProblem(fluorescence)).toBeNull()
  expect(columnPayload(fluorescence)).toMatchObject({ mode: 'fluorescence', numerator: ['c3'], denominator: null })
  expect(columnProblem({ ...fluorescence, import_signals: { ...fluorescence.import_signals, transmission: true } })).toMatch(/fluorescence signal/)
})

it('keeps direct absorption, extracted chi, calculations and foil choices outside the three-detector defaults', () => {
  for (const mapping of [{ ...transmission, mode: 'mu' as const }, { ...transmission, data_type: 'chi' as const },
    { ...transmission, data_type: 'xmudat' as const }, { ...transmission, is_reference: true }]) {
    expect(prepareImportSignals(mapping, threeInspection)).toBe(mapping)
  }
  for (const evidence of [{ ambiguous: true }, { foil_spectrum: true }]) {
    const input: InspectionResponse = { ...threeInspection, beamline_reader: {
      id: 'test', name: 'Synthetic reader', facility: 'Test', beamline: 'Test', format: 'text', evidence: 'header', confidence: 'beamline',
      measurement: { mode: 'transmission', edge_energy: 9000, contrast: {}, notes: [], ...evidence },
    } }
    expect(prepareImportSignals(transmission, input)).toBe(transmission)
  }
  const prepared = prepareImportSignals(transmission, threeInspection)
  expect(changeInputType(prepared, 'chi')).not.toHaveProperty('import_signals')
  expect(changeInputType(prepared, 'xmudat')).not.toHaveProperty('import_signals')
  expect(columnPayload(changeInputType(prepared, 'xmudat'))).toMatchObject({ mode: 'mu', numerator: ['c1'], denominator: null,
    additional_fluorescence: null, reference_numerator: null, reference_denominator: null })
  expect(initialColumnMapping(inspection, prepared)).not.toHaveProperty('import_signals')
})

it('remaps checked and unchecked recipes in a batch and ignores unused nonnumeric detectors', () => {
  const mapping = { ...prepareImportSignals(transmission, threeInspection),
    import_signals: { transmission: false, fluorescence: true, reference: false } }
  const next = { ...threeInspection, columns: threeInspection.columns.map(c => ({ ...c, column_id: `next-${c.index}` })) }
  expect(reuseColumnMapping(threeInspection, next, mapping)).toMatchObject({ import_signals: mapping.import_signals,
    numerator: ['next-1'], denominator: 'next-2', additional_fluorescence: { numerator: ['next-3'], denominator: 'next-1' },
    reference_numerator: 'next-2', reference_denominator: 'next-4' })
  const unusedBroken = { ...next, columns: next.columns.map(c => [2, 4].includes(c.index) ? { ...c, numeric: false } : c) }
  const reused = reuseColumnMapping(threeInspection, unusedBroken, mapping)
  expect(reused).not.toBeNull()
  expect(columnPayload(reused!)).toMatchObject({ mode: 'fluorescence', numerator: ['next-3'], denominator: 'next-1' })
  expect(reuseColumnMapping(threeInspection, { ...next, columns: next.columns.map(c => c.index === 3 ? { ...c, numeric: false } : c) }, mapping)).toBeNull()
  const onlyReference = { ...mapping, import_signals: { transmission: false, fluorescence: false, reference: true } }
  expect(reuseColumnMapping(threeInspection, next, onlyReference)?.import_signals).toEqual(onlyReference.import_signals)
  expect(batchCapacityWarning(onlyReference, threeInspection, [], 100)).toBeNull()
  expect(batchCapacityWarning(onlyReference, threeInspection, [], 101)).toMatch(/101 data \(1 per file/)
})

it('defaults complete detector files to transmission, fluorescence and one It/Iref reference', () => {
  const selected = initialColumnMapping(threeInspection, previous)
  expect(columnPayload(selected)).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1', signal_multiplier: 1, invert: false },
    reference_numerator: 'c2', reference_denominator: 'c4', reference_log: true })
  expect(columnProblem(selected)).toBeNull()
  const fluorescent = { ...threeInspection, athena_suggestion: { ...threeInspection.athena_suggestion!,
    mode: 'fluorescence' as const, numerator: ['c3'], denominator: 'c1' } }
  expect(initialColumnMapping(fluorescent, previous)).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1' }, reference_numerator: 'c2', reference_denominator: 'c4' })
})

it('recognizes a unique ref label as Iref and declines competing reference aliases', () => {
  const input = { ...threeInspection, columns: threeInspection.columns.map(c => c.index === 4 ? { ...c, name: 'ref' } : c) }
  expect(setThreeMode(transmission, input)).toMatchObject({ reference_numerator: 'c2', reference_denominator: 'c4', reference_log: true })
  expect(initialColumnMapping(input, previous)).toMatchObject({ additional_fluorescence: { numerator: ['c3'] }, reference_denominator: 'c4' })
  const competing = { ...input, columns: [...input.columns, { ...input.columns[4], index: 5, column_id: 'c5', name: 'Iref' }] }
  expect(setThreeMode(transmission, competing).reference_denominator).toBe('')
  expect(initialColumnMapping(competing, previous).additional_fluorescence).toBeUndefined()
})

it('uses reader suggestions and detector roles for columns whose labels do not name the detectors', () => {
  const input: InspectionResponse = { ...threeInspection,
    columns: threeInspection.columns.map(c => ({ ...c, name: `channel ${c.index}` })),
    beamline_reader: { id: 'test', name: 'Synthetic reader', facility: 'Test', beamline: 'Test', format: 'text',
      evidence: 'header', confidence: 'beamline',
      roles: { i0: 'c1', transmission: 'c2', fluorescence: ['c3'], reference: 'c4' },
      suggestions: { transmission: threeInspection.athena_suggestion!,
        fluorescence: { ...threeInspection.athena_suggestion!, mode: 'fluorescence', numerator: ['c3'], denominator: 'c1' } },
      reference: { numerator: 'c2', denominator: 'c4', log: true, default: true },
    } }
  expect(initialColumnMapping(input, previous)).toMatchObject({ additional_fluorescence: { numerator: ['c3'], denominator: 'c1' },
    reference_numerator: 'c2', reference_denominator: 'c4' })
  expect(setThreeMode(transmission, { ...input, beamline_reader: { ...input.beamline_reader!, reference: undefined } })).toMatchObject({
    reference_numerator: 'c2', reference_denominator: 'c4', reference_log: true })
})

it('preserves reviewed fluorescence and reference choices when adding all three modes', () => {
  const reviewed: ColumnMapping = { ...transmission, mode: 'fluorescence', numerator: ['c3'], denominator: ['c1'],
    signal_multiplier: 2, reference_numerator: 'c4', reference_denominator: 'c2', reference_log: false }
  expect(setThreeMode(reviewed, threeInspection)).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3'], denominator: ['c1'], signal_multiplier: 2 },
    reference_numerator: 'c4', reference_denominator: 'c2', reference_log: false })
  expect(setThreeMode(changeInputType(reviewed, 'chi'), threeInspection).additional_fluorescence).toBeUndefined()
})

it('leaves missing, nonnumeric and ambiguous reference detectors for the user to select', () => {
  const missing = { ...threeInspection, columns: threeInspection.columns.slice(0, 4) }
  expect(setThreeMode(transmission, missing).reference_denominator).toBe('')
  const ambiguous = { ...threeInspection, columns: [...threeInspection.columns,
    { ...threeInspection.columns[4], index: 5, column_id: 'c5', name: 'Iref' }] }
  expect(setThreeMode(transmission, ambiguous).reference_denominator).toBe('')
  const nonnumeric = { ...threeInspection, columns: threeInspection.columns.map(c => c.index === 4 ? { ...c, numeric: false } : c) }
  for (const input of [missing, ambiguous, nonnumeric,
    { ...threeInspection, columns: threeInspection.columns.filter(c => c.index !== 3) },
    { ...threeInspection, columns: threeInspection.columns.map(c => c.index === 3 ? { ...c, name: 'unknown signal' } : c) },
  ]) expect(initialColumnMapping(input, previous).additional_fluorescence).toBeUndefined()
})

it('does not reinterpret direct absorption, chi or foil-only and ambiguous beamline scans as three measurements', () => {
  for (const data_type of ['mu', 'chi', 'xmudat'] as const) {
    const input = { ...threeInspection, athena_suggestion: { ...threeInspection.athena_suggestion!, mode: 'mu' as const, data_type } }
    expect(initialColumnMapping(input, previous).additional_fluorescence).toBeUndefined()
  }
  for (const evidence of [{ ambiguous: true }, { foil_spectrum: true }]) {
    const input: InspectionResponse = { ...threeInspection, beamline_reader: {
      id: 'test', name: 'Synthetic reader', facility: 'Test', beamline: 'Test', format: 'text', evidence: 'header', confidence: 'beamline',
      measurement: { mode: 'transmission', edge_energy: 9000, contrast: {}, notes: [], ...evidence },
    } }
    expect(initialColumnMapping(input, previous).additional_fluorescence).toBeUndefined()
  }
})

it('preserves matching remembered single-mode choices while applying three-mode defaults to a new layout', () => {
  const remembered = { ...threeInspection, remembered_columns: { version: 1, matching_columns: true, mapping: transmission, warnings: [] } }
  expect(initialColumnMapping(remembered, previous).additional_fluorescence).toBeUndefined()
  expect(initialColumnMapping(remembered, previous).reference_denominator).toBe('')
  expect(initialColumnMapping({ ...remembered, remembered_columns: { ...remembered.remembered_columns, matching_columns: false } }, previous))
    .toMatchObject({ additional_fluorescence: { numerator: ['c3'], denominator: 'c1' }, reference_denominator: 'c4' })
})

it('remaps all three measurements together and refuses a changed reference column', () => {
  const mapping = setThreeMode(transmission, threeInspection)
  const next = { ...threeInspection, columns: threeInspection.columns.map(c => ({ ...c, column_id: `next-${c.index}` })) }
  expect(reuseColumnMapping(threeInspection, next, mapping)).toMatchObject({ numerator: ['next-1'], denominator: 'next-2',
    additional_fluorescence: { numerator: ['next-3'], denominator: 'next-1' }, reference_numerator: 'next-2', reference_denominator: 'next-4' })
  expect(reuseColumnMapping(threeInspection, { ...next, columns: next.columns.map(c => c.index === 4 ? { ...c, name: 'other signal' } : c) }, mapping)).toBeNull()
})

it('imports the reference channel a recognized beamline file carries, unless its data show no edge', () => {
  // The registry named It/Iref, but the browser cleared it on every file.
  const reader = { id: 'aps-xsd-labview', name: 'LabVIEW', facility: 'APS', beamline: '20-BM', format: 'LabVIEW', evidence: '',
    confidence: 'beamline' as const, reference: { numerator: 'c2', denominator: 'c1', log: true, default: true } }
  const recognized = { ...inspection, beamline_reader: reader }
  expect(initialColumnMapping(recognized, previous)).toMatchObject({ reference_numerator: 'c2', reference_denominator: 'c1', reference_log: true })
  for (const unconfirmed of [false, undefined]) {
    const offered = { ...inspection, beamline_reader: { ...reader, reference: { ...reader.reference, default: unconfirmed } } }
    expect(initialColumnMapping(offered, previous)).toMatchObject({ reference_numerator: '', reference_denominator: '' })
  }
})

it('leaves counters, logs, alignment scans and companion detector files out of a folder batch', () => {
  // A companion detector file belongs to the series even without matching text.
  const names = ['sample_Cu_EXAFS.0003', 'sample_Cu_EXAFS.0003.hdf5', 'sample_Cu_EXAFS.last',
    'Sequence log 1 Jan 2026 01 00 00 PM', 'align.0002', 'sample1_align_Mn.0001', 'Cu_foil.0001', 'lonely.hdf5',
    'sample_Cu_EXAFS.0001.hdf5']
  expect([...batchExclusions(names).keys()]).toEqual([1, 2, 3, 4, 5, 8])
  expect(batchExclusions(['scan.last'])).toEqual(new Map())
  expect(batchExclusions(['a.last', 'b.last'])).toEqual(new Map())
})

it('warns before a series batch that cannot fit the project, saying how many files fit', () => {
  // The server refused the import crossing 100 groups, part-way through.
  const mapping: ColumnMapping = { ...previous, energy_column: 'c0', numerator: ['c1'], denominator: 'c2', mode: 'transmission',
    reference_numerator: 'c2', reference_denominator: 'c1', additional_fluorescence: null, individual_channels: false }
  const existing = Array.from({ length: 50 }, () => ({ energy: [1, 2], source: {} }) as unknown as AthenaGroup)
  expect(batchCapacityWarning(mapping, inspection, existing, 29)).toBe(
    'This batch would bring the project to 108 data (2 per file, counting each reference); a project holds at most 100. '
    + 'Only the first 25 of these 29 files fit: import the series into its own new project, or choose fewer files.')
  expect(batchCapacityWarning(mapping, inspection, [], 29)).toBeNull()
})

it('counts one shared reference with both measurements and every individual fluorescence channel', () => {
  const mapping = setThreeMode(transmission, threeInspection)
  expect(batchCapacityWarning(mapping, threeInspection, [], 33)).toBeNull()
  expect(batchCapacityWarning(mapping, threeInspection, [], 34)).toMatch(/102 data \(3 per file/)
  expect(batchCapacityWarning(mapping, { ...threeInspection, row_count: 40_000 }, [], 2)).toBeNull()
  expect(batchCapacityWarning(mapping, { ...threeInspection, row_count: 50_000 }, [], 2)).toMatch(/about 2\.5 million stored values/)
  const channels: ColumnMapping = { ...mapping,
    additional_fluorescence: { ...mapping.additional_fluorescence!, numerator: ['c3', 'c5'], individual_channels: true } }
  expect(batchCapacityWarning(channels, threeInspection, [], 25)).toBeNull()
  expect(batchCapacityWarning(channels, threeInspection, [], 26)).toMatch(/104 data \(4 per file/)
  expect(batchCapacityWarning({ ...channels, reference_numerator: '', reference_denominator: '' }, threeInspection, [], 34)).toMatch(/102 data \(3 per file/)
  // A single-mode individual import keeps its historical per-sample references.
  expect(batchCapacityWarning({ ...mapping, additional_fluorescence: null, numerator: ['c1', 'c3'], individual_channels: true },
    threeInspection, [], 26)).toMatch(/104 data \(4 per file/)
})
