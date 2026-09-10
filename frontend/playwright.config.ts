import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const rootDir = path.resolve(__dirname, "..");
const pythonExe = path.join(rootDir, ".venv", "Scripts", "python.exe");

export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  expect: {
    timeout: 15000,
  },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_TEST_BASE_URL || "http://127.0.0.1:13002",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: `"${pythonExe}" -m uvicorn tests.fixtures.e2e_server:app --port 18082 --host 127.0.0.1 --app-dir backend`,
      cwd: rootDir,
      url: "http://127.0.0.1:18082/e2e/health",
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: "npm run start -- -p 13002",
      cwd: __dirname,
      env: {
        NEXT_DIST_DIR: ".next-test",
      },
      url: "http://127.0.0.1:13002",
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
