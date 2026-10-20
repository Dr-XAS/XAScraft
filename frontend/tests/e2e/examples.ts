import { type Page } from "@playwright/test"

export async function loadCopperExamples(page: Page) {
  const mainMenu = page.getByRole("navigation", { name: "Main menu", exact: true })
  const file = mainMenu.getByRole("button", { name: "File", exact: true })
  if (await file.getAttribute("aria-expanded") !== "true") await file.click()
  await mainMenu.getByRole("button", { name: "Load copper examples", exact: true }).click()
}
