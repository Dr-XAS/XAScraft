import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { ViewerPlotSpace } from "./viewer-plot-space"

afterEach(cleanup)

const options = [{ value: "k", label: "k", description: "EXAFS" }, { value: "R", label: "R", description: "Fourier" }] as const

describe("shared plot space controls", () => {
  it("preserves spectrum selection and the independent special-plot context menu", () => {
    const change = vi.fn(), special = vi.fn()
    const view = render(<ViewerPlotSpace label="Plot space" tabs options={options} value="k" onChange={change} onSpecialPlot={special} />)
    const k = screen.getByRole("tab", { name: "k EXAFS" }), r = screen.getByRole("tab", { name: "R Fourier" })
    expect(k).toHaveAttribute("aria-selected", "true")
    expect(k).toHaveAttribute("data-selected", "true")
    expect(r).toHaveAttribute("data-selected", "false")
    fireEvent.contextMenu(r)
    expect(special).toHaveBeenCalledExactlyOnceWith("R")
    expect(change).not.toHaveBeenCalled()
    fireEvent.click(r)
    expect(change).toHaveBeenCalledExactlyOnceWith("R")
    view.rerender(<ViewerPlotSpace label="Plot space" tabs options={options} value="R" onChange={change} />)
    expect(k).toHaveAttribute("aria-selected", "false")
    expect(r).toHaveAttribute("aria-selected", "true")
  })

  it("uses the same selected appearance for fit and simulation buttons, including an unset selection", () => {
    const change = vi.fn()
    const view = render(<ViewerPlotSpace label="Fit plot space" options={options} value="R" onChange={change} />)
    const r = screen.getByRole("button", { name: "R Fourier" })
    expect(r).toHaveAttribute("aria-pressed", "true")
    expect(r).toHaveAttribute("data-selected", "true")
    fireEvent.click(screen.getByRole("button", { name: "k EXAFS" }))
    expect(change).toHaveBeenCalledExactlyOnceWith("k")
    view.rerender(<ViewerPlotSpace label="Fit plot space" options={options} value={null} onChange={change} />)
    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveAttribute("aria-pressed", "false")
      expect(button).toHaveAttribute("data-selected", "false")
    }
  })
})
