import "@testing-library/jest-dom/vitest"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { Analysis, AthenaGroup, Parameters } from "@/lib/athena"
import { downloadArtemisText } from "@/lib/artemis-structures"
import { AthenaSpectrumViewer } from "./athena-spectrum-viewer"
import { useSpectrumViewerState } from "./athena-spectrum-viewer-state"

type PlotRange = [number | null, number | null]
const plot = vi.hoisted(() => vi.fn((_props: { range: PlotRange; onRangeChange?: (range: PlotRange) => void }) => {}))
vi.mock("./athena-plot", () => ({ AthenaPlot: (props: { range: PlotRange; onRangeChange?: (range: PlotRange) => void }) => {
  plot(props)
  return <div aria-label="Spectrum plot" />
} }))
vi.mock("@/lib/artemis-structures", () => ({ downloadArtemisText: vi.fn() }))

const sample: AthenaGroup = {
  id: "sample", label: "Sample", data_type: "mu", marked: true, frozen: false,
  energy: [100, 101], mu: [1, 2], multiplier: 1, offset: 0, notes: "", reference_id: null,
  parameters: { energy_shift: 0, kweight: 2 } as Parameters,
  result: { arrays: { energy: [100, 101], mu: [1, 2], flat: [0.5, 1] }, effective: {}, warnings: [] },
  processing_error: null, source: {},
}

function Harness({ viewer = "single", onExport, canExport = true, pending = false, analysis = null }: {
  viewer?: "single" | "multiple"; onExport?: () => void; canExport?: boolean; pending?: boolean; analysis?: Analysis | null
}) {
  const state = useSpectrumViewerState(viewer === "single" ? "current" : "selected")
  return <AthenaSpectrumViewer viewer={viewer} state={state} active={sample}
    weightedPlot={{ groups: [sample], loading: false, error: null, retry: () => {} }}
    analysis={analysis} analysisVisible={!!analysis} savedKWeight={2} canChangeKWeight draftE0={null}
    onChangeSpace={state.setSpace} onOptionsMenuOpen={() => {}} onExport={onExport}
    canExport={canExport} exportPending={pending} />
}

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe("spectrum viewer range", () => {
  it("shows the drawn axis in the range fields after the plot is zoomed or reset", () => {
    render(<Harness />)
    const minimum = screen.getByLabelText("Plot minimum"), maximum = screen.getByLabelText("Plot maximum")
    fireEvent.change(minimum, { target: { value: "100.2" } })
    fireEvent.change(maximum, { target: { value: "100.8" } })
    expect(plot.mock.calls.at(-1)![0].range).toEqual([100.2, 100.8])
    act(() => plot.mock.calls.at(-1)![0].onRangeChange?.([100.25, 100.5]))
    expect(minimum).toHaveValue(100.25)
    expect(maximum).toHaveValue(100.5)
    act(() => plot.mock.calls.at(-1)![0].onRangeChange?.([null, null]))
    expect(plot.mock.calls.at(-1)![0].range).toEqual([null, null])
    expect(minimum).toHaveValue(100)
    expect(maximum).toHaveValue(101)
  })

  it("keeps the last ordered range drawn while the minimum is not below the maximum", () => {
    render(<Harness />)
    const minimum = screen.getByLabelText("Plot minimum"), maximum = screen.getByLabelText("Plot maximum")
    const drawn = () => plot.mock.calls.at(-1)![0].range
    fireEvent.change(minimum, { target: { value: "100.2" } })
    fireEvent.change(maximum, { target: { value: "100.8" } })
    fireEvent.change(minimum, { target: { value: "100.8" } })
    expect(drawn()).toEqual([100.2, 100.8])
    expect(minimum).toHaveValue(100.8)
    expect(minimum).toHaveAttribute("aria-invalid", "true")
    expect(maximum).toHaveAttribute("aria-invalid", "true")
    expect(minimum).toHaveAccessibleDescription("Minimum must be less than maximum.")
    expect(maximum).toHaveAccessibleDescription("Minimum must be less than maximum.")
    fireEvent.change(minimum, { target: { value: "100.9" } })
    expect(drawn()).toEqual([100.2, 100.8])
    fireEvent.change(maximum, { target: { value: "100.95" } })
    expect(drawn()).toEqual([100.9, 100.95])
    expect(minimum).not.toHaveAttribute("aria-invalid")
    expect(screen.queryByText("Minimum must be less than maximum.")).not.toBeInTheDocument()
    // A blank maximum is the automatic 101, so a minimum past it is inverted too.
    fireEvent.change(maximum, { target: { value: "" } })
    fireEvent.change(minimum, { target: { value: "102" } })
    expect(drawn()).toEqual([100.9, null])
    expect(screen.getByText("Minimum must be less than maximum.")).toBeInTheDocument()
  })
})

describe("spectrum viewer export", () => {
  it("opens the current-data export from its header menu and respects permission and pending state", async () => {
    const onExport = vi.fn()
    const view = render(<Harness onExport={onExport} />)
    const trigger = screen.getByRole("button", { name: "Export Single spectrum viewer" })
    expect(trigger.closest("header")).not.toBeNull()
    expect(screen.queryByRole("button", { name: "CSV" })).not.toBeInTheDocument()
    fireEvent.click(trigger)
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: "Data (CSV)" })) })
    expect(onExport).toHaveBeenCalledOnce()
    view.rerender(<Harness onExport={onExport} pending />)
    expect(trigger).toBeDisabled()
    view.rerender(<Harness onExport={onExport} canExport={false} />)
    expect(trigger).toBeDisabled()
  })

  it("downloads multiple spectra as CSV without requiring a current-data callback", async () => {
    render(<Harness viewer="multiple" />)
    fireEvent.click(screen.getByRole("button", { name: "Export Multiple spectra viewer" }))
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: "Data (CSV)" })) })
    expect(downloadArtemisText).toHaveBeenCalledWith("marked-spectra-E.csv",
      expect.stringContaining("sample,Sample,mu,,0,100,1,,0.5,"), "text/csv;charset=utf-8")
  })

  it("exports the analysis being displayed as JSON", async () => {
    const analysis: Analysis = { kind: "pca", project_version: 3, group_ids: [sample.id], options: {}, result: { explained_variance_ratio: [0.9, 0.1] } }
    render(<Harness analysis={analysis} />)
    fireEvent.click(screen.getByRole("button", { name: "Export Single spectrum viewer" }))
    expect(screen.queryByRole("menuitem", { name: "Data (CSV)" })).not.toBeInTheDocument()
    await act(async () => { fireEvent.click(screen.getByRole("menuitem", { name: "Analysis data (JSON)" })) })
    expect(downloadArtemisText).toHaveBeenCalledWith("Sample-analysis.json", JSON.stringify(analysis, null, 2), "application/json")
  })
})
