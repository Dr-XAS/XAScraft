import { expect, type Locator } from '@playwright/test'

export type ImportSignal = 'transmission' | 'fluorescence' | 'reference'
const title = (signal: ImportSignal) => signal[0].toUpperCase() + signal.slice(1)

/** Choose outputs independently of the tab used to edit their columns. */
export async function selectImportSignals(dialog: Locator, signals: ImportSignal[], active = signals[0]) {
  await expect(dialog.getByRole('combobox', { name: 'Energy column', exact: true })).toBeVisible()
  for (const signal of ['transmission', 'fluorescence', 'reference'] as const) {
    const checkbox = dialog.getByRole('checkbox', { name: `Import ${title(signal)}`, exact: true })
    if (await checkbox.count()) await checkbox.setChecked(signals.includes(signal))
  }
  if (active) {
    const tab = dialog.getByRole('tab', { name: title(active), exact: true })
    if (await tab.count()) await tab.click()
  }
}
