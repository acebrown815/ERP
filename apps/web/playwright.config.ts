import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

// Runs against a production build and its own database (`erp_e2e`, rebuilt on every run by tests/e2e_prepare.py).
// Needs PostgreSQL running. The build replaces .next, so stop `tools/dev.py`'s web server first.
const API_PORT = 8100;
const WEB_PORT = 3100;
const apiUrl = `http://127.0.0.1:${API_PORT}`;
const python =
  process.env.E2E_PYTHON ?? (process.platform === "win32" ? path.join(".venv", "Scripts", "python.exe") : "python");
const databaseUrl = process.env.E2E_DATABASE_URL ?? "postgresql+asyncpg://erp:erp@127.0.0.1:54329/erp_e2e";

export default defineConfig({
  testDir: "./e2e",
  // The tests share one database and one set of demo people.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 1000 } } }],
  webServer: [
    {
      command: `${python} -m tests.e2e_prepare && ${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: path.join(__dirname, "..", "api"),
      url: `${apiUrl}/api/health/ready`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        ERP_DATABASE_URL: databaseUrl,
        ERP_ENV: "test",
        ERP_FAST_PASSWORD_HASHING: "true",
        ERP_ATTACHMENTS_DIR: path.join(__dirname, "..", "api", "var", "e2e", "attachments"),
        ERP_BACKUPS_DIR: path.join(__dirname, "..", "api", "var", "e2e", "backups"),
      },
    },
    {
      command: `npx next build && npx next start --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/login`,
      timeout: 420_000,
      reuseExistingServer: false,
      env: { API_URL: apiUrl, NEXT_TELEMETRY_DISABLED: "1" },
    },
  ],
});
