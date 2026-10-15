import { expect, test, type Locator, type Page } from "@playwright/test"
import { readFile } from "node:fs/promises"

async function exportFile(page: Page, viewer: Locator, choice: string) {
  await viewer.getByRole("button", { name: /^Export / }).click()
  const downloaded = page.waitForEvent("download")
  await page.getByRole("menuitem", { name: choice, exact: true }).click()
  const download = await downloaded
  expect(await download.failure()).toBeNull()
  const content = await readFile((await download.path())!)
  expect(content.length).toBeGreaterThan(30)
  return { filename: download.suggestedFilename(), content }
}

test("viewer heading menus download scientific data and current plot/structure images", async ({ page }, info) => {
  test.setTimeout(180_000)
  const errors: string[] = []
  page.on("pageerror", error => errors.push(error.message))
  await page.setViewportSize({ width: 1500, height: 1000 })
  await page.goto("/")
  await page.getByRole("button", { name: "Load copper examples", exact: true }).click()
  await expect(page.locator(".ath-autosaved")).toHaveText("Saved locally", { timeout: 60_000 })

  const single = page.getByRole("region", { name: "Single spectrum viewer", exact: true })
  const multiple = page.getByRole("region", { name: "Multiple spectra viewer", exact: true })
  const wavelet = page.getByRole("region", { name: "Wavelet plotter", exact: true })
  const cif = page.getByRole("region", { name: "CIF structure viewer", exact: true })
  const feff = page.getByRole("region", { name: "FEFF path viewer", exact: true })
  const fit = page.getByRole("region", { name: "EXAFS fit results", exact: true })
  for (const viewer of [single, multiple, wavelet, cif, feff, fit]) {
    await expect(viewer.locator("header").getByRole("button", { name: /^Export / })).toHaveText("export")
  }
  await expect(single.locator(".js-plotly-plot")).toBeVisible()
  const csv = await exportFile(page, single, "Data (CSV)")
  expect(csv.filename).toMatch(/\.csv$/)
  expect(csv.content.toString()).toContain("energy")
  const multipleCsv = await exportFile(page, multiple, "Data (CSV)")
  expect(multipleCsv.content.toString()).toContain("data_id,data_label")

  const image = await exportFile(page, single, "Image (PNG)")
  expect(image.content.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a")
  const svg = await exportFile(page, single, "Image (SVG)")
  expect(svg.content.toString()).toContain("<svg")
  await expect(cif.locator("canvas")).toBeVisible()
  const structurePng = await exportFile(page, cif, "Image (PNG)")
  expect(structurePng.content.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a")
  const structure = await exportFile(page, cif, "CIF source (.cif)")
  expect(structure.content.toString()).toContain("_cell_length_a")
  await expect(feff.locator("canvas").first()).toBeVisible()
  const pathPng = await exportFile(page, feff, "3D structure image (PNG)")
  expect(pathPng.content.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a")
  const pathData = await exportFile(page, feff, "Path data (JSON)")
  expect(JSON.parse(pathData.content.toString()).paths.length).toBeGreaterThan(0)

  await expect(wavelet.locator(".js-plotly-plot").first()).toBeVisible({ timeout: 60_000 })
  const grid = await exportFile(page, wavelet, "Data (CSV)")
  expect(grid.content.toString()).toContain("R / k")
  const waveletSvg = await exportFile(page, wavelet, "Image (SVG)")
  expect(waveletSvg.content.toString().match(/<image /g)?.length).toBeGreaterThan(1)
  const waveletPng = await exportFile(page, wavelet, "Image (PNG)")
  expect(waveletPng.content.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a")
  expect(waveletPng.content.readUInt32BE(16)).toBeGreaterThan(1000)

  await single.scrollIntoViewIfNeeded()
  const trigger = single.getByRole("button", { name: /^Export / })
  await trigger.click()
  await expect(page.getByRole("menu")).toBeVisible()
  await page.screenshot({ path: info.outputPath("viewer-export-desktop.png") })
  await trigger.click()
  await expect(page.getByRole("menu")).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  await trigger.click()
  const menu = page.getByRole("menu")
  const bounds = (await menu.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390)
  await page.screenshot({ path: info.outputPath("viewer-export-mobile.png") })
  await menu.press("Escape")
  await expect(trigger).toBeFocused()
  expect(errors).toEqual([])
})
