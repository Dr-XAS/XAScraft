import { expect, test, type Locator, type Page } from "@playwright/test"
import type { AthenaGroupFolder, AthenaProject } from "../../lib/athena"

type ProjectSummary = Pick<AthenaProject, "id" | "version"> & {
  groups: { id: string; label: string; marked: boolean }[]
}

test.use({ viewport: { width: 1440, height: 1400 }, actionTimeout: 15000 })

async function prepareProject(page: Page, batch = false) {
  const created = await page.request.post("/api/backend/api/athena/projects", { data: { name: "Folder drag check" } })
  expect(created.ok()).toBe(true)
  let project = await created.json() as ProjectSummary
  const endpoint = `/api/backend/api/athena/projects/${project.id}`
  async function setupCommand(action: string, group_ids: string[], options: Record<string, unknown>) {
    const response = await page.request.post(`${endpoint}/command?view=summary`, {
      data: { version: project.version, action, group_ids, options },
    })
    expect(response.ok(), await response.text()).toBe(true)
    project = await response.json() as ProjectSummary
  }
  await setupCommand("example", [], {})
  await setupCommand("metadata", project.groups.map(group => group.id), { marked: false })
  if (batch) await setupCommand("metadata", project.groups.slice(0, 2).map(group => group.id), { marked: true })
  const folders: AthenaGroupFolder[] = batch ? [
    { id: "source", name: "Source", group_ids: project.groups.slice(0, 2).map(group => group.id) },
    { id: "target", name: "Target", group_ids: [project.groups[2].id] },
  ] : [{ id: "target", name: "Target", group_ids: [] }]
  // A final organization command also avoids the copper demo's model autosave.
  await setupCommand("project", [], { group_folders: folders })
  await page.addInitScript(id => localStorage.setItem("athena.project", id), project.id)
  await page.goto("/")
  await expect(page.locator("#athena-data-groups .ath-group[data-group-id]")).toHaveCount(project.groups.length)
  await expect(page.getByRole("button", { name: "Import data", exact: true })).toBeEnabled()
  return project
}

function row(page: Page, id: string) {
  return page.locator(`#athena-data-groups .ath-group[data-group-id="${id}"]`)
}

async function drag(page: Page, source: Locator, target: Locator, position: "center" | "before" = "center") {
  await source.scrollIntoViewIfNeeded()
  await target.scrollIntoViewIfNeeded()
  const from = await source.boundingBox()
  const to = await target.boundingBox()
  expect(from).not.toBeNull()
  expect(to).not.toBeNull()
  await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2)
  await page.mouse.down()
  await page.mouse.move(to!.x + to!.width / 2, to!.y + to!.height * (position === "before" ? .2 : .5), { steps: 12 })
  await page.mouse.up()
}

async function command(page: Page, action: string, trigger: () => Promise<unknown>) {
  const waiting = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/command") &&
    response.request().postDataJSON().action === action)
  await trigger()
  const response = await waiting
  expect(response.ok(), await response.text()).toBe(true)
  await expect(page.locator(".ath-autosaved")).toHaveText("Saved locally")
  return await response.json() as AthenaProject
}

test("title and handle drag move data into a collapsed folder and out again, with reload and undo", async ({ page }) => {
  test.setTimeout(120000)
  const project = await prepareProject(page)
  const source = project.groups[0]
  const folder = page.getByRole("group", { name: "Target data group", exact: true })
  await page.getByRole("button", { name: "Collapse Target group", exact: true }).click()
  const grouped = await command(page, "project", () =>
    drag(page, row(page, source.id).locator(".ath-group-select"), folder.locator(".ath-group-folder-heading")))
  expect(grouped.group_folders).toEqual([{ id: "target", name: "Target", group_ids: [source.id] }])
  await expect(row(page, source.id)).toHaveAttribute("data-group-folder-id", "target")
  await expect(page.getByRole("button", { name: "Collapse Target group", exact: true })).toBeVisible()

  await page.reload()
  await expect(row(page, source.id)).toHaveAttribute("data-group-folder-id", "target")
  const ungrouped = await command(page, "project", () =>
    drag(page, row(page, source.id).locator(".ath-group-drag-handle"),
      page.getByRole("region", { name: "Ungrouped data drop area", exact: true })))
  expect(ungrouped.group_folders).toEqual([{ id: "target", name: "Target", group_ids: [] }])
  expect(ungrouped.groups.at(-1)?.id).toBe(source.id)
  await expect(row(page, source.id)).not.toHaveAttribute("data-group-folder-id")
  await expect(folder).toBeVisible()
  await expect(folder.locator(".ath-group")).toHaveCount(0)
  expect(Object.fromEntries(ungrouped.groups.map(group => [group.id, group])))
    .toEqual(Object.fromEntries(grouped.groups.map(group => [group.id, group])))

  await page.reload()
  await expect(row(page, source.id)).not.toHaveAttribute("data-group-folder-id")
  await expect(folder).toBeVisible()
  const undone = await command(page, "undo", () => page.getByRole("button", { name: "Undo", exact: true }).click())
  expect(undone.group_folders).toEqual(grouped.group_folders)
  await expect(row(page, source.id)).toHaveAttribute("data-group-folder-id", "target")
  await command(page, "redo", () => page.getByRole("button", { name: "Redo", exact: true }).click())
  await expect(row(page, source.id)).not.toHaveAttribute("data-group-folder-id")
  await expect(folder.locator(".ath-group")).toHaveCount(0)
})

test("marked data can leave a folder in sorted view and move before a root row in Manual order", async ({ page }) => {
  test.setTimeout(120000)
  const project = await prepareProject(page, true)
  const [first, second, targetMember, , anchor] = project.groups
  const movingIds = [first.id, second.id]
  const sourceFolder = page.getByRole("group", { name: "Source data group", exact: true })
  const targetFolder = page.getByRole("group", { name: "Target data group", exact: true })
  const sort = page.getByRole("combobox", { name: "Sort spectra", exact: true })
  await sort.selectOption("name")
  const out = await command(page, "project", () =>
    drag(page, row(page, first.id).locator(".ath-group-drag-handle"),
      page.getByRole("region", { name: "Ungrouped data drop area", exact: true })))
  expect(out.groups.slice(-2).map(group => group.id)).toEqual(movingIds)
  for (const id of movingIds) await expect(row(page, id)).not.toHaveAttribute("data-group-folder-id")
  await expect(sourceFolder.locator(".ath-group")).toHaveCount(0)
  await expect(sort).toHaveValue("name")

  await command(page, "project", () =>
    drag(page, row(page, first.id).locator(".ath-group-select"), targetFolder.locator(".ath-group-folder-heading")))
  for (const id of movingIds) await expect(row(page, id)).toHaveAttribute("data-group-folder-id", "target")
  await sort.selectOption("manual")
  const placed = await command(page, "project", () =>
    drag(page, row(page, first.id).locator(".ath-group-drag-handle"), row(page, anchor.id), "before"))
  const order = placed.groups.map(group => group.id)
  expect(order.slice(order.indexOf(anchor.id) - 2, order.indexOf(anchor.id))).toEqual(movingIds)
  expect(placed.group_folders).toEqual([
    { id: "source", name: "Source", group_ids: [] },
    { id: "target", name: "Target", group_ids: [targetMember.id] },
  ])
  expect(Object.fromEntries(placed.groups.map(group => [group.id, group])))
    .toEqual(Object.fromEntries(out.groups.map(group => [group.id, group])))
  await page.reload()
  await expect(sort).toHaveValue("manual")
  for (const id of movingIds) await expect(row(page, id)).not.toHaveAttribute("data-group-folder-id")
  await expect(sourceFolder).toBeVisible()
  await expect(targetFolder.locator(".ath-group")).toHaveCount(1)
  await expect.poll(() => page.locator('#athena-data-groups .ath-group[data-reorder-scope="root:ungrouped"]')
    .evaluateAll(elements => elements.map(element => element.getAttribute("data-group-id"))))
    .toEqual(order.filter(id => id !== targetMember.id))
})
