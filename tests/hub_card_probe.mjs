// The chat card as the host sees it, for tests/test_hub_mcp.py: the widget bridge (sbhub_widget_bridge.js) runs in a fake
// window, its host answers ui/initialize and relays tools/call to the real sb_api over HTTP (the test's shim), and the
// board's own typed client (web/src/lib/api.ts) reads /api/state every STATE_MS through the bridge's fetch.
// Prints "ok <inits>" or "fail <status or message>" per read.
import { readFileSync } from "node:fs";
import vm from "node:vm";
const [, , apiTs, bridgeJs, shim, everyMs] = process.argv;

const hostFetch = globalThis.fetch; // the host's own network; the card's fetch becomes the bridge's
let inits = 0;
const listeners = [];
const win = {
  addEventListener: (t, f) => { if (t === "message") listeners.push(f); },
  fetch: () => Promise.reject(new Error("no network")),
};
const parent = {
  postMessage: (m) => {
    queueMicrotask(async () => {
      let result;
      if (m.method === "ui/initialize") result = { hostContext: {}, hostCapabilities: ++inits === 1 ? {} : { serverTools: {} } }; // a slow first start offers no tools
      else if (m.method === "tools/call") {
        result = await hostFetch(shim, { method: "POST", body: JSON.stringify(m.params) }).then((x) => x.json());
      } else return;
      for (const f of listeners) f({ source: parent, data: { jsonrpc: "2.0", id: m.id, result } });
    });
  },
};
win.parent = parent;
const ctx = { window: win, document: { documentElement: {}, body: {} }, addEventListener: () => undefined, ResizeObserver: class { observe() {} }, URL, Response, setTimeout, Promise, JSON, String };
vm.runInNewContext(readFileSync(bridgeJs, "utf8"), ctx);
globalThis.window = win;
globalThis.fetch = (...a) => win.fetch(...a);

const { get } = await import(apiTs);
const read = async () => {
  try { await get("GET /api/state"); console.log(`ok ${inits}`); } catch (e) { console.log(`fail ${e.message}`); }
};
for (;;) { await read(); await new Promise((r) => setTimeout(r, Number(everyMs))); }
