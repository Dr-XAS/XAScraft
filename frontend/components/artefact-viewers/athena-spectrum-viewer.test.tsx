import "@testing-library/jest-dom/vitest"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { Analysis, AthenaGroup, Parameters } from "@/lib/athena"
import { downloadArtemisText } from "@/lib/artemis-structures"
import { AthenaSpectrumViewer } from "./athena-spectrum-viewer"
import { useSpectrumViewerState } from "./athena-spectrum-viewer-state"

vi.mock("./athena-plot", () => ({ AthenaPlot: () => <div aria-label="Spectrum plot" /> }))
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
