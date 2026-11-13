import { execFileSync } from "node:child_process";
import { defineConfig, devices } from "@playwright/test";

/** A port nothing listens on now, so two checks running at once do not collide. */
function freePort(): string {
  const script = "const s=require('net').createServer().listen(0,'127.0.0.1',()=>{process.stdout.write(String(s.address().port));s.close()})";
  return execFileSync(process.execPath, ["-e", script], { encoding: "utf8" }).trim();
}

// Chosen once in the main process; workers inherit the env and so read the same ports.
process.env.SB_E2E_FIXTURE_PORT ??= freePort();
process.env.SB_E2E_WEB_PORT ??= freePort();

/** The board against a fixture hub: the Vite dev server's /api goes to e2e/fixture-server.ts. */
const FIXTURE = Number(process.env.SB_E2E_FIXTURE_PORT);
const WEB = Number(process.env.SB_E2E_WEB_PORT);

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
