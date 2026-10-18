import "@testing-library/jest-dom/vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { simulationFixture } from "@/tests/fixtures/artemis-simulation"
import { ArtemisSimulationViewer } from "./artemis-simulation-viewer"

const plot = vi.hoisted(() => vi.fn((_props: { data: { x: number[]; y: number[] }[] }) => <div data-testid="simulation-plot" />))
vi.mock("../themed-plot", () => ({ ThemedPlot: plot }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it("keeps the selected space visible above the simulation and switches the saved curves without changing them", () => {
  const result = simulationFixture(), original = structuredClone(result)
  render(<ArtemisSimulationViewer result={result} />)
  const k = screen.getByRole("button", { name: "χ(k)" }), r = screen.getByRole("button", { name: "|χ(R)|" })
  const toolbar = k.closest("[data-viewer-plot-toolbar]")!
  expect(toolbar.compareDocumentPosition(screen.getByTestId("simulation-plot")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(k).toHaveAttribute("aria-pressed", "true")
  expect(k).toHaveAttribute("data-selected", "true")
  expect(r).toHaveAttribute("data-selected", "false")
  expect(plot.mock.calls.at(-1)![0].data[0]).toMatchObject({ x: result.k.x, y: result.k.total })
  fireEvent.click(r)
  expect(r).toHaveAttribute("aria-pressed", "true")
  expect(r).toHaveAttribute("data-selected", "true")
  expect(k).toHaveAttribute("data-selected", "false")
  expect(plot.mock.calls.at(-1)![0].data[0]).toMatchObject({ x: result.r.x, y: result.r.total_mag })
  expect(result).toEqual(original)
})
