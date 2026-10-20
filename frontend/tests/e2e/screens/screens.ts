import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test"

/**
 * Shared steps for the screenshot suite. The suite compares pixels with zero
 * tolerance, so every screen is reached the same way on every run: a project
 * seeded through the API, a fresh page, a fixed browser clock, and a settled
 * render. See README.md for what is covered and what is masked.
 */

/** Browser clock for every page: client-side dates render the same on every run. */
export const fixedTime = new Date("2026-01-02T03:04:05Z")

/** The app's base path: "" standalone, "/advanced-xas/app" for the mounted build. */
export function basePath(): string {
  return (test.info().project.metadata as { basePath?: string } | undefined)?.basePath ?? ""
}

export type Dataset = "copper" | "demo"

/** The spectra the screens select: copper and Cu₂O from the copper examples, NiO from the demo cases. */
export const spectra = {
  copper: "Cu foil · 10 K",
  cu2o: "Cu₂O · room temperature",
  demo: "NiO · transmission",
} as const
export type Spectrum = keyof typeof spectra
export const datasetOf: Record<Spectrum, Dataset> = { copper: "copper", cu2o: "copper", demo: "demo" }

type Project = { id: string; version: number }

/** A new project holding the copper examples, or the curated Ni, Cu and Fe demo cases. */
export async function seedProject(request: APIRequestContext, dataset: Dataset): Promise<string> {
  const api = `${basePath()}/api/backend/api/athena/projects`
  const created = await request.post(api, { data: { name: `Screens · ${dataset}` } })
  expect(created.ok(), await created.text()).toBe(true)
  const project = await created.json() as Project
  const options = dataset === "demo" ? { dataset: "curated-three-elements" } : {}
  const loaded = await request.post(`${api}/${project.id}/command`, {
    data: { version: project.version, action: "example", group_ids: [], options },
    timeout: 240_000,
  })
  expect(loaded.ok(), await loaded.text()).toBe(true)
  return project.id
}

/** Pin the browser clock and open a page of the app. */
export async function openPage(page: Page, path: string) {
  await page.clock.setFixedTime(fixedTime)
  await page.goto(`${basePath()}${path}`)
  await settle(page)
}

/** Open the workbench on a project, or on a new one. */
export async function openWorkbench(page: Page, projectId?: string) {
  await page.clock.setFixedTime(fixedTime)
  if (projectId) await page.addInitScript(id => localStorage.setItem("athena.project", id), projectId)
  await page.goto(`${basePath()}/`)
  await expect(page.getByRole("button", { name: "Process", exact: true })).toBeEnabled()
  await expect(page.getByRole("heading", { name: /^Data\b/, level: 2 })).toBeVisible()
  await settle(page)
}

/** Make a spectrum the current one by clicking it in the data list. */
export async function selectSpectrum(page: Page, spectrum: Spectrum) {
  const item = page.locator(".ath-group-select").filter({ hasText: spectra[spectrum] }).first()
  // Clicking the current spectrum again clears the selection.
  if (await item.getAttribute("aria-current") !== "true") await item.click()
  await expect(item).toHaveAttribute("aria-current", "true")
  await expect(page.getByRole("region", { name: "Single spectrum viewer", exact: true })).toContainText(spectra[spectrum])
  await settle(page)
}

/** Wait until requests, fonts, busy regions and plots have finished. */
export async function settle(page: Page) {
  await page.waitForLoadState("networkidle")
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  // The project bar reads "Working…" (or "Connecting", "Saving …", "… pending") while a task runs.
  await page.waitForFunction(() => !document.querySelector("[aria-busy='true']") &&
    !/^(Working|Connecting|Saving|Parameter changes pending)/.test(document.querySelector(".ath-autosaved")?.textContent ?? ""),
  undefined, { timeout: 60_000 })
  await page.waitForLoadState("networkidle")
}

/**
 * Fields that change on their own between runs, masked in every screenshot.
 * This is the only list; everything else is compared pixel for pixel.
 */
export function volatileFields(page: Page): Locator[] {
  return [
    // Open a project › Recent local projects: "<n> data items · <save time>", one text run.
    page.locator(".ath-recent small"),
  ]
}

/** Compare the viewport, or one element, with its snapshot. Soft: the test goes on to the next screen. */
export async function shoot(target: Page | Locator, name: string) {
  const page = "page" in target ? target.page() : target
  await expect.soft(target).toHaveScreenshot(`${name}.png`, { mask: volatileFields(page) })
}

export function mainMenu(page: Page) {
  return page.getByRole("navigation", { name: "Main menu", exact: true })
}

/** Open one entry of the main menu (File, Edit, …, Search menu). */
export async function openMenu(page: Page, menu: string) {
  const button = mainMenu(page).getByRole("button", { name: menu, exact: true })
  if (await button.getAttribute("aria-expanded") !== "true") await button.click()
  await settle(page)
}

/** Choose a main-menu command and wait for the dialog it opens. */
export async function openDialog(page: Page, menu: string, command: string) {
  await openMenu(page, menu)
  await mainMenu(page).getByRole("button", { name: command, exact: true }).click()
  await expect(page.locator("dialog[open], [role=dialog]").last()).toBeVisible()
  await settle(page)
}

/** File-name-safe slug of a label. */
export function slug(label: string): string {
  return label.normalize("NFKD").replace(/[₀-₉]/g, d => String(d.charCodeAt(0) - 0x2080)).toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}
