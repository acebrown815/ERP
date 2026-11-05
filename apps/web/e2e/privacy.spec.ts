import { expect, test } from "@playwright/test";

import { PASSWORD, signIn } from "./helpers";

type Employee = { id: string; full_name: string };

test("an employee can't see a colleague's pay", async ({ page, playwright, baseURL }) => {
  // What a finance manager can reach, to compare against. Also proves the refusals below aren't just bad addresses.
  const finance = await playwright.request.newContext({ baseURL });
  const login = await finance.post("/api/v1/auth/login", { data: { email: "finance@example.com", password: PASSWORD } });
  expect(login.ok()).toBe(true);
  const staff = (await (await finance.get("/api/v1/employees?page_size=100")).json()) as { items: Employee[] };
  const colleague = staff.items.find((e) => e.full_name === "Employee A");
  expect(colleague).toBeDefined();
  const colleagueSalary = `/api/v1/employees/${colleague!.id}/salary`;
  expect((await finance.get(colleagueSalary)).ok()).toBe(true);
  await finance.dispose();

  await signIn(page, "bob@example.com");

  // Their own salary is there.
  await page.goto("/me");
  await expect(page.getByRole("heading", { name: "My salary" })).toBeVisible();
  await expect(page.getByText("Projected salary this period")).toBeVisible();

  // The colleague's isn't, on the screens or by asking the API directly with this session.
  await page.goto("/employees/salary");
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Employee A")).toHaveCount(0);

  await page.goto(`/employees/${colleague!.id}`);
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Employee A")).toHaveCount(0);

  const direct = await page.request.get(colleagueSalary);
  expect([403, 404]).toContain(direct.status());
});

test("signing in with the wrong password is refused", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("bob@example.com");
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});
