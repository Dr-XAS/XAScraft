import { loadPlotly } from "./plotly-runtime"

export type ViewerImageFormat = "png" | "svg"

/** Only export plots inside this viewer that are currently on screen. */
export function viewerPlots(container: HTMLElement | null): HTMLElement[] {
  return Array.from(container?.querySelectorAll<HTMLElement>(".js-plotly-plot") ?? []).filter(plot => {
    const bounds = plot.getBoundingClientRect()
    return !plot.closest("[hidden]") && bounds.width > 0 && bounds.height > 0 &&
      Array.isArray((plot as HTMLElement & { data?: unknown }).data)
  })
}

export function downloadViewerDataUrl(filename: string, url: string) {
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

export function viewerExportStem(name: string) {
  return name.trim().replace(/[<>:"/\\|?*\x00-\x1f]+/g, "-").replace(/\s+/g, "-") || "viewer"
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error("Could not prepare the viewer image. Try exporting SVG."))
    image.src = url
  })
}

/** Capture live layouts (including zoom/camera) without changing any scientific inputs. */
export async function exportViewerImage(container: HTMLElement | null, filename: string, format: ViewerImageFormat) {
  const plots = viewerPlots(container)
  if (!plots.length) throw new Error("Wait for the plot to finish drawing, then export again.")
  const plotly = await loadPlotly()
  const bounds = plots.map(plot => plot.getBoundingClientRect())
  const images = await Promise.all(plots.map((plot, index) => plotly.toImage(plot, {
    format, width: Math.round(bounds[index].width), height: Math.round(bounds[index].height),
    ...(format === "png" ? { scale: 2 } : {}),
  })))
  const stem = viewerExportStem(filename)
  if (images.length === 1) {
    downloadViewerDataUrl(`${stem}.${format}`, images[0])
    return
  }

  // Wavelets have several plots. Export one image, retaining their current arrangement.
  const left = Math.min(...bounds.map(rect => rect.left))
  const top = Math.min(...bounds.map(rect => rect.top))
  const width = Math.ceil(Math.max(...bounds.map(rect => rect.right)) - left)
  const height = Math.ceil(Math.max(...bounds.map(rect => rect.bottom)) - top)
  const background = container ? getComputedStyle(container).getPropertyValue("--ath-surface").trim() || "white" : "white"
  if (format === "svg") {
    const namespace = "http://www.w3.org/2000/svg"
    const svg = document.createElementNS(namespace, "svg")
    svg.setAttribute("width", String(width))
    svg.setAttribute("height", String(height))
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`)
    const backgroundRect = document.createElementNS(namespace, "rect")
    backgroundRect.setAttribute("width", "100%")
    backgroundRect.setAttribute("height", "100%")
    backgroundRect.setAttribute("fill", background)
    svg.appendChild(backgroundRect)
    images.forEach((url, index) => {
      const image = document.createElementNS(namespace, "image")
      image.setAttribute("x", String(bounds[index].left - left))
      image.setAttribute("y", String(bounds[index].top - top))
      image.setAttribute("width", String(bounds[index].width))
      image.setAttribute("height", String(bounds[index].height))
      image.setAttribute("href", url)
      svg.appendChild(image)
    })
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml;charset=utf-8" }))
    downloadViewerDataUrl(`${stem}.svg`, url)
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } else {
    const canvas = document.createElement("canvas")
    canvas.width = width * 2
    canvas.height = height * 2
    const context = canvas.getContext("2d")
    if (!context) throw new Error("This browser could not create a PNG image. Try exporting SVG.")
    context.scale(2, 2)
    context.fillStyle = background
    context.fillRect(0, 0, width, height)
    const decoded = await Promise.all(images.map(loadImage))
    decoded.forEach((image, index) => context.drawImage(image, bounds[index].left - left, bounds[index].top - top, bounds[index].width, bounds[index].height))
    downloadViewerDataUrl(`${stem}.png`, canvas.toDataURL("image/png"))
  }
}
