/**
 * The hub: `pnpm --dir skills/sb/hub start` (or `node packages/server/src/index.ts [--port N]`).
 * Listens on 127.0.0.1 (8765, SB_HUB_PORT or --port), starts the Python hub as its child and answers
 * for it through the contract. Stops the child on SIGTERM or Ctrl-C, and stops when the child does.
 */
import { mkdirSync } from "node:fs";
import { serve } from "@hono/node-server";
import { createApp } from "./app.ts";
import { hubHome, hubPort } from "./config.ts";
import { startPython, type PythonHub } from "./python.ts";
import { upstream } from "./upstream.ts";

const port = hubPort(process.argv.slice(2), process.env);
const home = hubHome(process.env);
const webDir = new URL("../../web/dist", import.meta.url).pathname;
let python: PythonHub | undefined;

const app = createApp({ port, webDir, upstream: upstream(() => python?.port), log: (line) => { console.error(line); } });

// The public port first: when it is taken this exits before touching any Python hub.
const server = serve({ fetch: app.fetch, hostname: "127.0.0.1", port });
server.once("error", (e: Error) => {
  console.error(`sb hub: cannot listen on 127.0.0.1:${String(port)}: ${e.message}`);
  process.exit(1);
});
server.once("listening", () => {
  mkdirSync(home, { recursive: true });
  startPython(home).then(
    (p) => {
      python = p;
      p.child.once("exit", (code, signal) => {
        console.error(`sb hub: the Python hub stopped (${signal ?? String(code)})`);
        process.exit(stopping ? 0 : 1);
      });
      console.log(`sb hub on http://127.0.0.1:${String(port)}`);
    },
    (e: unknown) => {
      console.error(`sb hub: ${e instanceof Error ? e.message : String(e)}`);
      process.exit(1);
    },
  );
});

let stopping = false;
function stop(): void {
  if (stopping) return;
  stopping = true;
  server.close();
  // SIGTERM ends the Python hub's workers, as stopping it directly does.
  if (python !== undefined) python.child.kill("SIGTERM");
  else process.exit(0);
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
