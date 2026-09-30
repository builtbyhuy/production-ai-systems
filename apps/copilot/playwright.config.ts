import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const root = path.resolve(__dirname, "../..");
const local = process.env.PAIS_E2E_PROFILE === "local";
const evidenceDir = process.env.PAIS_UI_EVIDENCE_DIR
  ? path.resolve(process.env.PAIS_UI_EVIDENCE_DIR)
  : path.join(root, "artifacts/ui-runs", local ? "local" : "fixture");
// The Python launcher selects its own locked interpreter for the API subprocess.
// These supervised commands target the documented Unix test profile.
const apiPython = process.env.PAIS_E2E_PYTHON || path.join(root, ".venv/bin/python");
const quotedApiPython = "'" + apiPython.replaceAll("'", "'\\''") + "'";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  testMatch: local ? "local.spec.ts" : "copilot.spec.ts",
  timeout: local ? 180_000 : 30_000,
  expect: { timeout: local ? 120_000 : 10_000 },
  outputDir: path.join(evidenceDir, "playwright"),
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(evidenceDir, "playwright-results.json") }],
  ],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.PAIS_BROWSER_EXECUTABLE
      ? {
          executablePath: process.env.PAIS_BROWSER_EXECUTABLE,
          args: ["--no-sandbox", "--disable-dev-shm-usage"],
        }
      : undefined,
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 960 },
      },
    },
    ...(!local
      ? [
          {
            name: "mobile",
            use: {
              ...devices["Desktop Chrome"],
              viewport: { width: 390, height: 844 },
              isMobile: true,
              hasTouch: true,
            },
          },
        ]
      : []),
  ],
  webServer: [
    {
      command: `${quotedApiPython} -m uvicorn services.api.app:app --host 127.0.0.1 --port 8000`,
      cwd: root,
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PAIS_PROFILE: local ? "local" : "fixture",
        PAIS_ALLOW_FIXTURE_AUTH: "1",
        PAIS_ENABLE_TEST_FAULTS: local ? "0" : "1",
        PAIS_REQUEST_TIMEOUT_SECONDS: local ? "120" : "60",
        PAIS_FIXTURE_STREAM_DELAY_MS: local ? "0" : "180",
        PAIS_DB_PATH:
          process.env.PAIS_E2E_DB_PATH || path.join(evidenceDir, "e2e.db"),
      },
    },
    {
      command: "npm run start",
      url: "http://127.0.0.1:3000",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PAIS_API_URL: "http://127.0.0.1:8000",
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
