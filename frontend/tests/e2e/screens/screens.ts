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

/** Pin the browser clock and start counting requests; call before the first navigation. */
export async function preparePage(page: Page) {
  await page.clock.setFixedTime(fixedTime)
  watchTraffic(page)
}

/** Open a page of the app. */
export async function openPage(page: Page, path: string) {
  await preparePage(page)
  await page.goto(`${basePath()}${path}`)
  await settle(page)
}

/** Open the Athena workbench on a project, or on a new one. */
export async function openWorkbench(page: Page, projectId?: string) {
  await preparePage(page)
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

type Traffic = { inFlight: number; last: number }
const traffic = new WeakMap<Page, Traffic>()

/** Count the page's requests from now on (done by every open* helper before navigating). */
function watchTraffic(page: Page) {
  if (traffic.has(page)) return
  const state: Traffic = { inFlight: 0, last: Date.now() }
  traffic.set(page, state)
  page.on("request", () => { state.inFlight += 1; state.last = Date.now() })
  const done = () => { state.inFlight = Math.max(0, state.inFlight - 1); state.last = Date.now() }
  page.on("requestfinished", done)
  page.on("requestfailed", done)
}

/**
 * Wait until no request has been in flight for `quietMs`. Previews in the tool
 * dialogs fetch after a debounce longer than "networkidle"'s 500 ms, so that
 * alone can catch a dialog before its plot.
 */
async function quiet(page: Page, quietMs = 1500, timeoutMs = 90_000) {
  const state = traffic.get(page)
  if (!state) { await page.waitForLoadState("networkidle"); return }
  const deadline = Date.now() + timeoutMs
  while (state.inFlight > 0 || Date.now() - state.last < quietMs) {
    if (Date.now() > deadline) throw new Error(`requests still running after ${timeoutMs} ms`)
    await page.waitForTimeout(100)
  }
}

/** Wait until requests, fonts, busy regions and plots have finished. */
export async function settle(page: Page) {
  await quiet(page)
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  // The project bar reads "Working…" (or "Connecting", "Saving …", "… pending") while a task runs.
  await page.waitForFunction(() => !document.querySelector("[aria-busy='true']") &&
    !/^(Working|Connecting|Saving|Parameter changes pending)/.test(document.querySelector(".ath-autosaved")?.textContent ?? ""),
  undefined, { timeout: 60_000 })
  await quiet(page)
}

/**
 * Compare the viewport, or one element, with its snapshot. Soft: the test goes on
 * to the next screen. Fields that change on their own are masked by
 * volatile-fields.css, which the config applies to every screenshot.
 */
export async function shoot(target: Page | Locator, name: string) {
  await steady(target)
  await expect.soft(target).toHaveScreenshot(`${name}.png`)
}

/**
 * Wait until three screenshots 250 ms apart are identical. toHaveScreenshot only
 * needs two frames in a row, and right after a menu closes the compositor has
 * shown a stale tile (a piece of a plot where the menu was) for that long.
 */
async function steady(target: Page | Locator, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs
  const frames: Buffer[] = []
  while (Date.now() < deadline) {
    frames.push(await target.screenshot({ animations: "disabled", caret: "hide", scale: "css" }))
    if (frames.length >= 3 && frames.slice(-3).every(frame => frame.equals(frames.at(-1)!))) return
    await new Promise(resolve => setTimeout(resolve, 250))
  }
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
