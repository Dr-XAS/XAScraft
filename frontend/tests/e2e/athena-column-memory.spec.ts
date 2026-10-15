import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Locator, type Page } from '@playwright/test'

test.use({ actionTimeout: 10000 })

const measured = readFileSync(fileURLToPath(new URL('../../../examples/xafsdata/cu_10k.xmu', import.meta.url)), 'utf8')
  .split(/\r?\n/).filter(s => /^\s*[+\-.]?\d/.test(s)).map(s => s.trim().split(/\s+/).slice(0, 2).map(Number))
const content = Buffer.from('# energy incident transmitted channel channel monitor zero\n' + measured.map(([e, mu]) =>
  [e / 1000, 10000, 10000 * Math.exp(-mu), 10000 * mu, 5000 * mu, 10000 * Math.exp(-mu), 0].join(' ')).join('\n'))

async function open(page: Page, name: string, buffer = content) {
  await page.getByRole('button', { name: 'Import data', exact: true }).click()
  const response = page.waitForResponse(r => r.url().endsWith('/inspect'))
  await page.getByLabel('Choose data files', { exact: true }).setInputFiles({ name, mimeType: 'text/plain', buffer })
  const inspection = await (await response).json()
  const panel = page.getByRole('dialog')
  await expect(panel.getByRole('combobox', { name: 'Energy units', exact: true })).toBeVisible()
  return { inspection, panel }
}
async function curves(panel: Locator) {
  const region = panel.getByLabel('Imported signal preview plot')
  await expect(region).toHaveAttribute('aria-busy', 'false')
  await expect(region.locator('.js-line').first()).toBeAttached()
  return region.locator('.js-plotly-plot').evaluate(node => (node as HTMLElement & {
    data: { x: number[]; y: number[]; name: string }[]
  }).data.map(t => ({ x: [...t.x], y: [...t.y], name: t.name })))
}

test('remembered column choices restore real previews across sessions without accepting failed or cancelled choices', async ({ page, browser }, info) => {
  test.setTimeout(90000)
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  let { panel } = await open(page, 'first.dat')
  await panel.getByRole('combobox', { name: 'Measurement', exact: true }).selectOption('fluorescence')
  await expect(panel.getByRole('checkbox', { name: 'Enable EXAFS processing', exact: true })).toHaveCount(0)
  await panel.getByRole('combobox', { name: 'Energy units', exact: true }).selectOption('keV')
  await panel.getByRole('button', { name: 'Clear numerator', exact: true }).click()
  await panel.getByLabel('Numerator channel', { exact: true }).check()
  await panel.getByLabel('Numerator channel_col5', { exact: true }).check()
  await panel.getByRole('button', { name: 'Clear denominator', exact: true }).click()
  await panel.getByLabel('Denominator incident', { exact: true }).check()
  await panel.getByLabel('Denominator transmitted', { exact: true }).check()
  await panel.getByLabel('Save each channel as a separate data item', { exact: true }).check()
  await panel.getByLabel('Multiplicative constant', { exact: true }).fill('2')
  await panel.getByRole('tab', { name: 'Reference', exact: true }).click()
  await panel.getByRole('combobox', { name: 'reference numerator', exact: true }).selectOption({ label: 'incident · column 2' })
  await panel.getByRole('combobox', { name: 'reference denominator', exact: true }).selectOption({ label: 'monitor · column 6' })
  await expect(panel.getByText('Preprocess imported data', { exact: true })).toHaveCount(0)
  await expect(panel.getByText('Rebin quick scans', { exact: true })).toHaveCount(0)
  const original = await curves(panel)
  expect(original).toHaveLength(3) // Two detector channels and the reference preview.
  expect(original[0].x[200]).toBeCloseTo(measured[200][0], 10)
  expect(original[0].y[200]).toBeCloseTo(2 * measured[200][1] / (1 + Math.exp(-measured[200][1])), 12)
  const response = page.waitForResponse(r => r.url().endsWith('/import'))
  await panel.getByRole('button', { name: 'Import spectrum', exact: true }).click()
  const imported = await response; expect(imported.ok()).toBe(true)
  const accepted = await imported.json(); expect(accepted.groups).toHaveLength(4)
  expect(accepted.groups.map((g: { marked: boolean }) => g.marked)).toEqual([false, false, false, false])
  await expect(panel).not.toBeVisible()
  await page.reload()
  const restored = await open(page, 'after-reload.dat'); panel = restored.panel
  expect(restored.inspection.remembered_columns.matching_columns).toBe(true)
  const memoryVersion = restored.inspection.remembered_columns.version
  await expect(panel.getByLabel('Numerator channel', { exact: true })).toBeChecked()
  await expect(panel.getByLabel('Numerator channel_col5', { exact: true })).toBeChecked()
  await expect(panel.getByLabel('Denominator incident', { exact: true })).toBeChecked()
  await expect(panel.getByLabel('Denominator transmitted', { exact: true })).toBeChecked()
  await expect(panel.getByLabel('Save each channel as a separate data item', { exact: true })).toBeChecked()
  const restoredCurves = await curves(panel)
  expect(restoredCurves).toHaveLength(3)
  expect(restoredCurves.slice(0, 3)).toEqual(original.slice(0, 3))
  await panel.screenshot({ path: info.outputPath('remembered-column-preview.png') })
  await panel.getByRole('button', { name: 'Clear denominator', exact: true }).click()
  await panel.getByLabel('Denominator zero', { exact: true }).check()
  const failed = page.waitForResponse(r => r.url().endsWith('/import'))
  await panel.getByRole('button', { name: 'Import spectrum', exact: true }).click()
  expect((await failed).status()).toBe(400)
  await expect(panel.getByText(/zero detector counts/).first()).toBeVisible()
  await panel.getByRole('button', { name: 'Close dialog' }).click()
  const context = await browser.newContext({ baseURL: info.project.use.baseURL })
  try {
    const other = await context.newPage(); await other.goto('/')
    const again = await open(other, 'new-browser-session.dat')
    expect(again.inspection.remembered_columns.version).toBe(memoryVersion)
    await expect(again.panel.getByLabel('Denominator incident', { exact: true })).toBeChecked()
    await expect(again.panel.getByLabel('Denominator zero', { exact: true })).not.toBeChecked()
    await again.panel.getByLabel('Multiplicative constant', { exact: true }).fill('9')
    await again.panel.getByRole('button', { name: 'Close dialog' }).click()
    const changed = await open(other, 'different-layout.dat', Buffer.from(content.toString().replace('transmitted channel', 'transmitted changed_channel')))
    expect(changed.inspection.remembered_columns.version).toBe(memoryVersion)
    expect(changed.inspection.remembered_columns.matching_columns).toBe(false)
    await expect(changed.panel.getByText('Rebin quick scans', { exact: true })).toHaveCount(0)
    await expect(changed.panel.getByLabel('Save each channel as a separate data item', { exact: true })).not.toBeChecked()
    await expect(changed.panel.getByLabel('Multiplicative constant', { exact: true })).toHaveValue('2')
    await changed.panel.getByRole('button', { name: 'Use suggested columns' }).click()
    await expect(changed.panel.getByLabel('Multiplicative constant', { exact: true })).toHaveValue('1')
    await curves(changed.panel)
  } finally { await context.close() }
  const final = await (await page.request.get(`/api/backend/api/athena/projects/${accepted.id}`)).json()
  expect(final).toEqual(accepted)
  expect(errors).toEqual([])
})
