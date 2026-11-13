import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/** The hub the dev server's /api goes to: the Python hub by default, a fixture server in the Playwright test. */
const hub = process.env.SB_HUB_URL ?? `http://127.0.0.1:${process.env.SB_HUB_PORT ?? "8765"}`;

export default defineConfig({
  base: "/next/",
  plugins: [
    react(),
    // the compiler on every component and hook of this package's source, and the build fails on anything it cannot
    // compile. "infer", not "all": "all" memoizes plain helpers too, and those crash when an event handler calls them
    // (useMemoCache outside render). The contract package is plain TypeScript.
    babel({
      include: [/\/packages\/web\/src\//],
      presets: [reactCompilerPreset({ compilationMode: "infer", panicThreshold: "all_errors" })],
    }),
    tailwindcss(),
  ],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  build: { chunkSizeWarningLimit: 800 },
  server: { proxy: { "/api": { target: hub, changeOrigin: true } } },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
