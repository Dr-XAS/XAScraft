import { createHash, createHmac, randomBytes } from "node:crypto"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { expect, test, type APIRequestContext } from "@playwright/test"

import { basePath, fixedTime, openDialog, openMenu, settle, shoot } from "./screens"

/**
 * The Dr.XAS launch, which only the mounted build serves: a project created and
 * launched through the signed integration API, then one spectrum imported.
 * Same issuer, audience and secret as the config's backend.
 */

const fixture = path.resolve(fileURLToPath(new URL(".", import.meta.url)), "../../fixtures/cu_rt01.xmu")
const issuer = "playwright-drxas"
const audience = "playwright-athena"
const secret = "playwright-only-integration-secret-32-bytes"

function backendOrigin() {
  return (test.info().project.metadata as { backendOrigin: string }).backendOrigin
}

async function signed(request: APIRequestContext, route: string, body: unknown, capability?: string) {
  const raw = JSON.stringify(body)
  const timestamp = String(Math.floor(Date.now() / 1000))
  const nonce = randomBytes(24).toString("hex")
  const digest = createHash("sha256").update(raw).digest("hex")
  const signature = createHmac("sha256", secret).update(["v2", "POST", route, issuer, audience, timestamp, nonce, digest].join("\n")).digest("hex")
  const response = await request.fetch(`${backendOrigin()}${route}`, {
    method: "POST",
    data: raw,
    headers: {
      "content-type": "application/json",
      "X-DrXAS-Issuer": issuer,
      "X-DrXAS-Audience": audience,
      "X-DrXAS-Timestamp": timestamp,
      "X-DrXAS-Nonce": nonce,
      "X-DrXAS-Body-SHA256": digest,
      "X-DrXAS-Signature": signature,
      ...(capability ? { "X-XrayLarch-Project-Capability": capability } : {}),
    },
  })
  expect(response.ok(), await response.text()).toBe(true)
  return response.json()
}

test("Dr.XAS launch · linked project", async ({ page, request }) => {
  const project = await signed(request, "/api/integration/v2/projects", { contract_version: 2, name: "Screens · linked project", persistent: true }) as { project_id: string; capability: string }
  const { handle } = await signed(request, `/api/integration/v2/projects/${project.project_id}/launch`, { capability: project.capability }, project.capability) as { handle: string }

  await page.clock.setFixedTime(fixedTime)
  await page.goto(`${basePath()}/integration?launch=${encodeURIComponent(handle)}&return=%2Fadvanced-xas`)
  await expect(page.getByText("Linked project", { exact: true })).toBeVisible()
  await settle(page)
  await shoot(page, "linked-empty")

  await page.getByRole("button", { name: "Import data", exact: true }).click()
  await page.getByLabel("Choose data files", { exact: true }).setInputFiles(fixture)
  await settle(page)
  await shoot(page, "linked-import-dialog")
  await page.getByRole("button", { name: "Import spectrum", exact: true }).click()
  await expect(page.getByRole("heading", { name: /^Data 1\b/, level: 2 })).toBeVisible()
  await settle(page)
  await shoot(page, "linked-workbench")

  for (const menu of ["File", "Edit", "Data"]) {
    await openMenu(page, menu)
    await shoot(page, `linked-menu-${menu.toLowerCase()}`)
    await page.keyboard.press("Escape")
  }
  await openDialog(page, "Data", "Data information…")
  await shoot(page, "linked-dialog-data-information")
})
