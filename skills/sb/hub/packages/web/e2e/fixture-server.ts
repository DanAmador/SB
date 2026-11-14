/**
 * A small hub for the Playwright test: the routes the board reads, a queue it can write, every answer checked
 * against the contract before it leaves. Run with `node e2e/fixture-server.ts` (Node strips the types).
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { QueueMoveBody, QueueSetBody, RunDetail, RunSeenBody, RunsPage, SendBody, State, Tickets, Trail, addLinks, type LinkContext, type Message, type QueueItem, type TicketRow } from "@sb-hub/contract";

/** Every file the fixtures name exists; the server's own vault lookup is covered by the server's tests. */
const ctx: LinkContext = { exists: () => true, real: (p) => p, findTicket: (map, num) => `/vault/${map}/issues/${String(num)}.md`, runs: {} };

const PORT = Number(process.env.FIXTURE_PORT ?? "8799");
const now = (): number => Date.now() / 1000;

type Raw<T> = Omit<T, "links">;
const ticket = (num: number, title: string, more: Partial<Raw<TicketRow>> = {}): Raw<TicketRow> => ({
  map: "demo/board", num, title, why: "So the board can be tested.", type: "task", status: "open", priority: null,
  blocked_by: [], blocked_by_open: [], paths: ["src/"], tier: "sonnet", has_done_when: true, done_when: "It shows.",
  question: "", out: "", checks: ["pnpm test"], repo: "/demo", file: `/vault/demo/board/issues/${String(num)}.md`,
  map_title: "The demo board", map_order: 1, claimed_by: null, queued: false, state: "ready", reason: "ready", ...more,
});
const tickets = (): TicketRow[] => Tickets.parse(addLinks("GET /api/tickets", [
  ticket(1, "Draw the header"),
  ticket(2, "Drag a ticket into the queue"),
  ticket(3, "Show the queue in order"),
  ticket(4, "Decide the colour scheme", { state: "waits for you", type: "grilling" }),
  ticket(5, "Run the board against the real hub", { status: "claimed", state: "claimed", reason: "claimed by hub main" }),
  ticket(6, "Fix the sheet's focus", { status: "claimed", state: "claimed", reason: "claimed by hub main" }),
  ticket(8, "Read the accounts' usage", { status: "claimed", state: "claimed", reason: "claimed by hub main" }),
  ticket(1, "Draw the shop window", { map: "other/site", map_title: "The shop site", file: "/vault/other/site/issues/1.md" }),
  ticket(2, "Pick the shop's fonts", { map: "other/site", map_title: "The shop site", state: "waits for you", type: "grilling", file: "/vault/other/site/issues/2.md" }),
  ticket(3, "Write the shop's copy", { map: "other/site", map_title: "The shop site", status: "claimed", state: "claimed", reason: "claimed by hub main", file: "/vault/other/site/issues/3.md" }),
], ctx));

const item = (key: string, state: QueueItem["state"]): Raw<QueueItem> => ({
  key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: state === "running" ? now() - 300 : null, ended: null,
});
const RUN = "/vault/runs/2026-11-13-board";
const start = now();
const queue = {
  version: 1, seeded: true, paused: false, agent: "main", agents: ["main"],
  runs: { "demo/board": `${RUN}/2026-11-13-board.md` },
  items: [
    { ...item("demo/board#5", "running"), runner: "main", model: "opus", started: start - 720, run: RUN, log: `${RUN}/5.log` },
    { ...item("demo/board#8", "running"), runner: "main", started: start - 1500, run: RUN, log: `${RUN}/8.log` },
    { ...item("demo/board#6", "failed"), ended: start - 900, note: "no commit after 85bfcc87b", run: RUN, log: `${RUN}/6.log` },
    {
      ...item("demo/board#7", "done"), title: "Show who runs what", ended: start - 1200, commit: "0123456789abcdef", run: RUN, log: `${RUN}/7.log`,
      checks: [{ cmd: "pnpm test", code: 0, secs: 12, tail: "" }],
    },
    { ...item("other/site#3", "running"), runner: "main", started: start - 240, run: RUN, log: `${RUN}/s3.log` },
    { ...item("other/site#4", "failed"), ended: start - 800, note: "check failed: pnpm test", run: RUN, log: `${RUN}/s4.log` },
    item("demo/board#3", "queued"),
  ] as Raw<QueueItem>[],
};

const messages: Record<string, Message> = {};
const seen: string[] = [];

// ---- History: runs the queue and the vault's run folders know of, and the pictures of two of them ----
const run = (key: string, title: string, ago: number, more: Record<string, unknown> = {}): Record<string, unknown> => ({
  key, title, project: key.split("/")[0], map: key.replace(/#\d+$/, ""), outcome: "done", reason: "", account: "main", model: "sonnet",
  started: start - ago - 600, ended: start - ago, commit: "0123456789abcdef", tries: 1, pictures: [],
  links: { ticket: `obsidian://open?path=%2Fvault%2F${key.replace(/[#/]/g, "-")}.md`, map: null, board: null, report: `obsidian://open?path=%2Fvault%2Frun-${key.replace(/[#/]/g, "-")}.md`, log: null }, ...more,
});
const PICS = ["board-1440.png", "board-phone.png", "sheet-open.png"];
const runs: Record<string, unknown>[] = [
  run("demo/board#7", "Show who runs what", 1200, { pictures: PICS }),
  run("demo/board#6", "Fix the sheet's focus", 900, { outcome: "failed", reason: "ended without a commit", commit: null, model: "opus", tries: 2 }),
  run("other/site#4", "Pick the shop's fonts", 800, { outcome: "failed", reason: "pnpm test failed", account: "spare", commit: null }),
  run("demo/board#2", "Drag a ticket into the queue", 86400 + 3600, { pictures: ["drag.png"], commit: "abcdef0123456789" }),
  run("demo/board#1", "Draw the header", 86400 * 3, { outcome: "skipped", reason: "someone else had claimed it", commit: null, account: null, model: null }),
  run("demo/board#0", "Wire up the very first sketch", 86400 * 20, { outcome: "unknown", commit: "9999999aaaaaaa", account: null, model: null }),
];
const colours = ["#3b82f6", "#16a34a", "#f59e0b"];
const svg = (name: string): string => {
  const c = colours[Math.max(0, PICS.indexOf(name)) % colours.length] ?? "#3b82f6";
  return `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="600" viewBox="0 0 960 600"><rect width="960" height="600" fill="${c}"/><rect x="60" y="60" width="840" height="80" rx="12" fill="#fff" opacity=".85"/><rect x="60" y="180" width="380" height="360" rx="12" fill="#fff" opacity=".6"/><rect x="480" y="180" width="420" height="160" rx="12" fill="#fff" opacity=".6"/><text x="80" y="115" font-size="40" font-family="sans-serif" fill="#111">${name}</text></svg>`;
};
const detailOf = (key: string): unknown => {
  const r = runs.find((x) => x.key === key);
  if (r === undefined) return undefined;
  return RunDetail.parse({
    run: r,
    checks: r.outcome === "failed" ? [{ cmd: "pnpm test", code: 1, secs: 41.2, tail: "1 failed, 12 passed\nFAIL src/board.test.ts" }] : [{ cmd: "pnpm typecheck", code: 0, secs: 12.4, tail: "" }, { cmd: "pnpm test", code: 0, secs: 31, tail: "13 passed" }],
    report: `# Show who runs what\n\nCommit: 0123456 (branch sb/demo)\n\n## What changed\n- The **Runs** view names the account.\n- A \`pnpm test\` run now covers it.\n\n## Self-checks\n- \`pnpm test\`: exit 0\n`,
    log: "Reading the board.\n→ Read src/Board.tsx\nThe header needs the account name.\n→ Edit src/Header.tsx\nresult: done",
  });
};

function state(): State {
  return State.parse({
    agents: {
      "s-1": { agent: "s-1", title: "Charting the board", project: "/demo", state: "your turn", asked: "chart it", at: now() - 30 },
      "demo/board#5": { agent: "demo/board#5", role: "worker", parent: "queue", project: "/demo", state: "working", note: "running the tests", at: now() - 20 },
      "other/site#3": { agent: "other/site#3", role: "worker", parent: "queue", project: "/other", state: "working", note: "writing the copy", at: now() - 15 },
      "demo/board#8": { agent: "demo/board#8", role: "worker", parent: "queue", project: "/demo", state: "working", note: "reading the usage file", at: start - 400 },
    },
    locks: {}, aliases: {}, messages, providers: {},
    questions: { q1: { agent: "s-1", q: "Ship the new board tonight?", options: ["Yes", "Not yet"], default: "Yes", asked: now() - 10, deadline: now() + 600, answer: null, by: null } },
    installed: { main: { kind: "claude", dir: null, model: null, limited_until: null } },
    seen: [...seen],
    now: now(),
    queue: (addLinks("GET /api/state", { queue }, ctx) as { queue: unknown }).queue,
  });
}

const send = (res: ServerResponse, status: number, body: unknown): void => {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
};
async function body(req: IncomingMessage): Promise<unknown> {
  let raw = "";
  for await (const chunk of req) raw += String(chunk);
  return raw ? JSON.parse(raw) : {};
}

// ---- Sessions: a trail per live agent, newest action last ----
const act = (tool: string, label: string, ago: number, ok: boolean | null = true, sub = false): Record<string, unknown> => ({
  tool, label, start: now() - ago, end: ok === null ? null : now() - ago + 1, ok, sub,
});
const TRAILS: Record<string, Record<string, unknown>[]> = {
  "s-1": [act("prompt", "chart it", 40), act("Read", "docs/plan.md", 30), act("Bash", "git status", 20), act("WebSearch", "lot-map", 10), act("Edit", "src/App.tsx", 4, null)],
  "demo/board#5": [act("Read", "src/Board.tsx", 60), act("Edit", "src/Header.tsx", 45), act("Bash", "pnpm test", 30, false), act("Agent", "check the tests", 20, true, true), act("Bash", "pnpm test", 3, null)],
  "other/site#3": [act("Read", "copy/home.md", 50), act("Write", "copy/shop.md", 20), act("Skill", "wikibrain", 6)],
  "demo/board#8": [act("Read", "usage.json", 500), act("Grep", "usage", 450)],
};

createServer((req, res) => {
  void (async () => {
    const path = (req.url ?? "").split("?")[0];
    if (req.method === "GET" && path === "/api/state") { send(res, 200, state()); return; }
    if (req.method === "GET" && path === "/api/trail") {
      const agent = new URL(req.url ?? "", "http://x").searchParams.get("agent") ?? "";
      const actions = TRAILS[agent];
      if (actions === undefined) send(res, 404, { ok: false, error: "no trail for that agent" });
      else send(res, 200, Trail.parse({ agent, ctx: agent === "demo/board#5" ? 72 : null, ended: null, actions }));
      return;
    }
    if (req.method === "GET" && path === "/api/runs") {
      const u = new URL(req.url ?? "", "http://x").searchParams;
      const since = Number(u.get("since") ?? "0");
      const list = runs.filter((r) => Number(r.ended) >= since);
      send(res, 200, RunsPage.parse({ runs: list.slice(0, Number(u.get("limit") ?? "100")), total: list.length, offset: 0, limit: Number(u.get("limit") ?? "100") }));
      return;
    }
    if (req.method === "GET" && path === "/api/run") {
      const d = detailOf(new URL(req.url ?? "", "http://x").searchParams.get("key") ?? "");
      if (d === undefined) send(res, 404, { ok: false, error: "no such run" });
      else send(res, 200, d);
      return;
    }
    if (req.method === "GET" && path === "/api/media") {
      res.writeHead(200, { "Content-Type": "image/svg+xml" });
      res.end(svg(new URL(req.url ?? "", "http://x").searchParams.get("name") ?? ""));
      return;
    }
    if (req.method === "GET" && path === "/api/tickets") { send(res, 200, tickets().map((t) => ({ ...t, queued: queue.items.some((i) => i.key === `${t.map}#${String(t.num)}`) }))); return; }
    if (req.method === "GET" && path === "/api/ticket") {
      const key = new URL(req.url ?? "", "http://x").searchParams.get("key") ?? "";
      { send(res, 200, { key, title: key, file: "/vault/x.md", open: true, comments: [], map_checks: ["pnpm test"], trail: [], uri: "obsidian://open?path=x", map_uri: "obsidian://open?path=m" }); return; }
    }
    if (req.method === "POST" && path === "/api/queue/set") {
      const b = QueueSetBody.parse(await body(req));
      if (b.version !== null && b.version !== queue.version) { send(res, 409, addLinks("POST /api/queue/set", { ok: false, stale: true, queue }, ctx)); return; }
      const others = queue.items.filter((i) => i.state !== "queued");
      queue.items = [...others, ...b.keys.map((k) => queue.items.find((i) => i.key === k && i.state === "queued") ?? item(k, "queued"))];
      queue.version += 1;
      { send(res, 200, addLinks("POST /api/queue/set", { ok: true, queue }, ctx)); return; }
    }
    if (req.method === "POST" && path === "/api/queue/move") {
      const b = QueueMoveBody.parse(await body(req));
      const queued = queue.items.filter((i) => i.state === "queued");
      const from = queued.findIndex((i) => i.key === b.key);
      const [moved] = queued.splice(from, 1);
      if (moved) queued.splice(b.to, 0, moved);
      queue.items = [...queue.items.filter((i) => i.state !== "queued"), ...queued];
      queue.version += 1;
      { send(res, 200, addLinks("POST /api/queue/set", { ok: true, queue }, ctx)); return; }
    }
    if (req.method === "POST" && path === "/api/__reset-seen") {
      seen.length = 0;
      send(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && path === "/api/run/seen") {
      seen.push(RunSeenBody.parse(await body(req)).key);
      send(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && path === "/api/send") {
      const b = SendBody.parse(await body(req));
      const id = `m${String(Object.keys(messages).length + 1)}`;
      messages[id] = { to: b.to, text: b.text, at: now(), delivered: null, how: null };
      { send(res, 200, { ok: true, id }); return; }
    }
    if (req.method === "POST") { send(res, 200, { ok: true }); return; }
    send(res, 404, { ok: false, error: "not found" });
  })();
}).listen(PORT, "127.0.0.1", () => {
  console.log(`fixture hub on http://127.0.0.1:${String(PORT)}`);
});
