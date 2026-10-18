import "@testing-library/jest-dom/vitest"
import { useState } from "react"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import type { ColumnMapping } from "@/lib/athena-import"
import type { InspectionResponse } from "@/lib/contracts"
import { columnPayload, defaultRebin, numeratorRange, prepareImportSignals } from "@/lib/athena-import"
import { AthenaColumnSelection } from "./athena-column-selection"
import { InstructionVisibility } from "./section-help"

vi.mock("./athena-import-preview", () => ({ AthenaImportPreview: () => <div /> }))
vi.mock("@/lib/athena", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/athena")>(),
  athenaDownload: vi.fn(),
}))
afterEach(() => { cleanup(); vi.unstubAllEnvs() })
const columns = ["energy", "i0", "it", "detA", "detB", "ref"].map((name, index) => ({ name, index, column_id: `c${index}`,
  numeric: true, unit: null, role_hint: null, preview: [1, 2, 3] }))
const initial: ColumnMapping = { energy_column: "c0", numerator: ["c1"], denominator: "c2", mode: "transmission", units: "eV",
  data_type: "mu", reference_numerator: "", reference_denominator: "", sort: false }
function Harness({ busy = false, columnUnits, inspection = {}, remaining = 1, initialMapping = initial, replacement = false }: { busy?: boolean; columnUnits?: Record<string, "eV" | "keV" | null>; inspection?: Partial<InspectionResponse>; remaining?: number; initialMapping?: ColumnMapping; replacement?: boolean }) {
  const [mapping, setMapping] = useState(() => replacement ? initialMapping : prepareImportSignals(initialMapping, {
    display_name: 'columns.dat', upload_id: 'u', row_count: 3, columns, warnings: [], issues: [], ...inspection,
  }))
  const [reuseMapping, setReuseMapping] = useState<boolean | null>(null)
  return <><AthenaColumnSelection projectId="p" version={0} inspection={{ display_name: "columns.dat", upload_id: "u", row_count: 3,
    columns, column_units: columnUnits, warnings: [], issues: [], source_preview: "# Original beamline headers", source_preview_truncated: true, ...inspection }}
    mapping={mapping} setMapping={setMapping} busy={busy} remaining={remaining} reuseMapping={reuseMapping} setReuseMapping={setReuseMapping}
    chooseAnother={() => {}} importCurrent={() => {}} replacement={replacement} /><output data-testid="mapping">{JSON.stringify(mapping)}</output></>
}
function accepted(): ColumnMapping { return JSON.parse(screen.getByTestId("mapping").textContent!) }
function selectSignals(...signals: string[]) {
  for (const name of ['Transmission', 'Fluorescence', 'Reference']) {
    const checkbox = screen.getByRole('checkbox', { name: `Import ${name}` })
    if ((checkbox as HTMLInputElement).checked !== signals.includes(name)) fireEvent.click(checkbox)
  }
}
it('shows field instructions on demand without changing column selections or field names', () => {
  const { rerender } = render(<InstructionVisibility.Provider value={false}><Harness /></InstructionVisibility.Provider>)
  expect(screen.queryByRole('button', { name: 'About Multiplicative constant' })).not.toBeInTheDocument()
  const before = accepted()
  rerender(<InstructionVisibility.Provider value><Harness /></InstructionVisibility.Provider>)
  const help = screen.getByRole('button', { name: 'About Multiplicative constant' })
  fireEvent.focus(help)
  expect(screen.getByRole('tooltip')).toHaveTextContent('Scale the calculated absorption signal')
  expect(screen.getByLabelText('Multiplicative constant')).toHaveValue(1)
  expect(screen.getByLabelText('Input already normalized')).not.toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'About Input already normalized' }))
  expect(screen.getByLabelText('Input already normalized')).not.toBeChecked()
  expect(accepted()).toEqual(before)
  rerender(<InstructionVisibility.Provider value={false}><Harness /></InstructionVisibility.Provider>)
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'About Multiplicative constant' })).not.toBeInTheDocument()
})
it('offers normalization with automatic EXAFS processing for new absorption imports', () => {
  render(<Harness />)
  expect(screen.getByLabelText('Input format')).toHaveValue('mu')
  expect(screen.queryByRole('option', { name: /XANES/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('option', { name: 'Normalized μ(E)' })).not.toBeInTheDocument()
  expect(screen.getByLabelText('Input already normalized')).not.toBeChecked()
  expect(screen.queryByLabelText('Enable EXAFS processing')).not.toBeInTheDocument()

  fireEvent.click(screen.getByLabelText('Input already normalized'))
  expect(accepted()).toMatchObject({ data_type: 'norm', is_normalized: true, exafs: null })
  expect(screen.getByLabelText('Input already normalized')).toBeChecked()
  expect(screen.getByLabelText('Input format')).toHaveValue('mu')

  fireEvent.click(screen.getByLabelText('Input already normalized'))
  expect(accepted()).toMatchObject({ data_type: 'mu', is_normalized: false, exafs: null, numerator: initial.numerator, denominator: initial.denominator })
})
it('keeps ordinary import focused on columns while retaining ordering and source warnings', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions, warnings: ['Check the energy units.'] }} />)
  for (const text of ['Rebin quick scans', 'Preprocess imported data', 'Reader columns']) {
    expect(screen.queryByText(text)).not.toBeInTheDocument()
  }
  for (const label of ['Perform rebinning', 'Preprocessing standard', 'Mark each imported sample']) {
    expect(screen.queryByLabelText(label)).not.toBeInTheDocument()
  }
  expect(screen.queryByRole('button', { name: 'Use transmission columns' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Use fluorescence columns' })).not.toBeInTheDocument()
  expect(screen.getByText('Check the energy units.')).toBeVisible()
  fireEvent.click(screen.getByText('Ordering', { exact: true }))
  fireEvent.click(screen.getByLabelText('Sort ascending by energy (rows at a repeated energy are averaged)'))
  expect(accepted().sort).toBe(true)
})
it('retains rebin controls when rebuilding an existing rebinned spectrum from its original columns', () => {
  render(<Harness replacement initialMapping={{ ...initial, rebin: { ...defaultRebin, enabled: true, pre: 7 } }} />)
  fireEvent.click(screen.getByText('Rebin quick scans'))
  expect(screen.getByLabelText('Perform rebinning')).toBeChecked()
  expect(screen.getByLabelText('Rebin pre-edge step · eV')).toHaveValue(7)
  fireEvent.change(screen.getByLabelText('Rebin pre-edge step · eV'), { target: { value: '5' } })
  expect(accepted().rebin!.pre).toBe(5)
  expect(screen.queryByText('Preprocess imported data')).not.toBeInTheDocument()
})
it('omits obsolete preprocessing-standard advice while retaining remembered column warnings', () => {
  const obsolete = 'The remembered preprocessing standard is missing or unusable. Choose a standard to copy parameters or align.'
  render(<Harness inspection={{ remembered_columns: { version: 1, matching_columns: true, mapping: initial,
    warnings: [obsolete, 'The saved detector labels changed.'] } }} />)
  expect(screen.queryByText(obsolete)).not.toBeInTheDocument()
  expect(screen.getByText('The saved detector labels changed.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Use suggested columns' })).toBeEnabled()
})
it('keeps normalization independent of the explicit EXAFS choice when replacing columns', () => {
  render(<Harness replacement />)
  expect(screen.getByLabelText('Enable EXAFS processing')).toBeChecked()
  fireEvent.click(screen.getByLabelText('Input already normalized'))
  expect(accepted()).toMatchObject({ data_type: 'norm', is_normalized: true, exafs: true })
  fireEvent.click(screen.getByLabelText('Enable EXAFS processing'))
  expect(accepted()).toMatchObject({ data_type: 'xanes', is_normalized: true, exafs: false })
  fireEvent.click(screen.getByLabelText('Input already normalized'))
  expect(accepted()).toMatchObject({ data_type: 'xanes', is_normalized: false, exafs: false })
  expect(screen.getByLabelText('Enable EXAFS processing')).not.toBeChecked()
  fireEvent.click(screen.getByLabelText('Enable EXAFS processing'))
  expect(accepted()).toMatchObject({ ...initial, is_normalized: false })
})
it.each([
  ['xanes', undefined, false, false],
  ['xanes', true, true, false],
  ['norm', undefined, true, true],
] as const)('restores existing %s processing choices without changing the absorption format', (data_type, is_normalized, normalized, exafs) => {
  render(<Harness replacement initialMapping={{ ...initial, data_type, is_normalized }} />)
  expect(screen.getByLabelText('Input format')).toHaveValue('mu')
  expect(screen.getByLabelText('Input already normalized')).toHaveProperty('checked', normalized)
  expect(screen.getByLabelText('Enable EXAFS processing')).toHaveProperty('checked', exafs)
})
it('limits replacement to one existing group while retaining column, signal and ordering choices', () => {
  render(<Harness replacement />)
  expect(screen.getByRole('button', { name: 'Apply column changes' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled()
  expect(screen.queryByRole('option', { name: 'Transmission + fluorescence' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Save each channel as a separate data item')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('reference numerator')).not.toBeInTheDocument()
  expect(screen.queryByText('Reference channel & ordering')).not.toBeInTheDocument()
  expect(screen.queryByText('Preprocessing')).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Numerator detA'))
  fireEvent.click(screen.getByLabelText('Sort ascending by energy (rows at a repeated energy are averaged)'))
  expect(accepted()).toMatchObject({ numerator: ['c1', 'c3'], sort: true })
})
it('locks replacement controls and cancel while applying changes', () => {
  render(<Harness replacement busy />)
  expect(screen.getByRole('button', { name: 'Applying…' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  expect(screen.getByLabelText('Numerator detA')).toBeDisabled()
})
const readerSuggestions: InspectionResponse['plugin_suggestions'] = {
  transmission: { energy_column: 'c0', numerator: ['c1'], denominator: 'c2', mode: 'transmission', units: 'eV', data_type: 'mu' },
  fluorescence: { energy_column: 'c0', numerator: ['c3'], denominator: 'c1', mode: 'fluorescence', units: 'eV', data_type: 'mu' },
}
it('uses the Reference signal choice without a duplicate reference checkbox', () => {
  const { rerender } = render(<Harness />)
  expect(screen.queryByRole('checkbox', { name: 'This is reference' })).not.toBeInTheDocument()
  selectSignals('Reference')
  expect(columnPayload(accepted()).is_reference).toBe(true)
  rerender(<Harness replacement />)
  expect(screen.queryByRole('checkbox', { name: 'This is reference' })).not.toBeInTheDocument()
})
it('defaults detector imports to all three checked signals without a Measurement menu', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  expect(screen.queryByLabelText('Measurement')).not.toBeInTheDocument()
  for (const name of ['Transmission', 'Fluorescence', 'Reference']) {
    expect(screen.getByRole('checkbox', { name: `Import ${name}` })).toBeChecked()
  }
  expect(screen.getByRole('button', { name: 'Import 3 spectra' })).toBeEnabled()
  expect(columnPayload(accepted())).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1' }, reference_numerator: 'c2', reference_denominator: 'c5' })
})
it('uses named detector columns for the independent fluorescence recipe', () => {
  render(<Harness inspection={{ columns: columns.map(c => c.column_id === 'c3' ? { ...c, name: 'If' } : c) }} />)
  selectSignals('Fluorescence')
  expect(columnPayload(accepted())).toMatchObject({ mode: 'fluorescence', numerator: ['c3'], denominator: 'c1' })
  selectSignals('Transmission')
  expect(columnPayload(accepted())).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2' })
})
it('preserves the reviewed energy column and units while selecting signals', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions,
    columns: [...columns, { ...columns[0], name: 'energy attained', index: 6, column_id: 'c6' }] }} />)
  fireEvent.change(screen.getByLabelText('Energy column'), { target: { value: 'c6' } })
  fireEvent.change(screen.getByLabelText('Energy units'), { target: { value: 'keV' } })
  selectSignals('Fluorescence')
  expect(columnPayload(accepted())).toMatchObject({ energy_column: 'c6', units: 'keV', numerator: ['c3'], denominator: 'c1' })
  selectSignals('Transmission')
  expect(columnPayload(accepted())).toMatchObject({ energy_column: 'c6', units: 'keV', numerator: ['c1'], denominator: 'c2' })
})
it.each([true, false])('keeps replacement detector choices when toggling Natural log with reader suggestions=%s', withSuggestions => {
  const reviewed: ColumnMapping = { ...initial, numerator: ['c3', 'c4'], denominator: ['c1', 'c2'], units: 'keV', signal_multiplier: 2 }
  render(<Harness replacement initialMapping={reviewed} inspection={{
    ...(withSuggestions ? { plugin_suggestions: readerSuggestions } : { columns: columns.map(c => c.column_id === 'c3' ? { ...c, name: 'If' } : c) }),
  }} />)
  expect(screen.queryByLabelText('Measurement')).not.toBeInTheDocument()
  expect(screen.queryByRole('checkbox', { name: 'Import Transmission' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Natural log'))
  expect(accepted()).toEqual({ ...reviewed, mode: 'fluorescence' })
  fireEvent.click(screen.getByLabelText('Natural log'))
  expect(accepted()).toEqual(reviewed)
})
it('imports both modes with independent detector columns and signal scales', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  selectSignals('Transmission', 'Fluorescence')
  expect(screen.getByRole('heading', { name: 'Transmission' })).toBeInTheDocument()
  expect(screen.queryByRole('group', { name: 'Fluorescence columns' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeEnabled()
  expect(screen.getByLabelText('Natural log')).toBeChecked()
  expect(screen.getByLabelText('Natural log')).toBeDisabled()
  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  fireEvent.click(screen.getByLabelText('Fluorescence numerator detB'))
  fireEvent.change(screen.getByLabelText('Fluorescence multiplicative constant'), { target: { value: '0.5' } })
  expect(accepted()).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3', 'c4'], denominator: 'c1', invert: false, signal_multiplier: 0.5 } })
  expect(screen.getByText('μ(E) = ln(|(i0) / (it)|)')).toBeInTheDocument()
  expect(screen.getByText('μ(E) = 0.5 × (detA + detB) / (i0)')).toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Save each fluorescence channel as a separate data item'))
  expect(accepted().additional_fluorescence!.individual_channels).toBe(true)
  expect(accepted().individual_channels).toBeFalsy()
})
it('restores the transmission logarithm when enabling fluorescence beside an edited transmission ratio', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  selectSignals('Transmission')
  fireEvent.click(screen.getByLabelText('Natural log'))
  expect(columnPayload(accepted()).mode).toBe('fluorescence')
  expect(screen.getByLabelText('Natural log')).not.toBeChecked()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Import Fluorescence' }))
  expect(screen.getByLabelText('Natural log')).toBeChecked()
  expect(screen.getByLabelText('Natural log')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeEnabled()
  expect(columnPayload(accepted())).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1' } })
})
it('edits three signals in separate tabs without losing any mapping', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  expect(screen.getAllByRole('tab').map(tab => tab.textContent)).toEqual(['Transmission', 'Fluorescence', 'Reference'])
  expect(screen.getByRole('tab', { name: 'Transmission' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('tabpanel', { name: 'Transmission' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Import 3 spectra' })).toBeEnabled()
  expect(accepted()).toMatchObject({ numerator: ['c1'], denominator: 'c2', reference_numerator: 'c2', reference_denominator: 'c5', reference_log: true,
    additional_fluorescence: { numerator: ['c3'], denominator: 'c1' } })

  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  fireEvent.click(screen.getByLabelText('Fluorescence numerator detB'))
  expect(screen.getByRole('tabpanel', { name: 'Fluorescence' })).toBeVisible()
  expect(screen.queryByRole('tabpanel', { name: 'Transmission' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Reference' }))
  fireEvent.change(screen.getByLabelText('reference denominator'), { target: { value: 'c4' } })
  expect(screen.getByText('Reference = ln(|it / detB|)')).toBeVisible()
  const configured = accepted()
  fireEvent.click(screen.getByRole('tab', { name: 'Transmission' }))
  expect(screen.getByLabelText('Numerator i0')).toBeChecked()
  expect(accepted()).toEqual(configured)
  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  expect(screen.getByLabelText('Fluorescence numerator detB')).toBeChecked()
  expect(accepted().reference_denominator).toBe('c4')
})
it('supports arrow keys, Home and End across the column tabs without changing data', () => {
  render(<Harness initialMapping={{ ...initial, additional_fluorescence: { numerator: ['c3'], denominator: 'c1' },
    reference_numerator: 'c2', reference_denominator: 'c5' }} />)
  const before = accepted()
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Transmission' }), { key: 'ArrowRight' })
  expect(screen.getByRole('tab', { name: 'Fluorescence' })).toHaveFocus()
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Fluorescence' }), { key: 'End' })
  expect(screen.getByRole('tab', { name: 'Reference' })).toHaveFocus()
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Reference' }), { key: 'ArrowRight' })
  expect(screen.getByRole('tab', { name: 'Transmission' })).toHaveFocus()
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Transmission' }), { key: 'ArrowLeft' })
  expect(screen.getByRole('tab', { name: 'Reference' })).toHaveFocus()
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Reference' }), { key: 'Home' })
  expect(screen.getByRole('tab', { name: 'Transmission' })).toHaveFocus()
  expect(accepted()).toEqual(before)
})
it('requires a reference choice for three-signal import when its columns are not identified', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions,
    columns: columns.map(c => c.name === 'ref' ? { ...c, name: 'unidentified' } : c) }} />)
  expect(screen.getByRole('button', { name: 'Import 3 spectra' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Reference tab')
  fireEvent.click(screen.getByRole('tab', { name: 'Reference' }))
  fireEvent.change(screen.getByLabelText('reference numerator'), { target: { value: 'c2' } })
  expect(screen.getByRole('button', { name: 'Import 3 spectra' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('reference denominator'), { target: { value: 'c5' } })
  expect(screen.getByRole('button', { name: 'Import 3 spectra' })).toBeEnabled()
})
it('flips fluorescence columns independently and swaps every rendered checkbox', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  selectSignals('Transmission', 'Fluorescence')
  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  fireEvent.click(screen.getByLabelText('Fluorescence numerator detB'))
  const flip = screen.getByRole('button', { name: 'Flip fluorescence numerator and denominator' })

  fireEvent.click(flip)

  expect(accepted()).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2',
    additional_fluorescence: { numerator: ['c1'], denominator: ['c3', 'c4'] } })
  expect(accepted().additional_fluorescence!.invert).not.toBe(true)
  expect(screen.getByLabelText('Fluorescence numerator i0')).toBeChecked()
  expect(screen.getByLabelText('Fluorescence numerator detA')).not.toBeChecked()
  expect(screen.getByLabelText('Fluorescence numerator detB')).not.toBeChecked()
  expect(screen.getByLabelText('Fluorescence denominator i0')).not.toBeChecked()
  expect(screen.getByLabelText('Fluorescence denominator detA')).toBeChecked()
  expect(screen.getByLabelText('Fluorescence denominator detB')).toBeChecked()
  expect(screen.getByText('μ(E) = (i0) / (detA + detB)')).toBeInTheDocument()

  fireEvent.click(flip)

  expect(accepted().additional_fluorescence).toMatchObject({ numerator: ['c3', 'c4'], denominator: ['c1'] })
  expect(accepted().additional_fluorescence!.invert).not.toBe(true)
  expect(screen.getByLabelText('Fluorescence numerator i0')).not.toBeChecked()
  expect(screen.getByLabelText('Fluorescence numerator detA')).toBeChecked()
  expect(screen.getByLabelText('Fluorescence numerator detB')).toBeChecked()
  expect(screen.getByLabelText('Fluorescence denominator i0')).toBeChecked()
  expect(screen.getByLabelText('Fluorescence denominator detA')).not.toBeChecked()
  expect(screen.getByLabelText('Fluorescence denominator detB')).not.toBeChecked()
})
it('requires explicit fluorescence columns when no detector suggestion is available', () => {
  render(<Harness />)
  selectSignals('Transmission', 'Fluorescence')
  expect(accepted().additional_fluorescence!.numerator).toEqual([])
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeDisabled()
  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  fireEvent.click(screen.getByLabelText('Fluorescence numerator detA'))
  fireEvent.click(screen.getByRole('button', { name: 'Clear fluorescence denominator' }))
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeDisabled()
  fireEvent.click(screen.getByLabelText('Fluorescence denominator i0'))
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Clear fluorescence numerator' }))
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeDisabled()
  expect(accepted().numerator).toEqual(['c1'])
  expect(accepted().denominator).toBe('c2')
})
it('keeps fluorescence scale independent and lowers only the selected recipe into the payload', () => {
  render(<Harness initialMapping={{ ...initial, signal_multiplier: 2, individual_channels: true,
    additional_fluorescence: { numerator: ['c3', 'c4'], denominator: 'c1' } }} />)
  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  expect(screen.getByText('μ(E) = (detA + detB) / (i0)')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Flip fluorescence numerator and denominator' })).toBeEnabled()
  expect(screen.getByLabelText('Fluorescence multiplicative constant')).toHaveValue(1)
  selectSignals('Fluorescence')
  expect(columnPayload(accepted())).toMatchObject({ mode: 'fluorescence', numerator: ['c3', 'c4'], invert: false,
    signal_multiplier: 1, individual_channels: false })
  expect(columnPayload(accepted()).additional_fluorescence).toBeFalsy()
  expect(accepted().signal_multiplier).toBe(2)
})
it('retains all edited recipes while disabling and re-enabling individual signals', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  fireEvent.click(screen.getByLabelText('Fluorescence numerator detB'))
  fireEvent.change(screen.getByLabelText('Fluorescence multiplicative constant'), { target: { value: '.5' } })
  const fluorescence = accepted().additional_fluorescence
  selectSignals('Fluorescence')
  expect(columnPayload(accepted())).toMatchObject({ mode: 'fluorescence', numerator: ['c3', 'c4'], denominator: 'c1', signal_multiplier: .5,
    reference_numerator: null, reference_denominator: null })
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
  selectSignals('Transmission')
  expect(accepted().additional_fluorescence).toEqual(fluorescence)
  expect(columnPayload(accepted())).toMatchObject({ mode: 'transmission', numerator: ['c1'], denominator: 'c2' })
  selectSignals('Transmission', 'Fluorescence', 'Reference')
  expect(columnPayload(accepted()).additional_fluorescence).toEqual(fluorescence)
  expect(screen.getByLabelText('Fluorescence numerator detB')).toBeChecked()
})
it('keeps tab navigation independent from import selection and blocks an empty selection', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  selectSignals()
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent(/select.*signal|choose.*signal/i)
  fireEvent.click(screen.getByRole('tab', { name: 'Reference' }))
  expect(screen.getByRole('tabpanel', { name: 'Reference' })).toBeVisible()
  expect(screen.getByRole('checkbox', { name: 'Import Reference' })).not.toBeChecked()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Import Fluorescence' }))
  expect(screen.getByRole('tab', { name: 'Reference' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
  expect(columnPayload(accepted())).toMatchObject({ mode: 'fluorescence', numerator: ['c3'], denominator: 'c1' })
})
it('imports only the reference recipe when its checkbox is the sole selection', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  selectSignals('Reference')
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
  expect(columnPayload(accepted())).toMatchObject({ mode: 'transmission', numerator: ['c2'], denominator: 'c5', is_reference: true,
    reference_numerator: null, reference_denominator: null })
  expect(columnPayload(accepted()).additional_fluorescence).toBeFalsy()
})
it('clears combined importing for extracted chi and does not restore it implicitly', () => {
  render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  fireEvent.change(screen.getByLabelText('Input format'), { target: { value: 'chi' } })
  expect(accepted()).toMatchObject({ data_type: 'chi', mode: 'mu' })
  expect(accepted().additional_fluorescence).toBeFalsy()
  expect(screen.queryByLabelText('Measurement')).not.toBeInTheDocument()
  expect(screen.queryByRole('checkbox', { name: 'Import Fluorescence' })).not.toBeInTheDocument()
  expect(screen.queryByRole('group', { name: 'Fluorescence columns' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Input format'), { target: { value: 'mu' } })
  expect(accepted().mode).toBe('mu')
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
})
it('freezes all additional fluorescence controls during import', () => {
  const { rerender } = render(<Harness inspection={{ plugin_suggestions: readerSuggestions }} />)
  selectSignals('Transmission', 'Fluorescence')
  fireEvent.click(screen.getByRole('tab', { name: 'Fluorescence' }))
  rerender(<Harness busy inspection={{ plugin_suggestions: readerSuggestions }} />)
  for (const label of ['Fluorescence numerator detA', 'Fluorescence denominator i0',
    'Fluorescence multiplicative constant', 'Save each fluorescence channel as a separate data item']) {
    expect(screen.getByLabelText(label)).toBeDisabled()
  }
  expect(screen.getByRole('button', { name: 'Flip fluorescence numerator and denominator' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Clear fluorescence numerator' })).toBeDisabled()
  for (const name of ['Transmission', 'Fluorescence', 'Reference']) expect(screen.getByRole('checkbox', { name: `Import ${name}` })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Importing…' })).toBeDisabled()
})
it('applies both modes to a shared batch while preserving the batch import action', () => {
  render(<Harness remaining={3} inspection={{ plugin_suggestions: readerSuggestions }} />)
  selectSignals('Transmission', 'Fluorescence')
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: 'Yes, use the same parameters' }))
  expect(screen.getByRole('button', { name: 'Import 3 files' })).toBeEnabled()
  fireEvent.change(screen.getByLabelText('Fluorescence multiplicative constant'), { target: { value: '' } })
  expect(screen.getByRole('button', { name: 'Import 3 files' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent(/fluorescence.*multiplicative constant/i)
})
it('asks once at the top of a batch whether to share parameters and makes the import scope explicit', () => {
  render(<Harness remaining={3} />)
  selectSignals('Transmission')
  const question = screen.getByRole('group', { name: 'Use the same import parameters for all files?' })
  expect(question.compareDocumentPosition(screen.getByLabelText('Input format')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: 'Yes, use the same parameters' }))
  expect(screen.getByRole('button', { name: 'Import 3 files' })).toBeEnabled()
  fireEvent.click(screen.getByRole('radio', { name: 'No, review each file' }))
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
})
it('leaves single-file importing unchanged and locks the batch choice during an import', () => {
  const { rerender } = render(<Harness />)
  selectSignals('Transmission')
  expect(screen.queryByRole('radio', { name: 'Yes, use the same parameters' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
  rerender(<Harness remaining={3} busy />)
  expect(screen.getByRole('radio', { name: 'Yes, use the same parameters' })).toBeDisabled()
  expect(screen.getByRole('radio', { name: 'No, review each file' })).toBeDisabled()
})
it('places the file and import actions above the column controls', () => {
  render(<Harness />)
  selectSignals('Transmission')
  const actions = screen.getByRole('group', { name: 'Import actions' })
  expect(actions).toContainElement(screen.getByRole('button', { name: 'Choose another file' }))
  expect(actions).toContainElement(screen.getByRole('button', { name: 'Import spectrum' }))
  expect(actions.compareDocumentPosition(screen.getByLabelText('Input format')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
it('can restore reader column suggestions while replacing an existing spectrum', () => {
  render(<Harness replacement inspection={{ plugin_suggestions: readerSuggestions }} />)
  expect(accepted()).toEqual(initial)
  fireEvent.click(screen.getByLabelText('Input already normalized'))
  fireEvent.click(screen.getByRole('button', { name: 'Use fluorescence columns' }))
  expect(accepted()).toMatchObject({ numerator: ['c3'], denominator: 'c1', mode: 'fluorescence', units: 'eV',
    data_type: 'norm', is_normalized: true, exafs: true, individual_channels: false })
  expect(screen.getByLabelText('Natural log')).not.toBeChecked()
  fireEvent.click(screen.getByLabelText('Numerator detB'))
  expect(accepted().numerator).toEqual(['c3', 'c4'])
  fireEvent.click(screen.getByRole('button', { name: 'Use transmission columns' }))
  expect(accepted()).toMatchObject({ numerator: ['c1'], denominator: 'c2', mode: 'transmission', data_type: 'norm', exafs: true })
  expect(screen.getByLabelText('Natural log')).toBeChecked()
})
it('does not offer a nonexistent reader fluorescence mapping', () => {
  render(<Harness replacement inspection={{ plugin_suggestions: { transmission: readerSuggestions!.transmission } }} />)
  expect(screen.getByRole('button', { name: 'Use transmission columns' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: 'Use fluorescence columns' })).not.toBeInTheDocument()
})
it('hides energy reader suggestions for extracted chi input', () => {
  render(<Harness replacement inspection={{ plugin_suggestions: readerSuggestions }} />)
  fireEvent.change(screen.getByLabelText('Input format'), { target: { value: 'chi' } })
  expect(screen.queryByLabelText('Reader column suggestions')).not.toBeInTheDocument()
})
it('prevents reader suggestion changes while importing', () => {
  render(<Harness replacement busy inspection={{ plugin_suggestions: readerSuggestions }} />)
  expect(screen.getByRole('button', { name: 'Use transmission columns' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Use fluorescence columns' })).toBeDisabled()
})
it('presents binary source bytes as hexadecimal with the original download', () => {
  render(<Harness inspection={{ source_preview_format: 'hex', source_preview: '00000000  53 53 52 4c' }} />)
  fireEvent.click(screen.getByText('Binary source bytes (hex) (first section)'))
  expect(screen.getByText(/00000000\s+53 53 52 4c/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Download original file' })).toBeVisible()
})
it('shows file conversion and separate original/converted downloads without changing detector choices', () => {
  render(<Harness inspection={{ file_plugin: { id: 'X10C', version: '0.1', description: 'NSLS beamline X10C',
    summary: 'Separated joined negative values.', source_sha256: 'a', converted_sha256: 'b' },
    source_preview: 'EXAFS\0padding', converted_preview: '# energy 1 2 3 4 5 6 7', converted_preview_truncated: true }} />)
  const before = accepted()
  expect(screen.getByLabelText('File conversion')).toHaveTextContent('NSLS beamline X10C')
  fireEvent.click(screen.getByText('Source file contents (first section)'))
  fireEvent.click(screen.getByText('Converted columns (first section)'))
  expect(screen.getByText('EXAFS␀padding')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Download original file' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Download converted file' })).toBeEnabled()
  expect(accepted()).toEqual(before)
})
it('offers transport-backed original and converted upload downloads', () => {
  render(<Harness inspection={{ source_preview: 'source', converted_preview: 'converted' }} />)
  fireEvent.click(screen.getByText('Source file contents (first section)'))
  fireEvent.click(screen.getByText('Converted columns'))
  expect(screen.getByRole('button', { name: 'Download original file' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Download converted file' })).toBeEnabled()
})

it('offers the original full file for ordinary tables without a conversion label', () => {
  render(<Harness />)
  fireEvent.click(screen.getByText('Source file contents (first section)'))
  expect(screen.getByRole('button', { name: 'Download original file' })).toBeVisible()
  expect(screen.queryByLabelText('File conversion')).not.toBeInTheDocument()
  expect(screen.queryByText(/Converted columns/)).not.toBeInTheDocument()
})
it("offers FEFF normalized input while retaining energy column controls and preview choices", () => {
  render(<Harness />)
  fireEvent.change(screen.getByLabelText('Input format'), { target: { value: 'xmudat' } })
  expect(accepted()).toMatchObject({ data_type: 'xmudat', energy_column: 'c0', numerator: ['c1'] })
  expect(screen.getByText(/FEFF μ\(E\) is already normalized/)).toBeInTheDocument()
  expect(screen.getByLabelText('Energy units')).toBeEnabled()
  expect(screen.getByLabelText('reference numerator')).toBeEnabled()
  expect(screen.queryByLabelText('Input already normalized')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Input format'), { target: { value: 'chi' } })
  expect(accepted().is_normalized).toBe(false)
  expect(screen.queryByLabelText('Enable EXAFS processing')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Energy units')).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Input format'), { target: { value: 'xmudat' } })
  expect(screen.getByLabelText('Energy units')).toBeEnabled()
  expect(accepted()).toMatchObject({ data_type: 'xmudat', mode: 'mu', denominator: '' })
})
it.each([["7,9,12-15", [6, 8, 11, 12, 13, 14]], ["4-2, 3, 1", [0, 1, 2, 3]], ["2,2", [1]]])("parses Athena column range %s", (range, expected) => {
  expect(numeratorRange(range as string, 15)).toEqual(expected)
})
it.each(["", "0", "16", "1;2", "1,,2", "1e2", "NaN", "1.5", "1-2-3"])("rejects invalid range %s", range => {
  expect(() => numeratorRange(range, 15)).toThrow()
})
it("adds a range to selected numerator buttons, skips energy, and clears all on request", () => {
  render(<Harness />)
  selectSignals('Transmission')
  fireEvent.change(screen.getByLabelText("Numerator column numbers"), { target: { value: "5-4,1" } })
  fireEvent.click(screen.getByRole("button", { name: "Select range" }))
  expect(accepted().numerator).toEqual(["c1", "c3", "c4"])
  expect(screen.getByLabelText("Numerator energy")).not.toBeChecked()
  fireEvent.change(screen.getByLabelText("Numerator column numbers"), { target: { value: "999" } })
  fireEvent.click(screen.getByRole("button", { name: "Select range" }))
  expect(screen.getByRole("alert")).toHaveTextContent("between 1 and 6")
  expect(accepted().numerator).toEqual(["c1", "c3", "c4"])
  fireEvent.click(screen.getByRole("button", { name: "Clear numerator" }))
  expect(accepted().numerator).toEqual([])
  expect(screen.getByRole("button", { name: "Import spectrum" })).toBeEnabled()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
})
it("sends individual-channel and reference toggles and clears references for chi", () => {
  render(<Harness />)
  fireEvent.click(screen.getByLabelText("Save each channel as a separate data item"))
  fireEvent.click(screen.getByRole("tab", { name: "Reference" }))
  fireEvent.change(screen.getByLabelText("reference numerator"), { target: { value: "c2" } })
  fireEvent.change(screen.getByLabelText("reference denominator"), { target: { value: "c5" } })
  fireEvent.click(screen.getByLabelText("Reference natural log"))
  fireEvent.click(screen.getByLabelText("Same element"))
  expect(accepted()).toMatchObject({ individual_channels: true, reference_log: false, reference_same_element: false,
    reference_numerator: "c2", reference_denominator: "c5" })
  fireEvent.change(screen.getByLabelText("Input format"), { target: { value: "chi" } })
  expect(accepted()).toMatchObject({ data_type: "chi", reference_numerator: "", reference_denominator: "" })
  expect(screen.getByLabelText("Energy units")).toBeDisabled()
  expect(screen.queryByLabelText("reference numerator")).not.toBeInTheDocument()
  expect(screen.queryByRole("tab", { name: "Reference" })).not.toBeInTheDocument()
})
it("exposes source contents and freezes mapping controls during import", () => {
  render(<Harness busy />)
  expect(screen.getByText("# Original beamline headers")).toBeInTheDocument()
  expect(screen.queryByLabelText('Measurement')).not.toBeInTheDocument()
  for (const name of ['Transmission', 'Fluorescence', 'Reference']) expect(screen.getByRole('checkbox', { name: `Import ${name}` })).toBeDisabled()
  expect(screen.getByLabelText("Numerator i0")).toBeDisabled()
  expect(screen.getByLabelText('Input already normalized')).toBeDisabled()
  expect(screen.queryByLabelText('Enable EXAFS processing')).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Select range" })).toBeDisabled()
})

it("flips complete numerator and denominator selections, including every rendered checkbox", () => {
  render(<Harness />)
  fireEvent.click(screen.getByLabelText("Numerator detA"))
  fireEvent.click(screen.getByLabelText("Denominator detB"))
  const flip = screen.getByRole("button", { name: "Flip numerator and denominator" })

  fireEvent.click(flip)

  expect(accepted()).toMatchObject({ numerator: ["c2", "c4"], denominator: ["c1", "c3"] })
  expect(accepted().invert).not.toBe(true)
  for (const name of ["it", "detB"]) expect(screen.getByLabelText(`Numerator ${name}`)).toBeChecked()
  for (const name of ["i0", "detA"]) expect(screen.getByLabelText(`Denominator ${name}`)).toBeChecked()
  expect(screen.getByLabelText("Numerator i0")).not.toBeChecked()
  expect(screen.getByLabelText("Numerator detA")).not.toBeChecked()
  expect(screen.getByLabelText("Denominator it")).not.toBeChecked()
  expect(screen.getByLabelText("Denominator detB")).not.toBeChecked()
  expect(screen.getByText("μ(E) = ln(|(it + detB) / (i0 + detA)|)")).toBeInTheDocument()

  fireEvent.click(flip)

  expect(accepted()).toMatchObject({ numerator: ["c1", "c3"], denominator: ["c2", "c4"] })
  expect(accepted().invert).not.toBe(true)
  expect(screen.getByLabelText("Numerator i0")).toBeChecked()
  expect(screen.getByLabelText("Numerator detA")).toBeChecked()
  expect(screen.getByLabelText("Numerator it")).not.toBeChecked()
  expect(screen.getByLabelText("Numerator detB")).not.toBeChecked()
  expect(screen.getByLabelText("Denominator it")).toBeChecked()
  expect(screen.getByLabelText("Denominator i0")).not.toBeChecked()
  expect(screen.getByLabelText("Denominator detB")).toBeChecked()
})

it("uses constant 1 when the denominator is cleared and displays signal scaling", () => {
  render(<Harness />)
  selectSignals('Transmission')
  fireEvent.change(screen.getByLabelText("Multiplicative constant"), { target: { value: "2.5" } })
  expect(accepted()).toMatchObject({ signal_multiplier: 2.5 })
  expect(accepted().invert).not.toBe(true)
  expect(screen.getByText(/μ\(E\) = 2.5 × ln/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Clear denominator" }))
  expect(accepted().denominator).toBe("")
  expect(screen.getByText(/ln\(\|\(i0\) \/ \(1\)\|\)/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Multiplicative constant"), { target: { value: "" } })
  expect(screen.getByRole("button", { name: "Import spectrum" })).toBeDisabled()
  expect(screen.getByRole("alert")).toHaveTextContent("finite multiplicative constant")
  fireEvent.change(screen.getByLabelText("Multiplicative constant"), { target: { value: "0" } })
  expect(screen.getByRole("button", { name: "Import spectrum" })).toBeEnabled()
  expect(screen.getByText(/μ\(E\) = 0 × ln/)).toBeInTheDocument()
})

it("disables flipping for chi data without creating an inversion transform", () => {
  render(<Harness />)
  const flip = screen.getByRole("button", { name: "Flip numerator and denominator" })
  expect(flip).toBeEnabled()
  fireEvent.change(screen.getByLabelText("Multiplicative constant"), { target: { value: "4" } })
  fireEvent.change(screen.getByLabelText("Input format"), { target: { value: "chi" } })
  expect(accepted()).toMatchObject({ data_type: "chi", mode: "mu", units: "eV", denominator: "", invert: false, signal_multiplier: 1 })
  expect(flip).toBeDisabled()
  for (const label of ["Natural log", "Multiplicative constant", "Denominator it", "Energy units"]) {
    expect(screen.getByLabelText(label)).toBeDisabled()
  }
  expect(screen.queryByLabelText('Measurement')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Input format"), { target: { value: "mu" } })
  expect(screen.getByLabelText("Multiplicative constant")).toHaveValue(1)
})

it("suggests units for a new energy column and preserves a manual override while choosing detectors", () => {
  render(<Harness columnUnits={{ c0: "eV", c1: "keV", c2: null }} />)
  fireEvent.change(screen.getByLabelText("Energy column"), { target: { value: "c1" } })
  expect(screen.getByLabelText("Energy units")).toHaveValue("keV")
  fireEvent.change(screen.getByLabelText("Energy units"), { target: { value: "eV" } })
  fireEvent.click(screen.getByLabelText("Numerator detA"))
  expect(accepted().units).toBe("eV")
  fireEvent.change(screen.getByLabelText("Energy column"), { target: { value: "c2" } })
  expect(accepted().units).toBe("eV")
  expect(screen.getByText(/could not be inferred/)).toBeInTheDocument()
})
const twentyBm = (measurement: object, suggestions: object) => ({ beamline_reader: { id: 'aps-20bm', name: '20-BM', facility: 'APS', beamline: '20-BM',
  format: 'LabVIEW', evidence: 'header', confidence: 'beamline' as const, suggestions,
  reference: { numerator: 'c2', denominator: 'c5', log: true, default: true },
  measurement: { mode: 'transmission' as const, edge_energy: 8980, notes: [], contrast: {}, ...measurement } } })
const sample = { energy_column: 'c0', numerator: ['c1'], denominator: 'c2', mode: 'transmission' as const, units: 'eV' as const, data_type: 'mu' as const }
const foilColumns = { ...sample, numerator: ['c2'], denominator: 'c5' }
it('can remove the reference after explicitly choosing three signals', () => {
  render(<Harness inspection={twentyBm({}, { ...readerSuggestions })} />)
  expect(screen.getByRole('button', { name: 'Import 3 spectra' })).toBeEnabled()
  selectSignals('Transmission', 'Fluorescence')
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeEnabled()
  expect(columnPayload(accepted())).toMatchObject({ reference_numerator: null, reference_denominator: null })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
it('keeps an ambiguous import to one spectrum when the user identifies a foil scan', () => {
  render(<Harness inspection={twentyBm({ ambiguous: true }, { ...readerSuggestions, foil: foilColumns })} />)
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: /A foil scan:/ }))
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
  expect(accepted()).toMatchObject({ numerator: ['c2'], denominator: 'c5', reference_numerator: '', reference_denominator: '' })
  expect(accepted().additional_fluorescence).toBeUndefined()
  expect(screen.queryByLabelText('Measurement')).not.toBeInTheDocument()
})
it('imports nothing from a scan that may be a dilute sample or a foil until the user says which', () => {
  // A marginal I0/It edge beside a clear foil edge used to be resolved by an
  // absolute step floor that declared the sample position empty.
  render(<Harness inspection={twentyBm({ ambiguous: true, contrast: { transmission: 10, reference: 550 } }, { transmission: sample, foil: foilColumns })}
    initialMapping={{ ...initial, reference_numerator: 'c2', reference_denominator: 'c5' }} />)
  expect(screen.getByRole('button', { name: 'Import 2 spectra' })).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: /A foil scan: it\/ref as the spectrum/ }))
  expect(accepted()).toMatchObject({ numerator: ['c2'], denominator: 'c5', mode: 'transmission', reference_numerator: '', reference_denominator: '' })
  expect(screen.getByRole('button', { name: 'Import spectrum' })).toBeEnabled()
  fireEvent.click(screen.getByRole('radio', { name: /A sample: I0\/It, with it\/ref as its reference/ }))
  expect(accepted()).toMatchObject({ numerator: ['c1'], denominator: 'c2', reference_numerator: 'c2', reference_denominator: 'c5' })
})
it('names each channel’s own contrast on the sample-or-foil choice', () => {
  // The only contrast shown was the transmission button's tooltip, which
  // quotes I0/It (10) even after choosing the foil, whose edge is 550.
  render(<Harness inspection={twentyBm({ ambiguous: true, contrast: { transmission: 10, reference: 550 } }, { transmission: sample, foil: foilColumns })}
    initialMapping={{ ...initial, reference_numerator: 'c2', reference_denominator: 'c5' }} />)
  expect(screen.getByRole('radio', { name: /^A sample: .* · I0\/It edge step 10 times its noise$/ })).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: /^A foil scan: .* · it\/ref edge step 550 times its noise$/ })).toBeInTheDocument()
})
it("reports the foil's own contrast on the offer that imports It/Iref as the spectrum", () => {
  // The tooltip quoted the I0/It contrast (no edge) behind an It/Iref offer.
  render(<Harness replacement inspection={twentyBm({ foil_spectrum: true, contrast: { transmission: -1, reference: 550 } }, { transmission: foilColumns })} />)
  expect(screen.getByRole('button', { name: /Use transmission columns/ })).toHaveAttribute('title', expect.stringMatching(/^it\/ref edge step 550 times/))
})
