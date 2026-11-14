// The chat widget's half of the new board (see sbhub_mcp.py): the board's own build is inlined into one html file and
// this script runs before it. The widget has no network of its own, so every /api/ read the board makes goes to the
// host as a tools/call of sb_api, and the one write it may make (answering a question) as sb_answer.
// MCP Apps view (SEP-1865, protocol 2026-01-26), hand-rolled so it needs no bundler or CDN.
window.__SB_WIDGET__ = true;
(() => {
  let nextId = 1;
  let canCall = false;
  const pending = new Map();
  const send = (msg) => { window.parent.postMessage({ jsonrpc: "2.0", ...msg }, "*"); };
  const request = (method, params, ms = 15000) => {
    const id = nextId++;
    send({ id, method, params });
    return new Promise((res, rej) => {
      pending.set(id, { res, rej });
      setTimeout(() => { if (pending.delete(id)) rej(new Error("timeout")); }, ms);
    });
  };
  const applyHost = (ctx) => {
    if (!ctx) return;
    const r = document.documentElement;
    if (ctx.theme) {
      r.style.colorScheme = ctx.theme;
      r.classList.toggle("dark", ctx.theme === "dark");
    }
  };
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent) return;
    const m = e.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id != null && !m.method) {
      const p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      if (m.error) p.rej(m.error); else p.res(m.result);
    } else if (m.method === "ui/notifications/host-context-changed") applyHost(m.params);
    else if (m.method === "ui/resource-teardown" || m.method === "ping") { if (m.id != null) send({ id: m.id, result: {} }); }
  });

  const ready = request("ui/initialize", { appInfo: { name: "sb-board", version: "2.0.0" }, appCapabilities: { availableDisplayModes: ["inline"] }, protocolVersion: "2026-01-26" })
    .then((r) => {
      applyHost(r?.hostContext);
      canCall = !!r?.hostCapabilities?.serverTools;
      send({ method: "ui/notifications/initialized", params: {} });
    })
    .catch(() => { canCall = false; });

  let last = 0;
  const size = () => {
    const h = Math.ceil(document.documentElement.getBoundingClientRect().height);
    if (h !== last) { last = h; send({ method: "ui/notifications/size-changed", params: { height: h } }); }
  };
  addEventListener("DOMContentLoaded", () => { new ResizeObserver(size).observe(document.body); });

  const reply = (status, body) => new Response(body, { status, headers: { "Content-Type": "application/json" } });
  const call = async (name, args) => {
    await ready;
    if (!canCall) return null;
    return request("tools/call", { name, arguments: args });
  };
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const u = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://widget.invalid/");  // a widget's own address (about:srcdoc, a blob) is no base
    const at = u.pathname.indexOf("/api/");
    if (at < 0) return realFetch(input, init);
    const path = u.pathname.slice(at) + u.search;
    try {
      if ((init?.method ?? "GET").toUpperCase() === "POST") {
        const body = JSON.parse(String(init?.body ?? "{}"));
        if (path !== "/api/answer") return reply(403, '{"ok":false,"error":"this page is read-only"}');
        const r = await call("sb_answer", { qid: body.qid, answer: body.answer });
        if (!r || r.isError) return reply(502, JSON.stringify({ ok: false, error: r?.content?.[0]?.text ?? "the host cannot call tools" }));
        return reply(200, '{"ok":true}');
      }
      const r = await call("sb_api", { path });
      const s = r?.structuredContent;
      if (!s || typeof s.status !== "number") return reply(503, '{"ok":false,"error":"the hub is not reachable"}');
      return reply(s.status, s.body);
    } catch {
      return reply(503, '{"ok":false,"error":"the hub is not reachable"}');
    }
  };
})();
