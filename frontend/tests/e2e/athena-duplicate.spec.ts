import { expect, test } from '@playwright/test'
import type { AthenaProject } from '../../lib/athena'

test('duplicate data merges the compact response and retains folder order through undo and redo', async ({ page, request }) => {
  test.setTimeout(90000)
  const created = await request.post('/api/backend/api/athena/projects', { data: {} })
  expect(created.ok()).toBe(true)
  let project = await created.json() as AthenaProject
  const endpoint = `/api/backend/api/athena/projects/${project.id}`
  const example = await request.post(`${endpoint}/command`, {
    data: { version: project.version, action: 'example', group_ids: [], options: {} },
  })
  expect(example.ok()).toBe(true)
  project = await example.json() as AthenaProject
  const source = project.groups[0]
  const organized = await request.post(`${endpoint}/command`, {
    data: { version: project.version, action: 'project', group_ids: [], options: {
      group_folders: [{ id: 'copper-series', name: 'Copper series', group_ids: project.groups.slice(0, 2).map(group => group.id) }],
    } },
  })
  expect(organized.ok()).toBe(true)
  project = await organized.json() as AthenaProject
  await page.addInitScript(id => localStorage.setItem('athena.project', id), project.id)
  await page.goto('/')
  const rows = page.locator('#athena-data-groups .ath-group[data-group-id]')
  await expect(rows).toHaveCount(project.groups.length)
  await expect(page.getByRole('button', { name: 'Import data', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Actions for current data', exact: true }).click()
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/command') && response.request().postDataJSON()?.action === 'duplicate')
  await page.getByRole('menuitem', { name: 'Duplicate current data', exact: true }).click()
  const response = await responsePromise
  expect(response.ok()).toBe(true)
  expect(response.request().postDataJSON().response_mode).toBe('duplicate')
  const delta = await response.json()
  expect(delta.kind).toBe('duplicate')
  expect(delta.groups).toHaveLength(1)
  const copy = delta.groups[0]
  expect(copy.energy).toEqual(source.energy)
  expect(copy.mu).toEqual(source.mu)
  expect(copy.result).toEqual(source.result)
  await expect(rows).toHaveCount(project.groups.length + 1)
  expect(await rows.evaluateAll(nodes => nodes.map(node => node.getAttribute('data-group-id')))).toEqual(delta.group_order)
  await expect(page.locator(`[data-group-id="${copy.id}"]`)).toHaveAttribute('data-group-folder-id', 'copper-series')
  await page.getByRole('button', { name: 'Undo', exact: true }).click()
  await expect(rows).toHaveCount(project.groups.length)
  await expect(page.locator(`[data-group-id="${copy.id}"]`)).toHaveCount(0)
  await page.getByRole('button', { name: 'Redo', exact: true }).click()
  await expect(rows).toHaveCount(project.groups.length + 1)
  await expect(page.locator(`[data-group-id="${copy.id}"]`)).toHaveAttribute('data-group-folder-id', 'copper-series')
})
