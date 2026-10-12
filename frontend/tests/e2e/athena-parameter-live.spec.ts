import { fileURLToPath } from "node:url"
import { expect, test, type Locator, type Page } from "@playwright/test"
import type { AthenaGroup, AthenaProject } from "../../lib/athena"

const fixture = fileURLToPath(new URL("../../../backend/tests/fixtures/xdi-official-cu_metal_rt.xdi", import.meta.url))

test.use({ actionTimeout: 15_000 })

async function loadCopper(page: Page) {
  await page.goto("/")
  await page.getByRole("button", { name: "Import data", exact: true }).click()
  await page.getByLabel("Choose data files", { exact: true }).setInputFiles(fixture)
  const dialog = page.getByRole("dialog", { name: "Import spectra", exact: true })
  await dialog.getByRole("checkbox", { name: "Numerator i0", exact: true }).uncheck()
  await dialog.getByRole("checkbox", { name: "Numerator mutrans", exact: true }).check()
  await dialog.getByRole("checkbox", { name: "Denominator itrans", exact: true }).uncheck()
  await dialog.getByRole("checkbox", { name: "Natural log", exact: true }).uncheck()
  const imported = page.waitForResponse(response => response.url().endsWith("/import"))
  await dialog.getByRole("button", { name: "Import spectrum", exact: true }).click()
  const response = await imported
  expect(response.ok()).toBe(true)
  await expect(dialog).toHaveCount(0)
  return await response.json() as AthenaProject
}

async function expectProcessedMarkers(graph: Locator, group: AthenaGroup) {
  const effective = group.result!.effective
  const e0 = effective.e0 as number
  const rounded = (value: number) => Number(value.toFixed(6))
  const bounds = (start: string, end: string) => [start, end].map(key => rounded(e0 + (effective[key] as number)))
  await expect.poll(() => graph.evaluate(element => {
    const graph = element as HTMLElement & {
      data: { name?: string; mode?: string; x: number[] }[]
      layout: { annotations?: { text: string; x: number }[]; shapes?: { x0: number; x1: number }[] }
    }
    const marker = (name: string) => graph.data.find(trace => trace.mode === "markers" && trace.name?.startsWith(name))
      ?.x.map(value => Number(value.toFixed(6)))
    return {
      pre: marker("Pre-edge bounds"),
      post: marker("Post-edge bounds"),
      e0: graph.layout.shapes?.map(shape => [shape.x0, shape.x1]),
      annotation: graph.layout.annotations?.map(annotation => ({ x: annotation.x, text: annotation.text })),
    }
  })).toEqual({
    pre: bounds("pre1", "pre2"),
    post: bounds("norm1", "norm2"),
    e0: [[e0, e0]],
    annotation: [{ x: e0, text: `E₀ = ${e0.toFixed(3)} eV` }],
  })
}

test("focused normalization edits process and move E₀ and interval markers without blurring", async ({ page }) => {
  test.setTimeout(150_000)
  await page.setViewportSize({ width: 1500, height: 1040 })
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  const initial = await loadCopper(page)
  const viewer = page.getByRole("region", { name: "Single spectrum viewer", exact: true })
  await viewer.getByRole("checkbox", { name: "Pre-edge line", exact: true }).check()
  await viewer.getByRole("checkbox", { name: "Post-edge line", exact: true }).check()
  const graph = viewer.getByLabel("E-space spectrum plot", { exact: true }).locator(".js-plotly-plot")
  await expectProcessedMarkers(graph, initial.groups[0])

  // Hold the first real processing request so focus is checked while it is in
  // flight, not only after a fast response has already re-enabled the form.
  let releaseRequest!: () => void
  const requestGate = new Promise<void>(resolve => { releaseRequest = resolve })
  let firstParameterRequest = true
  await page.route("**/api/backend/api/athena/projects/*/command", async route => {
    if (firstParameterRequest && route.request().postDataJSON().action === "parameters") {
      firstParameterRequest = false
      await requestGate
    }
    await route.continue()
  })

  const edits = [
    { key: "e0", label: /^E₀/, value: null },
    { key: "pre1", label: /^Pre-edge start/, value: -150 },
    { key: "pre2", label: /^Pre-edge end/, value: -40 },
    { key: "norm1", label: /^Post-edge start/, value: 80 },
    { key: "norm2", label: /^Post-edge end/, value: 700 },
  ] as const
  let latest = initial
  for (const [index, edit] of edits.entries()) {
    await test.step(`process ${edit.key} while its input stays focused`, async () => {
      const field = page.getByRole("spinbutton", { name: edit.label })
      const saved = page.waitForResponse(response => response.url().endsWith("/command") &&
        response.request().postDataJSON().action === "parameters")
      const previous = Number(await field.inputValue())
      if (edit.value === null) {
        await field.focus()
        await field.press("ArrowUp")
      } else {
        await field.fill(String(edit.value))
      }
      const requested = Number(await field.inputValue())
      expect(requested).not.toBe(previous)
      await expect(field).toBeFocused()
      if (index === 0) {
        try {
          await expect.poll(() => firstParameterRequest, { timeout: 10_000 }).toBe(false)
          await expect(field).toBeEnabled()
          await expect(field).toBeFocused()
        } finally {
          releaseRequest()
        }
      }
      const response = await saved
      expect(response.ok()).toBe(true)
      latest = await response.json() as AthenaProject
      const processed = latest.groups.find(group => group.id === initial.groups[0].id)!
      expect(processed.processing_error).toBeNull()
      expect(processed.parameters[edit.key]).toBe(requested)
      await expectProcessedMarkers(graph, processed)
      await expect(field).toBeEnabled()
      await expect(field).toBeFocused()
      await expect(field).toHaveValue(String(requested))
    })
  }
  const savedResponse = await page.request.get(`/api/backend/api/athena/projects/${initial.id}?view=parameters`)
  expect(savedResponse.ok()).toBe(true)
  expect((await savedResponse.json()).version).toBe(latest.version)
  expect(errors).toEqual([])
})
