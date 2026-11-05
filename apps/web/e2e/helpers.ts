import { expect, type Locator, type Page } from "@playwright/test";

export const PASSWORD = "Demo-Pass-2026";

export async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
}

/** Choose from one of the searchable pickers. */
export async function pick(page: Page, id: string, option: string) {
  await page.locator(`#${id}`).click();
  await page.getByRole("option", { name: option }).click();
}

/** Submit the payment form, once its preview says the payment is valid, and wait for the saved payment's page. */
export async function submitPayment(page: Page) {
  const submit = page.getByRole("button", { name: "Submit", exact: true });
  await expect(submit).toBeEnabled({ timeout: 15_000 });
  await submit.click();
  await page.getByRole("button", { name: "Submit and post" }).click();
  await expect(page).toHaveURL(/\/accounting\/payment-entries\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Submitted", { exact: true }).first()).toBeVisible();
}

/** A row of the salary board, by employee name. */
export function boardRow(page: Page, employee: string): Locator {
  return page.getByRole("row").filter({ has: page.getByRole("link", { name: employee, exact: true }) });
}

/** The cell under a column heading of the salary board. */
export async function boardCell(page: Page, row: Locator, column: string): Promise<Locator> {
  await expect(page.locator("thead th").first()).toBeAttached();
  const headings = await page.locator("thead th").allTextContents();
  const index = headings.findIndex((h) => h.trim() === column);
  expect(index, `salary board column ${column}`).toBeGreaterThanOrEqual(0);
  return row.getByRole("cell").nth(index);
}
