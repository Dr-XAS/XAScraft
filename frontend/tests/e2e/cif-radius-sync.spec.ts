import { expect, test } from "@playwright/test"
import type { ArtemisFeffRequest } from "../../lib/artemis-structures"

test("the CIF viewer shares its radius with FEFF generation and EXAFS simulation", async ({ page }) => {
  test.setTimeout(180_000)
  const feffRequests: ArtemisFeffRequest[] = []
  page.on("request", request => {
    if (request.method() === "POST" && request.url().endsWith("/feff/jobs")) feffRequests.push(request.postDataJSON())
  })
  await page.setViewportSize({ width: 1500, height: 1000 })
  await page.goto("/")
  await page.getByRole("tab", { name: "EXAFS fitting", exact: true }).click()
  const structures = page.getByRole("region", { name: "Project CIF structures", exact: true })
  await expect(structures.getByRole("button", { name: "Upload CIF", exact: true })).toBeEnabled()
  const source = await page.request.get("/api/backend/api/artemis/structures/13088")
  expect(source.ok()).toBe(true)
  const { cif } = await source.json() as { cif: string }
  const attaching = page.waitForResponse(response => /\/projects\/[^/]+\/structures$/.test(response.url()) && response.request().method() === "POST")
  const picker = page.waitForEvent("filechooser")
  await structures.getByRole("button", { name: "Upload CIF", exact: true }).click()
  await (await picker).setFiles({ name: "radius-sync-copper.cif", mimeType: "chemical/x-cif", buffer: Buffer.from(cif) })
  const attachedResponse = await attaching
  expect(attachedResponse.ok()).toBe(true)
  const attached = await attachedResponse.json()
  const attachment = attached.artemis_structures[0]
  const name = attachment.label || attachment.structure.mineral || attachment.structure.formula
  await page.getByRole("dialog", { name: "Crystal structures", exact: true }).getByRole("button", { name: "Close CIF search", exact: true }).click()

  const dock = page.getByRole("region", { name: "CIF structure viewer", exact: true })
  const dockRadius = dock.getByRole("spinbutton", { name: "CIF display radius", exact: true })
  await expect(dockRadius).toHaveValue("5")
  await dockRadius.fill("3.4")
  await dockRadius.press("Tab")
  await expect(dock.getByRole("slider", { name: "CIF display radius", exact: true })).toHaveValue("3.4")
  expect(feffRequests).toHaveLength(0)

  await page.getByRole("button", { name: "Generate FEFF paths", exact: true }).click()
  const feff = page.getByRole("dialog", { name: "FEFF paths", exact: true })
  await expect(feff.getByRole("spinbutton", { name: "FEFF cluster radius", exact: true })).toHaveValue("3.4")
  await expect(feff.getByRole("spinbutton", { name: "CIF display radius", exact: true })).toHaveValue("3.4")
  await expect(feff.getByRole("spinbutton", { name: "FEFF maximum path radius", exact: true })).toHaveValue("3.4")
  await feff.getByRole("radio", { name: "Absorber site 1", exact: true }).check()
  await feff.getByLabel("FEFF maximum legs", { exact: true }).selectOption("2")
  await feff.getByLabel("FEFF maximum paths", { exact: true }).fill("6")
  expect(feffRequests).toHaveLength(0)
  const generating = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/feff/jobs"))
  await feff.getByRole("button", { name: "Run FEFF calculation", exact: true }).click()
  const generated = await generating
  expect(generated.ok()).toBe(true)
  expect((await generated.json()).request).toMatchObject({ attachment_id: attachment.id, cluster_radius: 3.4, path_radius: 3.4 })
  await expect(feff.getByText("FEFF calculation complete", { exact: true })).toBeVisible({ timeout: 60_000 })
  expect(feffRequests).toHaveLength(1)
  await feff.getByRole("button", { name: "Close FEFF paths", exact: true }).click()

  await structures.getByRole("button", { name: `Simulate EXAFS from ${name} CIF`, exact: true }).click()
  const simulation = page.getByRole("dialog", { name: "Simulate EXAFS", exact: true })
  await expect(simulation.getByRole("spinbutton", { name: "FEFF cluster radius", exact: true })).toHaveValue("3.4")
  await expect(simulation.getByRole("spinbutton", { name: "CIF display radius", exact: true })).toHaveValue("3.4")
  await expect(simulation.getByRole("spinbutton", { name: "Simulation maximum R", exact: true })).toHaveValue("3.4")
  expect(feffRequests).toHaveLength(1)
  const simulating = page.waitForResponse(response => response.url().endsWith("/simulate") && response.request().method() === "POST")
  await simulation.getByRole("button", { name: "Run EXAFS simulation", exact: true }).click()
  const simulated = await simulating
  expect(simulated.ok()).toBe(true)
  const result = await simulated.json()
  expect(result.source.request).toMatchObject({ attachment_id: attachment.id, cluster_radius: 3.4, path_radius: 3.4 })
  expect(feffRequests).toHaveLength(2)
  await simulation.getByRole("button", { name: "Export Simulated EXAFS", exact: true }).click()
  await expect(page.getByRole("menu", { name: "Export Simulated EXAFS", exact: true }).getByRole("menuitem", { name: "Simulation + sources (JSON)", exact: true })).toBeEnabled()
  await page.keyboard.press("Escape")

  await simulation.getByRole("spinbutton", { name: "FEFF cluster radius", exact: true }).fill("4.2")
  await expect(simulation.getByRole("spinbutton", { name: "CIF display radius", exact: true })).toHaveValue("4.2")
  await expect(simulation.getByRole("button", { name: "Export Simulated EXAFS", exact: true })).toHaveCount(0)
  await simulation.getByRole("button", { name: "Close EXAFS simulation", exact: true }).click()
  await expect(dockRadius).toHaveValue("4.2")
  expect(feffRequests).toHaveLength(2)

  await dockRadius.fill("2.6")
  await dockRadius.press("Tab")
  await page.getByRole("button", { name: "Generate FEFF paths", exact: true }).click()
  await expect(feff.getByRole("spinbutton", { name: "FEFF cluster radius", exact: true })).toHaveValue("2.6")
  await expect(feff.getByRole("button", { name: "Run FEFF calculation", exact: true })).toBeDisabled()
  await expect(feff.getByText("FEFF requires a cluster radius from 3 to 6 Å. Adjust the cluster or CIF display radius before calculating.", { exact: true })).toBeVisible()
  expect(feffRequests).toHaveLength(2)
})
