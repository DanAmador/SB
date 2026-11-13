import { defineConfig, devices } from "@playwright/test";

/** The board against a fixture hub: the Vite dev server's /api goes to e2e/fixture-server.ts. */
const FIXTURE = 8799;
const WEB = 5199;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${String(WEB)}`, trace: "retain-on-failure", ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
  webServer: [
    { command: "node e2e/fixture-server.ts", port: FIXTURE, env: { FIXTURE_PORT: String(FIXTURE) }, reuseExistingServer: false },
    {
      command: `vite --port ${String(WEB)} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${String(WEB)}/next/`,
      env: { SB_HUB_URL: `http://127.0.0.1:${String(FIXTURE)}` },
      reuseExistingServer: false,
    },
  ],
});
