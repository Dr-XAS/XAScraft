import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test, type Locator } from '@playwright/test'

// Synthetic detector counts derived from the bundled Cu foil. The arithmetic
// below gives independent expected values for each imported measurement.
const measured = readFileSync(fileURLToPath(new URL('../../../examples/xafsdata/cu_10k.xmu', import.meta.url)), 'utf8')
  .split(/\r?\n/).filter(line => /^\s*[+\-.]?\d/.test(line)).map(line => line.trim().split(/\s+/).slice(0, 2).map(Number))
const rows = measured.map(([energy, mu], index) => {
  const i0 = 10000 + 100 * Math.sin(index / 20)
  const it = i0 * Math.exp(-mu)
  return [energy, i0, it, i0 * (.2 + .5 * mu), it * Math.exp(-(.1 + .8 * mu)), it * Math.exp(-(.15 + .6 * mu))]
})
const content = Buffer.from('# Synthetic detector arithmetic from bundled Cu foil\n# Energy I0 It If Iref RefAlt\n'
  + rows.map(row => row.join(' ')).join('\n'))

type Curve = { name: string; x: number[]; y: number[] }
async function curves(panel: Locator): Promise<Curve[]> {
  const preview = panel.getByLabel('Imported signal preview plot', { exact: true })
  await expect(preview).toHaveAttribute('aria-busy', 'false')
  const plot = preview.locator('.js-plotly-plot')
  await expect(plot.locator('.js-line').first()).toBeAttached()
  return plot.evaluate(node => (node as HTMLElement & { data: Curve[] }).data.map(trace => ({
    name: trace.name, x: [...trace.x], y: [...trace.y],
  })))
}

function expectedSignals(referenceColumn = 4) {
  return {
    transmission: rows.map(row => Math.log(row[1] / row[2])),
    fluorescence: rows.map(row => row[3] / row[1]),
    reference: rows.map(row => Math.log(row[2] / row[referenceColumn])),
  }
}

function expectValues(actual: number[], expected: number[]) {
  expect(actual).toHaveLength(expected.length)
  for (const index of [0, 100, 300, expected.length - 1]) expect(actual[index]).toBeCloseTo(expected[index], 11)
}

async function expectReadableSelectedTab(tab: Locator) {
  await tab.hover()
  // Wait for the shared 120 ms background transition to finish before
  // assessing the selected/hovered tab's final colors.
  await expect.poll(() => tab.evaluate(node => {
    const style = getComputedStyle(node)
    const luminance = (color: string) => {
      const rgb = color.match(/[\d.]+/g)!.slice(0, 3).map(value => {
        const channel = Number(value) / 255
        return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
      })
      return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722
    }
    const foreground = luminance(style.color), background = luminance(style.backgroundColor)
    return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05)
  })).toBeGreaterThanOrEqual(4.5)
}

test('three measurement tabs keep every preview visible and import one shared reference', async ({ page }, info) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1400, height: 1000 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Import data', exact: true }).click()
  await page.getByLabel('Choose data files', { exact: true }).setInputFiles({ name: 'three-measurements.dat', mimeType: 'text/plain', buffer: content })
  const panel = page.getByRole('dialog', { name: 'Import spectra', exact: true })
  for (const name of ['Advanced import settings', 'Rebin quick scans', 'Preprocess imported data']) {
    await expect(panel.getByText(name, { exact: true })).toHaveCount(0)
  }
  for (const name of ['File plugins…', 'Reinspect selected file', 'Save grid as defaults', 'Load saved grid', 'Use Craft default grid']) {
    await expect(panel.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
  await expect(panel.getByRole('checkbox', { name: 'Plot reference', exact: true })).toHaveCount(0)
  await expect(panel.getByRole('combobox', { name: 'Measurement', exact: true })).toHaveCount(0)
  for (const signal of ['Transmission', 'Fluorescence', 'Reference']) {
    await expect(panel.getByRole('checkbox', { name: `Import ${signal}`, exact: true })).toBeChecked()
  }
  await expect(panel.getByRole('tab', { name: 'Transmission', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(panel.getByRole('button', { name: 'Import 3 spectra', exact: true })).toBeEnabled()

  const expected = expectedSignals()
  const original = await curves(panel)
  expect(original).toHaveLength(3)
  for (const [mode, values] of Object.entries(expected)) {
    const trace = original.find(candidate => candidate.name.toLowerCase().includes(mode))
    expect(trace, `${mode} is shown in the preview`).toBeDefined()
    expectValues(trace!.y, values)
    expectValues(trace!.x, rows.map(row => row[0]))
  }
  for (const tab of ['Fluorescence', 'Reference', 'Transmission']) {
    const selected = panel.getByRole('tab', { name: tab, exact: true })
    await selected.click()
    await expect(selected).toHaveAttribute('aria-selected', 'true')
    await expectReadableSelectedTab(selected)
    expect(await curves(panel)).toEqual(original)
  }

  await panel.getByRole('tab', { name: 'Reference', exact: true }).click()
  const referenceDenominator = panel.getByRole('combobox', { name: /reference denominator/i })
  const alternate = await referenceDenominator.locator('option').filter({ hasText: 'RefAlt · column' }).getAttribute('value')
  const primary = await referenceDenominator.locator('option').filter({ hasText: 'Iref · column' }).getAttribute('value')
  await referenceDenominator.selectOption(alternate!)
  await expect.poll(async () => (await curves(panel)).find(trace => /reference/i.test(trace.name))?.y[100])
    .toBeCloseTo(expectedSignals(5).reference[100], 11)
  const changed = await curves(panel)
  expect(changed).toHaveLength(3)
  expect(changed.filter(trace => !/reference/i.test(trace.name))).toEqual(original.filter(trace => !/reference/i.test(trace.name)))
  await referenceDenominator.selectOption(primary!)
  await expect.poll(async () => (await curves(panel)).find(trace => /reference/i.test(trace.name))?.y[100])
    .toBeCloseTo(expected.reference[100], 11)
  await panel.screenshot({ path: info.outputPath('three-measurements-reference-tab.png') })

  await page.setViewportSize({ width: 390, height: 844 })
  for (const tab of ['Transmission', 'Fluorescence', 'Reference']) {
    const selected = panel.getByRole('tab', { name: tab, exact: true })
    await selected.click()
    await expect(selected).toBeVisible()
    await expectReadableSelectedTab(selected)
    expect(await panel.evaluate(node => node.scrollWidth - node.clientWidth)).toBeLessThanOrEqual(1)
    expect(await curves(panel)).toEqual(original)
  }
  await panel.getByRole('tablist', { name: 'Signal columns' }).scrollIntoViewIfNeeded()
  await panel.screenshot({ path: info.outputPath('three-measurements-mobile-tabs.png') })
  await page.setViewportSize({ width: 1400, height: 1000 })

  const imported = page.waitForResponse(response => response.url().endsWith('/import') && response.request().method() === 'POST')
  await panel.getByRole('button', { name: 'Import 3 spectra', exact: true }).click()
  const response = await imported
  expect(response.ok()).toBe(true)
  expect(response.request().postDataJSON()).toMatchObject({ edge_policy: null,
    preprocessing: { mark: false, standard_id: null, copy_parameters: false, align: false } })
  expect(response.request().postDataJSON()).not.toHaveProperty('rebin')
  expect(response.request().postDataJSON()).not.toHaveProperty('rebin_grid')
  const project = await response.json()
  expect(project.groups).toHaveLength(3)
  const reference = project.groups.find((group: { source: { mapping: { is_reference?: boolean } } }) => group.source.mapping.is_reference)
  expect(reference).toBeDefined()
  const samples = project.groups.filter((group: { id: string }) => group.id !== reference.id)
  expect(samples.map((group: { reference_id: string }) => group.reference_id)).toEqual([reference.id, reference.id])
  expectValues(reference.mu, expected.reference)
  for (const mode of ['transmission', 'fluorescence'] as const) {
    const sample = samples.find((group: { source: { mapping: { mode: string } } }) => group.source.mapping.mode === mode)
    expect(sample).toBeDefined()
    expectValues(sample.mu, expected[mode])
  }
  for (const group of project.groups) expect(group.processing_error).toBeNull()
  await expect(panel).not.toBeVisible()
  await expect(page.getByRole('heading', { name: /^Data 3\b/ })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: /^Data 3\b/ })).toBeVisible()
  expect(errors).toEqual([])
})
