import { describe, expect, it } from "vitest";
import { State, type AgentRow, type Question, type QueueItem, type TicketRow } from "@sb-hub/contract";
import {
  SILENT,
  WEEK,
  addable,
  canTickAgain,
  dayStart,
  endedToday,
  endsAt,
  mapNote,
  queueView,
  runFiles,
  runRows,
  filterOptions,
  plainReason,
  searchTickets,
  seenKey,
  showCounts,
  tkey,
  type Find,
  splitAgents,
  ticketIndex,
  vaultUri,
  waitsFor,
  withBlockers,
} from "./board.ts";
import { readLink, writeLink } from "./link.ts";

const NOW = 1_800_000_000;

const agent = (id: string, more: Partial<AgentRow> = {}): AgentRow => ({ agent: id, at: NOW - 10, state: "working", ...more });
const question = (more: Partial<Question> = {}): Question => ({
  agent: "s1",
  q: "Which?",
  options: ["A", "B"],
  default: "A",
  asked: NOW - 60,
  deadline: NOW + 60,
  answer: null,
  by: null,
  ...more,
});
const item = (key: string, state: QueueItem["state"], more: Partial<QueueItem> = {}): QueueItem =>
  ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, ...more }) as QueueItem;
const ticket = (map: string, num: number, more: Partial<TicketRow> = {}): TicketRow => ({
  map,
  num,
  title: `${map} ${String(num)}`,
  why: "",
  type: "task",
  status: "open",
  priority: null,
  blocked_by: [],
  blocked_by_open: [],
  paths: [],
  tier: "sonnet",
  has_done_when: true,
  done_when: "",
  question: "",
  out: "",
  checks: ["true"],
  repo: "/r",
  file: "/f.md",
  map_title: map.toUpperCase(),
  map_order: 1,
  claimed_by: null,
  queued: false,
  state: "ready",
  reason: "ready",
  ...more,
});

function state(more: Partial<State> = {}, queue: Partial<State["queue"]> = {}): State {
  // the board's input is always a State the contract accepts
  return State.parse({
    agents: {},
    locks: {},
    questions: {},
    aliases: {},
    messages: {},
    installed: {},
    now: NOW,
    providers: {},
    ...more,
    queue: { version: 1, seeded: true, paused: false, agent: null, items: [], ...queue },
  });
}

describe("your sessions", () => {
  it("are apart from queue workers, with each session's helpers under it", () => {
    const s = state({
      agents: {
        s1: agent("s1", { role: "orchestrator", state: "your turn" }),
        s2: agent("s2", { state: "needs you", at: NOW - 100 }),
        q1: agent("q1", { role: "worker", parent: "queue" }),
        h1: agent("h1", { role: "worker", parent: "s1" }),
        lost: agent("lost", { role: "worker", parent: "gone" }),
      },
    });
    const a = splitAgents(s);
    expect(a.sessions.map((x) => x.agent)).toEqual(["s2", "s1", "lost"]);
    expect(a.workers.map((x) => x.agent)).toEqual(["q1"]);
    expect(a.kids.get("s1")?.map((x) => x.agent)).toEqual(["h1"]);
  });
});

describe("waits for you", () => {
  const tickets = [ticket("sb/one", 1), ticket("sb/one", 4, { state: "waits for you", type: "grilling" }), ticket("sb/one", 5, { state: "waits for you" })];
  const s = state(
    {
      agents: { s1: agent("s1", { state: "blocked" }), s2: agent("s2", { state: "idle" }) },
      questions: {
        late: question({ deadline: NOW + 300 }),
        soon: question({ deadline: NOW + 30 }),
        fresh: question({ answer: "A", by: "you", answered: NOW - 5 }),
        old: question({ answer: "B", by: "default", answered: NOW - 60 }),
      },
      installed: { main: { kind: "claude", dir: null, model: null, limited_until: null, login: "expired" } },
      providers: { "/r": [{ title: "Tests", widgets: [{ kind: "status", label: "unit", value: "3 failed", level: "bad" }] }] },
    },
    {
      items: [
        item("sb/one#1", "failed", { ended: NOW - 50, note: "checks failed" }),
        item("sb/one#2", "done", { ended: NOW - 40 }),
        item("sb/one#3", "done", { ended: NOW - 30 }),
        item("sb/one#5", "queued"),
      ],
    },
  );
  const ix = ticketIndex(tickets, s);

  it("orders questions by deadline and keeps a fresh answer 20 s; failed, done and design tickets follow", () => {
    const w = waitsFor(s, tickets, ix, new Set());
    expect(w.questions.map(([id]) => id)).toEqual(["soon", "late", "fresh"]);
    expect(w.failed.map((i) => i.key)).toEqual(["sb/one#1"]);
    expect(w.done.map((i) => i.key)).toEqual(["sb/one#3", "sb/one#2"]);
    // a queued design ticket is not waiting on you
    expect(w.tickets.map((t) => t.num)).toEqual([4]);
    expect(w.signedOut).toEqual(["main"]);
    expect(w.badWidgets).toEqual([{ project: "/r", panel: "Tests", label: "unit", value: "3 failed" }]);
  });

  it("counts open questions, runs to assess and trouble; not answered questions, not design tickets, not your sessions", () => {
    expect(waitsFor(s, tickets, ix, new Set()).count).toBe(2 + 1 + 2 + 1 + 1);
  });

  it("drops a run once it is looked at, and only that run", () => {
    const done = s.queue.items[1];
    if (!done) throw new Error("fixture");
    const w = waitsFor(s, tickets, ix, new Set([seenKey(done)]));
    expect(w.done.map((i) => i.key)).toEqual(["sb/one#3"]);
    // the same ticket ending again is a new run to look at
    expect(seenKey({ key: "sb/one#2", ended: NOW })).not.toBe(seenKey(done));
  });
});

describe("runs", () => {
  const s = state(
    {
      agents: {
        "m/a#1": agent("m/a#1", { role: "worker", parent: "queue", note: "running the tests", at: NOW - 20 }),
        "m/a#2": agent("m/a#2", { role: "worker", parent: "queue", note: "reading", at: NOW - SILENT - 1 }),
        "m/a#3": agent("m/a#3", { role: "worker", parent: "queue", state: "blocked", note: "needs the editor", at: NOW - 5 }),
        mine: agent("mine", { title: "My chat" }),
      },
    },
    {
      agent: "pool",
      items: [
        item("m/a#1", "running", { started: NOW - 600, runner: "work" }),
        item("m/a#2", "running", { started: NOW - 900 }),
        item("m/a#3", "running", { started: NOW - 60 }),
        item("m/a#4", "running", { started: NOW - 30 }),
        item("m/a#5", "queued"),
        item("m/a#6", "done", { started: NOW - 4000, ended: NOW - 10 }),
      ],
      cleared: [item("m/a#7", "failed", { ended: NOW - 20 }), item("m/a#8", "done", { ended: dayStart(NOW) - 60 })],
    },
  );
  const rows = runRows(s, ticketIndex([ticket("m/a", 1, { title: "Ship it", map_title: "Map A" })], s));

  it("are one row per running worker, never a chat session: blocked first, then silent, then longest running", () => {
    expect(rows.map((r) => r.item.key)).toEqual(["m/a#3", "m/a#2", "m/a#1", "m/a#4"]);
    expect(rows.map((r) => r.tone)).toEqual(["blocked", "quiet", "ok", "ok"]);
  });

  it("carry the title, map, account, minutes and the last action with its time", () => {
    const one = rows.find((r) => r.item.key === "m/a#1");
    expect(one).toMatchObject({ title: "Ship it", mapName: "a", project: "m", account: "work", runFor: 600, last: "running the tests", lastAt: NOW - 20 });
    // no report yet: the pool's account, and its start as its last word
    expect(rows.find((r) => r.item.key === "m/a#4")).toMatchObject({ account: "pool", last: "starting", lastAt: NOW - 30, tone: "ok" });
  });

  it("fold today's ended runs, cleared ones too, newest first, nothing from yesterday", () => {
    const d = dayStart(NOW) + 3600;
    const t = state(
      { now: d },
      {
        items: [item("x#1", "done", { ended: d - 10 }), item("x#2", "running")],
        cleared: [item("x#3", "failed", { ended: d - 20 }), item("x#4", "done", { ended: d - 7200 }), item("x#1", "done", { ended: d - 10 })],
      },
    );
    expect(endedToday(t).map((i) => i.key)).toEqual(["x#1", "x#3"]);
  });
});

describe("failure reasons", () => {
  it("are said in plain words", () => {
    const r = (note: string, st: QueueItem["state"] = "failed"): string => plainReason({ note, state: st });
    expect(r("no commit after b4fe872cf")).toBe("ended without a commit");
    expect(r("check failed: /Users/x/.sb-hub/checks/sk4te-compile.py\nUnity Editor not reachable")).toBe("the sk4te compile check failed");
    expect(r("check failed: pnpm typecheck\nsrc/a.ts(1,1): error")).toBe("pnpm typecheck failed");
    expect(r("commits since the start touch files outside the ticket's paths: a.ts, b.ts")).toBe("it changed 2 files outside its list");
    expect(r("could not land: its commits conflict with 85bfcc87b on the checkout's branch in skills/sb/scripts/sbhub_service.sh\nIts work stays")).toBe(
      "its commits conflict with the branch in sbhub_service.sh",
    );
    expect(r("blocked: after The new board", "skipped")).toBe("waited on “The new board”");
    expect(r("", "failed")).toBe("no reason recorded");
  });
});

describe("the vault", () => {
  it("links a file the way sbmap uri does, and finds a ticket's map and a run's report and log", () => {
    expect(vaultUri("/V/Second Brain/a (b)/030 It's done.md")).toBe("obsidian://open?path=%2FV%2FSecond%20Brain%2Fa%20%28b%29%2F030%20It%27s%20done.md");
    expect(vaultUri("relative.md")).toBeNull();
    expect(mapNote("/V/wayfinder/sb/hub/issues/030 X.md")).toBe("/V/wayfinder/sb/hub/map.md");
    expect(mapNote("/V/wayfinder/sb/hub/issues/done/030 X.md")).toBe("/V/wayfinder/sb/hub/map.md");
    expect(runFiles(item("sb/hub#30", "done", { run: "/V/runs/r", log: "/V/runs/r/30.log" }))).toEqual({ report: "/V/runs/r/30.md", log: "/V/runs/r/30.log" });
    expect(runFiles(item("sb/hub#30", "queued"))).toEqual({ report: null, log: null });
  });
});

describe("the queue", () => {
  const s = state(
    {},
    {
      items: [
        item("m#1", "running", { started: NOW - 100 }),
        item("m#2", "queued"),
        item("job-1", "queued", { kind: "job", model: null, project: "p", repo: "/r", prompt: "x", hash: "h", name: "j", title: "j", created: NOW }),
        item("m#3", "queued"),
        item("m#4", "done", { ended: NOW - 10 }),
        item("m#5", "done", { ended: NOW - WEEK - 1 }),
        item("m#6", "failed", { ended: NOW - WEEK - 1 }),
        item("m#7", "skipped", { ended: NOW - 5 }),
      ],
      cleared: [item("m#8", "done", { ended: NOW - 50 }), item("m#9", "failed", { ended: NOW - 50 })],
    },
  );
  const qv = queueView(s);

  it("splits running from what is next, in order, with the queued tickets' keys for queue/set", () => {
    expect(qv.running.map((i) => i.key)).toEqual(["m#1"]);
    expect(qv.next.map((i) => i.key)).toEqual(["m#2", "job-1", "m#3"]);
    expect(qv.queuedKeys).toEqual(["m#2", "m#3"]);
    expect([...qv.live].sort()).toEqual(["job-1", "m#1", "m#2", "m#3"]);
  });

  it("keeps Done to the last 7 days and every failure, newest first, and the cleared ones apart", () => {
    expect(qv.done.map((i) => i.key)).toEqual(["m#4"]);
    expect(qv.failed.map((i) => i.key)).toEqual(["m#7", "m#6"]);
    expect(qv.doneCleared.map((i) => i.key)).toEqual(["m#8"]);
    expect(qv.failedCleared.map((i) => i.key)).toEqual(["m#9"]);
  });

  it("reckons the end at 1.5 h a ticket", () => {
    expect(endsAt(s, null)).toBeGreaterThan(NOW);
    expect(endsAt(state(), null)).toBe(0);
  });
});

describe("open tickets", () => {
  const tickets = [
    ticket("sb/one", 1),
    ticket("sb/one", 2, { state: "blocked", blocked_by_open: [1] }),
    ticket("sb/one", 3, { state: "blocked", blocked_by_open: [9] }),
    ticket("sb/one", 4, { state: "waits for you", type: "grilling" }),
    ticket("sb/one", 5),
    ticket("sk4te/two", 1, { title: "Ropes you reel" }),
    ticket("sk4te/two", 2, { state: "claimed", reason: "claimed by someone" }),
    ticket("sb/one", 6),
  ];
  const s = state({}, { items: [item("sb/one#6", "queued"), item("sb/one#5", "running")] });
  const ix = ticketIndex(tickets, s);

  it("can be queued when ready, or blocked only by tickets that can be queued", () => {
    const [, two, three] = tickets;
    if (!two || !three) throw new Error("fixture");
    expect(addable(two, ix)).toBe(true);
    expect(addable(three, ix)).toBe(false);
    expect(withBlockers("sb/one#2", ix)).toEqual(["sb/one#1", "sb/one#2"]);
  });

  const find = (more: Partial<Find>): Find => ({ q: "", p: "", m: "", s: "ready", ...more });

  it("fall in three lists: can run, needs a decision, not yet; queued and running ones in none", () => {
    expect(searchTickets(tickets, ix, find({})).map(tkey)).toEqual(["sb/one#1", "sb/one#2", "sk4te/two#1"]);
    expect(searchTickets(tickets, ix, find({ s: "waits" })).map(tkey)).toEqual(["sb/one#4"]);
    expect(searchTickets(tickets, ix, find({ s: "later" })).map(tkey)).toEqual(["sb/one#3", "sk4te/two#2"]);
    expect(showCounts(tickets, ix, find({}))).toEqual({ ready: 3, waits: 1, later: 2 });
  });

  it("are found by every word over project, map and title, and by the project and map chosen", () => {
    expect(searchTickets(tickets, ix, find({ q: "ROPES" })).map((t) => t.title)).toEqual(["Ropes you reel"]);
    expect(searchTickets(tickets, ix, find({ q: "sb 2" })).map(tkey)).toEqual(["sb/one#2"]);
    expect(searchTickets(tickets, ix, find({ p: "sk4te" })).map(tkey)).toEqual(["sk4te/two#1"]);
    expect(searchTickets(tickets, ix, find({ m: "sb/one", s: "later" })).map(tkey)).toEqual(["sb/one#3"]);
    expect(filterOptions(tickets, { p: "sb", m: "" })).toEqual({ projects: ["sb", "sk4te"], maps: [["sb/one", "SB/ONE"]] });
  });

  it("tick again only for a failed ticket that is still open and not live", () => {
    expect(canTickAgain(item("sb/one#1", "failed"), ix)).toBe(true);
    expect(canTickAgain(item("sb/one#6", "failed"), ix)).toBe(false);
    expect(canTickAgain(item("gone#1", "failed"), ix)).toBe(false);
  });
});

describe("the page link", () => {
  it("keeps the view, the search and the open ticket, and leaves the defaults out", () => {
    const link = readLink("?view=queue&q=rope&p=sb&m=sb%2Fone&s=later&t=sb%2Fone%231");
    expect(link).toEqual({ view: "queue", q: "rope", p: "sb", m: "sb/one", s: "later", t: "sb/one#1" });
    expect(readLink(writeLink(link))).toEqual(link);
    expect(readLink("").view).toBe("runs");
    expect(writeLink(readLink("?view=bogus"))).toBe("");
  });
});
