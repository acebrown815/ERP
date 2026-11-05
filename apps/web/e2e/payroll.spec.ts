import { expect, test } from "@playwright/test";

import { boardCell, boardRow, pick, signIn, submitPayment } from "./helpers";

// docs/architecture.md, Section 16, through the screens. The demo data already has a $10,000 receipt split 60/40
// between Employee A and Employee B. This adds $5,000, so they reach $9,000 and $6,000 in the salary period.
// The formula's rate rises from 8% at $3,000 to 30% at $30,000:
//   A: 9,000 x (8% + 22% x 6,000 / 27,000) = 1,160.00
//   B: 6,000 x (8% + 22% x 3,000 / 27,000) =   626.67
test("a customer receipt is split, becomes salary, and the salary is paid", async ({ page }) => {
  await signIn(page, "finance@example.com");

  // Record the receipt. Choosing the project fills in its 60/40 split.
  await page.goto("/accounting/payment-entries/new");
  await page.getByLabel("Purpose").selectOption({ label: "Project / Customer Payment" });
  await pick(page, "party", "Customer ABC");
  await pick(page, "paid_to", "Company Checking");
  await page.getByLabel("Method").selectOption({ label: "Bank Transfer" });
  await page.locator("#amount").fill("5000");
  await pick(page, "project", "ABC Web Platform");
  await submitPayment(page);

  const split = page.locator("tr", { hasText: "Employee A" });
  await expect(split).toContainText("60%");
  await expect(split).toContainText("3,000.00");
  await expect(page.locator("tr", { hasText: "Employee B" })).toContainText("2,000.00");
  await expect(page.getByText("Ledger entry")).toBeVisible();

  // The salary board shows what each person earned from it.
  await page.goto("/employees/salary");
  const a = boardRow(page, "Employee A");
  const b = boardRow(page, "Employee B");
  await expect(b).toBeVisible();
  await expect(await boardCell(page, a, "Revenue")).toHaveText("9,000.00");
  await expect(await boardCell(page, a, "Calculated")).toHaveText("1,160.00");
  await expect(await boardCell(page, b, "Revenue")).toHaveText("6,000.00");
  await expect(await boardCell(page, b, "Calculated")).toHaveText("626.67");
  await expect(await boardCell(page, b, "Balance")).toHaveText("626.67");

  // Pay Employee B from the board: the form arrives filled in.
  await b.getByRole("link", { name: "Pay" }).click();
  await expect(page.locator("#amount")).toHaveValue("626.67");
  await pick(page, "paid_from", "Company Checking");
  await page.getByLabel("Method").selectOption({ label: "Bank Transfer" });
  await submitPayment(page);

  // Paid and settled, and Employee A is unaffected.
  await page.goto("/employees/salary");
  await expect(await boardCell(page, b, "Paid")).toHaveText("626.67");
  await expect(await boardCell(page, b, "Balance")).toHaveText("0.00");
  await expect(await boardCell(page, a, "Balance")).toHaveText("1,160.00");
});
