import { expect, test, type Page } from "@playwright/test"

import {
  datasetOf, mainMenu, openDialog, openMenu, openPage, openWorkbench, seedProject, selectSpectrum, settle, shoot, slug,
  spectra, type Dataset, type Spectrum,
} from "./screens"

/**
 * Every page, menu, viewer and main dialog of the workbench. The coverage list
 * is in README.md; keep the two in step.
 */

const menus = ["File", "Edit", "Data", "Process", "Analysis", "Search menu"]

/** Main-menu commands that open a dialog, by menu. Commands that act at once, download or pick a file are left out. */
const dialogs: Record<string, string[]> = {
  File: ["Open project…", "Import data…", "Save Craft project (.prj)", "Save complete web project", "Save marked project (.prj)",
    "Export column data…", "Project journal", "Plugin registry…", "Beamline identification…"],
  Edit: ["Review spectra…", "Compare spectra…", "Excel report on all data…", "Excel report on marked data…"],
  Data: ["Mark / freeze data…", "Group spectra…", "Processing settings…", "File metadata…", "Data information…", "Assign reference foil…"],
  Process: ["Calibrate energy", "Align scans", "Merge marked data", "Difference spectrum", "Sum marked data", "Rebin data",
    "Deglitch data", "Truncate data", "Smooth data", "Convolve data", "Deconvolve data", "Fluorescence self-absorption",
    "Dispersive energy calibration", "Fluorescence XAS from XRF fit", "Raw XRF spectra and maps", "Multi-electron excitation",
    "Copy parameter series", "Plot shortcuts…", "Diagnostic plots…"],
  Analysis: ["Linear combination fitting", "Principal component analysis", "XANES peak fitting", "Log-ratio & phase difference"],
}

const plotSpaces = ["E Energy", "k EXAFS", "R Fourier", "q Back transform"]

const projects: Partial<Record<Dataset, string>> = {}
test.beforeAll(async ({ playwright }, info) => {
  const request = await playwright.request.newContext({ baseURL: info.project.use.baseURL })
  projects.copper = await seedProject(request, "copper")
  projects.demo = await seedProject(request, "demo")
  await request.dispose()
})

async function openSpectrum(page: Page, spectrum: Spectrum) {
  await openWorkbench(page, projects[datasetOf[spectrum]])
  await selectSpectrum(page, spectrum)
}

test.describe("pages", () => {
  test("empty workbench", async ({ page }) => {
    await openWorkbench(page)
    await shoot(page, "page-empty-workbench")
  })

  test("classic workbench", async ({ page }) => {
    await openPage(page, "/classic")
    await shoot(page, "page-classic")
  })

  test("element picker artefact", async ({ page }) => {
    await openPage(page, "/artefacts/element-picker")
    await shoot(page, "page-element-picker")
    await page.locator("[aria-haspopup=dialog]").first().click()
    await settle(page)
    await shoot(page, "page-element-picker-open")
  })

  test("copper examples loaded from the File menu", async ({ page }) => {
    await openWorkbench(page)
    await openMenu(page, "File")
    await mainMenu(page).getByRole("button", { name: "Load copper examples", exact: true }).click()
    await expect(page.getByRole("heading", { name: /^Data 5\b/, level: 2 })).toBeVisible({ timeout: 240_000 })
    await settle(page)
    await shoot(page, "page-copper-examples-loaded")
  })

  test("demo cases loaded from the data list", async ({ page }) => {
    await openWorkbench(page)
    await page.getByRole("button", { name: "Load demo cases", exact: true }).click()
    await expect(page.getByRole("heading", { name: /^Data 9\b/, level: 2 })).toBeVisible({ timeout: 240_000 })
    await settle(page)
    await shoot(page, "page-demo-cases-loaded")
  })
})

test.describe("menus", () => {
  for (const state of ["empty", "copper"] as const) {
    test(`main menus · ${state}`, async ({ page }) => {
      if (state === "empty") await openWorkbench(page)
      else await openSpectrum(page, "copper")
      for (const menu of menus) {
        await openMenu(page, menu)
        await shoot(page, `menu-${state}-${slug(menu)}`)
        await page.keyboard.press("Escape")
      }
    })
  }

  test("data actions and viewer export menus · copper", async ({ page }) => {
    await openSpectrum(page, "copper")
    await page.getByRole("button", { name: "Actions for current data", exact: true }).click()
    await settle(page)
    await shoot(page, "menu-copper-data-actions")
    await page.keyboard.press("Escape")
    await page.getByRole("button", { name: "Export Single spectrum viewer", exact: true }).click()
    await settle(page)
    await shoot(page, "menu-copper-viewer-export")
  })
})

for (const spectrum of Object.keys(spectra) as Spectrum[]) {
  test.describe(`${spectrum} · ${spectra[spectrum]}`, () => {
    test("workbench and parameter panels", async ({ page }) => {
      await openSpectrum(page, spectrum)
      await shoot(page, `${spectrum}-workbench`)
      await shoot(page.locator("#athena-data-groups"), `${spectrum}-data-list`)
      const parameters = page.locator("#athena-processing-parameters")
      for (const tab of ["Processing", "EXAFS fitting"]) {
        await parameters.getByRole("tab", { name: tab, exact: true }).click()
        await settle(page)
        await shoot(parameters, `${spectrum}-parameters-${slug(tab)}`)
      }
    })

    test("spectrum viewers", async ({ page }) => {
      await openSpectrum(page, spectrum)
      for (const name of ["Single spectrum viewer", "Multiple spectra viewer"]) {
        const viewer = page.getByRole("region", { name, exact: true })
        for (const space of plotSpaces) {
          await viewer.getByRole("tab", { name: space, exact: true }).click()
          await settle(page)
          await shoot(viewer, `${spectrum}-${slug(name)}-${slug(space)}`)
        }
      }
    })

    test("wavelet, structure, path and fit viewers", async ({ page }) => {
      await openSpectrum(page, spectrum)
      for (const name of ["Wavelet plotter", "CIF structure viewer", "FEFF path viewer", "EXAFS fit results"]) {
        const viewer = page.getByRole("region", { name, exact: true })
        await viewer.scrollIntoViewIfNeeded()
        await settle(page)
        await shoot(viewer, `${spectrum}-${slug(name)}`)
      }
    })
  })
}

test.describe("dialogs · copper", () => {
  for (const [menu, commands] of Object.entries(dialogs)) {
    for (const command of commands) {
      test(`${menu} › ${command}`, async ({ page }) => {
        // Recent local projects lists every project in the data root, which grows with
        // each test; show only the one open here.
        if (command === "Open project…") await page.route(/\/api\/athena\/projects$/, async route => {
          if (route.request().method() !== "GET") return route.fallback()
          const response = await route.fetch()
          const rows = await response.json() as { id: string }[]
          await route.fulfill({ response, json: rows.filter(row => row.id === projects.copper) })
        })
        await openSpectrum(page, "copper")
        await openDialog(page, menu, command)
        await shoot(page, `dialog-${slug(menu)}-${slug(command)}`)
        await page.unrouteAll({ behavior: "ignoreErrors" })
      })
    }
  }

  test("Search menu › Report a bug or feedback…", async ({ page }) => {
    await openSpectrum(page, "copper")
    await openMenu(page, "Search menu")
    await page.getByRole("button", { name: /Report a bug or feedback/ }).click()
    await expect(page.locator("dialog[open], [role=dialog]").last()).toBeVisible()
    await settle(page)
    await shoot(page, "dialog-help-report-a-bug")
  })
})
