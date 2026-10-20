import { loadCopperExamples } from "./examples"
import { expect, test, type Locator } from "@playwright/test"
import type { AthenaProject } from "../../lib/athena"
import type { ArtemisProjectStructures } from "../../lib/artemis-structures"

async function renderedCrystal(panel: Locator) {
  return panel.getByRole("img", { name: "Interactive 3D crystal structure of Copper", exact: true }).locator("canvas").evaluate(element => {
    const canvas = element as HTMLCanvasElement & {
      _3dmol_viewer?: {
        getModel: () => { selectedAtoms: (selection: object) => { x: number; y: number; z: number }[] }
        getView: () => number[]
        renderer: { getContext: () => WebGLRenderingContext }
      }
    }
    const viewer = canvas._3dmol_viewer
    const context = viewer?.renderer.getContext()
    const atoms = viewer?.getModel().selectedAtoms({}) ?? []
    const snapshot = document.createElement("canvas")
    snapshot.width = canvas.width
    snapshot.height = canvas.height
    const drawing = snapshot.getContext("2d")!
    drawing.drawImage(canvas, 0, 0)
    const pixels = drawing.getImageData(0, 0, snapshot.width, snapshot.height).data
    let visiblePixels = 0
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] > 0 && (pixels[i] < 240 || pixels[i + 1] < 240 || pixels[i + 2] < 240)) visiblePixels++
    }
    return {
      atoms: atoms.length,
      nearest: Math.min(...atoms.map(atom => Math.hypot(atom.x, atom.y, atom.z)).filter(distance => distance > 0.01)),
      rendered: Boolean(context && !context.isContextLost() && visiblePixels > 100),
      view: viewer?.getView(),
    }
  })
}

async function viewerControlStyles(panel: Locator) {
  const controls = {
    heading: panel.locator(":scope > header"),
    title: panel.locator(":scope > header > h3"),
    collapse: panel.getByRole("button", { name: "Collapse CIF structure viewer", exact: true }),
    measure: panel.getByRole("button", { name: "Measure", exact: true }),
    reset: panel.getByRole("button", { name: "Reset view", exact: true }),
    radius: panel.getByRole("spinbutton", { name: "CIF display radius", exact: true }),
    slider: panel.getByRole("slider", { name: "CIF display radius", exact: true }),
    mode: panel.getByRole("combobox", { name: "CIF view mode", exact: true }),
    center: panel.getByRole("combobox", { name: "CIF center site", exact: true }),
  }
  // Flexible widths depend on the host panel; typography and control chrome must not.
  return Object.fromEntries(await Promise.all(Object.entries(controls).map(async ([name, control]) => [name, await control.evaluate(element => {
    const css = getComputedStyle(element)
    return Object.fromEntries(["font-size", "font-weight", "line-height", "padding", "gap", "min-height", "border-width", "border-style", "border-color", "border-radius", "color", "background-color"].map(property => [property, css.getPropertyValue(property)]))
  })])))
}

async function expectControlsInside(panel: Locator, controls: Locator[]) {
  const panelBounds = (await panel.boundingBox())!
  for (const control of controls) {
    const bounds = (await control.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(panelBounds.x - 1)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(panelBounds.x + panelBounds.width + 1)
  }
}

test("database CIF selection renders an interactive preview before attachment", async ({ page }, info) => {
  test.setTimeout(180_000)
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/")
  const exampleResponse = page.waitForResponse(response => response.url().endsWith("/command") && response.request().postDataJSON()?.action === "example")
  const preparedModel = page.waitForResponse(response => response.url().endsWith("/model") && response.request().method() === "POST")
  await loadCopperExamples(page)
  const initial = await (await exampleResponse).json() as AthenaProject
  expect((await preparedModel).ok()).toBe(true)
  const attachments = async () => {
    const response = await page.request.get(`/api/backend/api/artemis/projects/${initial.id}/structures`)
    expect(response.ok()).toBe(true)
    return await response.json() as ArtemisProjectStructures
  }
  const baseline = await attachments()
  expect(baseline.structures.some(item => item.amcsd_id === 11145 || item.amcsd_id === 13088)).toBe(false)
  const dock = page.locator(".ath-project-cif-viewer").getByRole("region", { name: "CIF structure viewer", exact: true })
  await expect(dock.getByRole("button", { name: "Reset view", exact: true })).toBeEnabled()
  await page.mouse.move(0, 0)
  const desktopStyles = await viewerControlStyles(dock)
  const mutations: string[] = []
  page.on("request", request => {
    if (request.method() === "POST" && (/\/projects\/[^/]+\/structures(?:\/|$)/.test(request.url()) || request.url().endsWith("/feff/jobs"))) mutations.push(request.url())
  })

  await page.getByRole("region", { name: "Project CIF structures", exact: true }).getByRole("button", { name: "Search / attach CIF", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: "Crystal structures", exact: true })
  await dialog.getByRole("combobox", { name: "Structure source", exact: true }).selectOption("amcsd")
  await dialog.getByRole("textbox", { name: "AMCSD search query", exact: true }).fill("copper")
  await dialog.getByRole("button", { name: "Search AMCSD", exact: true }).click()
  const first = dialog.getByRole("button", { name: /Copper.*AMCSD 0011145/ })
  const second = dialog.getByRole("button", { name: /Copper.*AMCSD 0013088/ })
  await first.click()
  const panel = dialog.getByRole("region", { name: "CIF structure viewer", exact: true })
  const attach = dialog.getByRole("button", { name: "Attach to project", exact: true })
  await expect(attach).toBeEnabled()
  await expect(panel.getByRole("button", { name: "Reset view", exact: true })).toBeEnabled()
  await expect.poll(async () => (await renderedCrystal(panel)).rendered).toBe(true)
  expect((await renderedCrystal(panel)).nearest).toBeCloseTo(3.61496 / Math.sqrt(2), 5)
  await expect(first).toHaveAttribute("aria-pressed", "true")
  const radius = panel.getByRole("slider", { name: "CIF display radius", exact: true })
  await expect(radius).toHaveValue("5")
  await radius.press("ArrowRight")
  await expect(radius).toHaveValue("5.1")
  const mode = panel.getByRole("combobox", { name: "CIF view mode", exact: true })
  const radiusValue = panel.getByRole("spinbutton", { name: "CIF display radius", exact: true })
  const sharedControls = [mode, radius, radiusValue, panel.getByRole("combobox", { name: "CIF center site", exact: true }), panel.getByRole("button", { name: "Measure", exact: true }), panel.getByRole("button", { name: "Reset view", exact: true })]
  await page.mouse.move(0, 0)
  expect(await viewerControlStyles(panel)).toEqual(desktopStyles)
  await expect(radiusValue).toHaveCSS("width", "72px")
  await expectControlsInside(panel, sharedControls)
  await mode.selectOption("cell")
  const repeats = ["a", "b", "c"].map(axis => panel.getByRole("spinbutton", { name: `CIF repeats along ${axis}`, exact: true }))
  for (const input of repeats) await expect(input).toHaveCSS("width", "48px")
  await expectControlsInside(panel, repeats)
  await repeats[0].fill("2")
  await expect.poll(async () => (await renderedCrystal(panel)).atoms).toBe(8)
  const canvas = panel.getByRole("img", { name: "Interactive 3D crystal structure of Copper", exact: true }).locator("canvas")
  await canvas.scrollIntoViewIfNeeded()
  const originalCanvas = await canvas.elementHandle()
  const beforeRotation = (await renderedCrystal(panel)).view
  const canvasBounds = (await canvas.boundingBox())!
  await page.mouse.move(canvasBounds.x + canvasBounds.width / 2, canvasBounds.y + canvasBounds.height / 2)
  await page.mouse.down()
  await page.mouse.move(canvasBounds.x + canvasBounds.width / 2 + 45, canvasBounds.y + canvasBounds.height / 2 + 25, { steps: 5 })
  await page.mouse.up()
  await expect.poll(async () => (await renderedCrystal(panel)).view).not.toEqual(beforeRotation)
  const rotated = (await renderedCrystal(panel)).view
  await panel.getByRole("button", { name: "Collapse CIF structure viewer", exact: true }).click()
  await expect(mode).toBeHidden()
  await panel.getByRole("button", { name: "Expand CIF structure viewer", exact: true }).click()
  await expect(mode).toHaveValue("cell")
  await expect(repeats[0]).toHaveValue("2")
  expect(await canvas.evaluate((element, original) => element === original, originalCanvas)).toBe(true)
  await expect.poll(async () => (await renderedCrystal(panel)).view).toEqual(rotated)
  await expect.poll(async () => (await renderedCrystal(panel)).rendered).toBe(true)
  await panel.getByRole("button", { name: "Show Cu atoms", exact: true }).click()
  await expect(panel.getByText("0 atoms shown", { exact: true })).toBeVisible()

  await second.click()
  await expect(second).toHaveAttribute("aria-pressed", "true")
  await expect(mode).toHaveValue("cluster")
  await expect(radius).toHaveValue("5")
  await expect(panel.getByRole("button", { name: "Show Cu atoms", exact: true })).toHaveAttribute("aria-pressed", "true")
  await expect.poll(async () => (await renderedCrystal(panel)).rendered).toBe(true)
  expect((await renderedCrystal(panel)).nearest).toBeCloseTo(3.63 / Math.sqrt(2), 5)
  await expect(attach).toBeEnabled()
  expect(await attachments()).toEqual(baseline)
  expect(mutations).toEqual([])

  await page.setViewportSize({ width: 390, height: 844 })
  await panel.scrollIntoViewIfNeeded()
  await expectControlsInside(panel, sharedControls)
  await expect(radiusValue).toHaveCSS("width", "72px")
  await page.mouse.move(0, 0)
  const mobileStyles = await viewerControlStyles(panel)
  await mode.selectOption("cell")
  for (const input of repeats) await expect(input).toHaveCSS("width", "48px")
  await expectControlsInside(panel, repeats)
  await mode.selectOption("cluster")
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true)
  await panel.screenshot({ path: info.outputPath("cif-candidate-preview-mobile.png") })

  await radius.press("ArrowRight")
  await expect(radius).toHaveValue("5.1")
  const saved = page.waitForResponse(response => response.url().endsWith(`/projects/${initial.id}/structures`) && response.request().method() === "POST")
  await attach.click()
  const savedResponse = await saved
  expect(savedResponse.ok()).toBe(true)
  const project = await savedResponse.json() as AthenaProject
  expect(project.artemis_structures).toHaveLength(baseline.structures.length + 1)
  expect(project.artemis_structures!.some(item => item.amcsd_id === 13088)).toBe(true)
  await expect(dialog.getByRole("button", { name: "Attached to project", exact: true })).toBeDisabled()
  await expect(radius).toHaveValue("5.1")
  await expect(panel.getByRole("alert")).toHaveCount(0)
  await dialog.getByRole("button", { name: "Close CIF search", exact: true }).click()
  await expect(dock.getByRole("button", { name: "Reset view", exact: true })).toBeEnabled()
  await dock.scrollIntoViewIfNeeded()
  await page.mouse.move(0, 0)
  expect(await viewerControlStyles(dock)).toEqual(mobileStyles)
  await expect(dock.getByRole("spinbutton", { name: "CIF display radius", exact: true })).toHaveCSS("width", "72px")
  expect(errors).toEqual([])
})
