/**
 * A small hub for the Playwright test: the routes the board reads, a queue it can write, every answer checked
 * against the contract before it leaves. Run with `node e2e/fixture-server.ts` (Node strips the types).
 */
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { QueueMoveBody, QueueSetBody, SendBody, State, Tickets, type Message, type QueueItem, type TicketRow } from "@sb-hub/contract";

const PORT = Number(process.env.FIXTURE_PORT ?? "8799");
const now = (): number => Date.now() / 1000;

const ticket = (num: number, title: string, more: Partial<TicketRow> = {}): TicketRow => ({
  map: "demo/board", num, title, why: "So the board can be tested.", type: "task", status: "open", priority: null,
  blocked_by: [], blocked_by_open: [], paths: ["src/"], tier: "sonnet", has_done_when: true, done_when: "It shows.",
  question: "", out: "", checks: ["pnpm test"], repo: "/demo", file: `/vault/demo/board/issues/${String(num)}.md`,
  map_title: "The demo board", map_order: 1, claimed_by: null, queued: false, state: "ready", reason: "ready", ...more,
});
const tickets: TicketRow[] = Tickets.parse([
  ticket(1, "Draw the header"),
  ticket(2, "Drag a ticket into the queue"),
  ticket(3, "Show the queue in order"),
  ticket(4, "Decide the colour scheme", { state: "waits for you", type: "grilling" }),
  ticket(5, "Run the board against the real hub", { status: "claimed", state: "claimed", reason: "claimed by hub main" }),
  ticket(6, "Fix the sheet's focus", { status: "claimed", state: "claimed", reason: "claimed by hub main" }),
  ticket(8, "Read the accounts' usage", { status: "claimed", state: "claimed", reason: "claimed by hub main" }),
]);

const item = (key: string, state: QueueItem["state"]): QueueItem => ({
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
    item("demo/board#3", "queued"),
  ] as QueueItem[],
};

const messages: Record<string, Message> = {};

function state(): State {
  return State.parse({
    agents: {
      "s-1": { agent: "s-1", title: "Charting the board", project: "/demo", state: "your turn", asked: "chart it", at: now() - 30 },
      "demo/board#5": { agent: "demo/board#5", role: "worker", parent: "queue", project: "/demo", state: "working", note: "running the tests", at: now() - 20 },
      "demo/board#8": { agent: "demo/board#8", role: "worker", parent: "queue", project: "/demo", state: "working", note: "reading the usage file", at: start - 400 },
    },
    locks: {}, aliases: {}, messages, providers: {},
    questions: { q1: { agent: "s-1", q: "Ship the new board tonight?", options: ["Yes", "Not yet"], default: "Yes", asked: now() - 10, deadline: now() + 600, answer: null, by: null } },
    installed: { main: { kind: "claude", dir: null, model: null, limited_until: null } },
    now: now(),
    queue,
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

createServer((req, res) => {
  void (async () => {
    const path = (req.url ?? "").split("?")[0];
    if (req.method === "GET" && path === "/api/state") { send(res, 200, state()); return; }
    if (req.method === "GET" && path === "/api/tickets") { send(res, 200, tickets.map((t) => ({ ...t, queued: queue.items.some((i) => i.key === `${t.map}#${String(t.num)}`) }))); return; }
    if (req.method === "GET" && path === "/api/ticket") {
      const key = new URL(req.url ?? "", "http://x").searchParams.get("key") ?? "";
      { send(res, 200, { key, title: key, file: "/vault/x.md", open: true, comments: [], map_checks: ["pnpm test"], trail: [], uri: "obsidian://open?path=x", map_uri: "obsidian://open?path=m" }); return; }
    }
    if (req.method === "POST" && path === "/api/queue/set") {
      const b = QueueSetBody.parse(await body(req));
      if (b.version !== null && b.version !== queue.version) { send(res, 409, { ok: false, stale: true, queue }); return; }
      const others = queue.items.filter((i) => i.state !== "queued");
      queue.items = [...others, ...b.keys.map((k) => queue.items.find((i) => i.key === k && i.state === "queued") ?? item(k, "queued"))];
      queue.version += 1;
      { send(res, 200, { ok: true, queue }); return; }
    }
    if (req.method === "POST" && path === "/api/queue/move") {
      const b = QueueMoveBody.parse(await body(req));
      const queued = queue.items.filter((i) => i.state === "queued");
      const from = queued.findIndex((i) => i.key === b.key);
      const [moved] = queued.splice(from, 1);
      if (moved) queued.splice(b.to, 0, moved);
      queue.items = [...queue.items.filter((i) => i.state !== "queued"), ...queued];
      queue.version += 1;
      { send(res, 200, { ok: true, queue }); return; }
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
