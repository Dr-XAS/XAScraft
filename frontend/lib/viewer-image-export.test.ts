import { afterEach, describe, expect, it, vi } from "vitest"
import { exportViewerImage, viewerPlots } from "./viewer-image-export"

const { toImage } = vi.hoisted(() => ({ toImage: vi.fn() }))
vi.mock("./plotly-runtime", () => ({ loadPlotly: async () => ({ toImage }) }))
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); toImage.mockReset() })

function plot(container: HTMLElement, x = 0, y = 0) {
  const element = document.createElement("div")
  element.className = "js-plotly-plot"
  Object.assign(element, { data: [{ x: [1, 2], y: [3, 4] }], layout: { xaxis: { range: [1.2, 1.8] } } })
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({ left: x, top: y, right: x + 400, bottom: y + 300, width: 400, height: 300 } as DOMRect)
  container.appendChild(element)
  return element
}

describe("viewer image downloads", () => {
  it("captures the live plot and preserves its data and zoom", async () => {
    const container = document.createElement("section")
    document.body.appendChild(container)
    const element = plot(container)
    const before = JSON.stringify(element)
    toImage.mockResolvedValue("data:image/png;base64,TEST")
    let filename = ""
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { filename = this.download })
    await exportViewerImage(container, "Single spectrum/E", "png")
    expect(filename).toBe("Single-spectrum-E.png")
    expect(toImage).toHaveBeenCalledWith(element, { format: "png", width: 400, height: 300, scale: 2 })
    expect(JSON.stringify(element)).toBe(before)
  })

  it("combines multiple visible plots into one SVG with their displayed arrangement", async () => {
    const container = document.createElement("section")
    document.body.appendChild(container)
    plot(container, 30, 20)
    plot(container, 440, 20)
    const hidden = document.createElement("div")
    hidden.hidden = true
    container.appendChild(hidden)
    plot(hidden)
    expect(viewerPlots(container)).toHaveLength(2)
    toImage.mockResolvedValue("data:image/svg+xml,%3Csvg/%3E")
    let exported: Blob | undefined
    vi.spyOn(URL, "createObjectURL").mockImplementation(blob => { exported = blob as Blob; return "blob:plots" })
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    await exportViewerImage(container, "wavelet", "svg")
    const svg = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(exported!) })
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml")
    expect(doc.querySelector("parsererror")).toBeNull()
    expect(doc.documentElement.getAttribute("width")).toBe("810")
    expect(doc.querySelectorAll("image")).toHaveLength(2)
    expect(doc.querySelectorAll("image")[1].getAttribute("x")).toBe("410")
    expect(toImage).toHaveBeenCalledTimes(2)
  })

  it("fails clearly when no plot is ready", async () => {
    await expect(exportViewerImage(null, "empty", "svg")).rejects.toThrow("finish drawing")
    expect(toImage).not.toHaveBeenCalled()
  })
})
