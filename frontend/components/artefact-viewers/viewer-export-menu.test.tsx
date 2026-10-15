import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ViewerPanel } from "./viewer-panel"

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe("viewer header exports", () => {
  it("uses the current viewer actions and supports keyboard dismissal without collapsing", () => {
    const single = vi.fn(), multiple = vi.fn()
    render(<>
      <ViewerPanel title="Single spectrum" exportItems={[{ id: "csv", label: "Data (CSV)", onSelect: single }]}><p>Single plot</p></ViewerPanel>
      <ViewerPanel title="Multiple spectra" exportItems={[{ id: "csv", label: "Data (CSV)", onSelect: multiple }]}><p>Multiple plot</p></ViewerPanel>
    </>)
    const trigger = screen.getByRole("button", { name: "Export Multiple spectra" })
    expect(trigger).toHaveTextContent("export")
    fireEvent.keyDown(trigger, { key: "ArrowDown" })
    expect(screen.getByRole("menuitem", { name: "Data (CSV)" })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" })
    expect(trigger).toHaveFocus()
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    fireEvent.click(trigger)
    fireEvent.pointerDown(trigger)
    fireEvent.click(trigger)
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole("menuitem", { name: "Data (CSV)" }))
    expect(multiple).toHaveBeenCalledOnce()
    expect(single).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "Collapse Multiple spectra" })).toHaveAttribute("aria-expanded", "true")
  })

  it("dismisses the portal when collapsed or processing disables export", () => {
    const props = { title: "Wavelet", exportItems: [{ id: "csv", label: "Data (CSV)", onSelect: vi.fn() }] }
    const { rerender } = render(<ViewerPanel {...props}><p>Grid</p></ViewerPanel>)
    fireEvent.click(screen.getByRole("button", { name: "Export Wavelet" }))
    fireEvent.click(screen.getByRole("button", { name: "Collapse Wavelet" }))
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Expand Wavelet" }))
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Export Wavelet" }))
    rerender(<ViewerPanel {...props} exportDisabled><p>Updating</p></ViewerPanel>)
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Export Wavelet" })).toBeDisabled()
  })

  it("shows errors and permits retry after a failed export", async () => {
    const onSelect = vi.fn().mockRejectedValueOnce(new Error("Could not create image")).mockResolvedValueOnce(undefined)
    render(<ViewerPanel title="CIF" exportImages={false} exportItems={[{ id: "png", label: "Image (PNG)", onSelect }]}><p>Structure</p></ViewerPanel>)
    const trigger = screen.getByRole("button", { name: "Export CIF" })
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole("menuitem", { name: "Image (PNG)" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not create image")
    await waitFor(() => expect(trigger).toBeEnabled())
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole("menuitem", { name: "Image (PNG)" }))
    await waitFor(() => expect(trigger).toBeEnabled())
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(onSelect).toHaveBeenCalledTimes(2)
  })

  it("does not offer another viewer's plots as image exports", () => {
    render(<>
      <ViewerPanel title="Empty"><p>No data</p></ViewerPanel>
      <ViewerPanel title="Loaded"><div data-testid="plot" className="js-plotly-plot" /></ViewerPanel>
    </>)
    const plot = screen.getByTestId("plot")
    Object.assign(plot, { data: [{ x: [1], y: [2] }] })
    vi.spyOn(plot, "getBoundingClientRect").mockReturnValue({ width: 400, height: 300 } as DOMRect)
    fireEvent.click(screen.getByRole("button", { name: "Export Empty" }))
    expect(screen.getByRole("menuitem", { name: "Image (PNG)" })).toBeDisabled()
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" })
    fireEvent.click(screen.getByRole("button", { name: "Export Loaded" }))
    expect(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Image (PNG)" })).toBeEnabled()
  })
})
