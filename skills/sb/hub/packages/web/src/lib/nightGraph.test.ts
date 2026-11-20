import { describe, expect, it } from "vitest";
import type { QueueItem } from "@sb-hub/contract";
import { EVERYTHING } from "./board.ts";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { State, TicketRow } from "@sb-hub/contract";
import { NODE_H, NODE_W } from "./map.ts";
import { atOnceOf, BAR_GAP, chunkGraph, CHUNK_W, clock, countsLine, DONE_ID, focusOf, frozenInfo, spanOf, GAP, HEAD, infoOf, LEFT, nightGraph, pathsMeet, pathsOf, ROW_H, type ChunkGraph, type ChunkInput, type NightInput, type TicketInfo } from "./nightGraph.ts";
import type { Queue } from "@sb-hub/contract";

const links = (report: string | null) => ({ ticket: null, map: null, board: null, report, log: null });
const it_ = (key: string, state: QueueItem["state"], more: Record<string, unknown> = {}): QueueItem =>
  ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, links: links(null), ...more });
const job = (): QueueItem =>
  ({ key: "job:close", kind: "job", agent: null, state: "queued", note: "", commit: null, tries: 0, started: null, ended: null, model: null, project: "/code/alpha", repo: "/code/alpha", prompt: "", hash: "h", name: "close-off", title: "Close off the night", created: 1, links: links(null) });

// two maps of two projects: alpha/one (first), beta/two; one link between the maps; a never-queued ticket
const info = (): NightInput["info"] => {
  const t = (title: string, after: string[] = []): TicketInfo => ({ title, after });
  return {
    maps: new Map([["alpha/one", "Map one"], ["beta/two", "Map two"]]),
    tickets: new Map([
      ["alpha/one#1", t("First")],
      ["alpha/one#2", t("Second", ["alpha/one#1"])],
      ["alpha/one#3", t("Third", ["alpha/one#1"])],
      ["alpha/one#9", t("Never queued")],
      ["beta/two#1", t("Elsewhere", ["alpha/one#2"])],
      ["beta/two#2", t("Short")],
    ]),
  };
};
const items = (): QueueItem[] => [
  it_("beta/two#1", "queued"),
  it_("alpha/one#1", "done", { links: links("obsidian://report-1") }),
  it_("alpha/one#2", "running"),
  it_("alpha/one#3", "queued"),
  it_("beta/two#2", "failed", { links: links("obsidian://report-2") }),
  job(),
];
// 21:00 local on a night, and an hour
const T = new Date(2026, 10, 14, 21, 0, 0).getTime() / 1000;
const H = 3600;
/** The graph's height of an hour: a row per half hour. */
const HR = 2 * ROW_H;
const run = (more: Partial<NightInput> = {}) => nightGraph({ items: items(), maps: ["alpha/one", "beta/two"], info: info(), scope: EVERYTHING, ...more });

describe("nightGraph", () => {
  const g = run();
  const box = (id: string, x = g) => x.boxes.find((b) => b.id === id);

  it("gives each box its state, outcome and place in the whole line; a ticket never queued is absent", () => {
    expect(box("alpha/one#1")).toMatchObject({ state: "done", outcome: "done", foot: "Done", report: "obsidian://report-1", place: null });
    expect(box("alpha/one#2")).toMatchObject({ state: "running", outcome: null, foot: "Running", report: null });
    // beta/two#1 is first in the queue's items, alpha/one#3 second: places count across projects
    expect(box("beta/two#1")).toMatchObject({ state: "queued", place: 1, foot: "Queued 1" });
    expect(box("alpha/one#3")).toMatchObject({ state: "queued", place: 2, foot: "Queued 2" });
    expect(box("beta/two#2")).toMatchObject({ outcome: "fell short", foot: "Fell short", report: "obsidian://report-2" });
    expect(box("job:close")).toMatchObject({ map: "", project: "alpha", title: "Close off the night", place: 3 });
    expect(box("alpha/one#9")).toBeUndefined();
    expect(g.boxes).toHaveLength(6);
  });

  it("makes a chip per map in the hub's order, then Jobs, each map of a project its own colour", () => {
    expect(g.frames.map((f) => f.title)).toEqual(["Map one", "Map two", "Jobs"]);
    const two = run({ items: [it_("alpha/one#1", "queued"), it_("alpha/six#1", "queued")], maps: ["alpha/one", "alpha/six"] });
    expect(two.columns.map((c) => c.project)).toEqual(["alpha"]);
    expect(two.frames[0]?.hue).not.toBe(two.frames[1]?.hue);
    expect(box("alpha/six#1", two)?.hue).toBe(two.frames[1]?.hue);
  });

  it("marks a stopped ticket and one in checks", () => {
    const s = run({ items: [it_("alpha/one#1", "skipped"), it_("alpha/one#2", "landed"), it_("alpha/one#3", "recheck")] });
    expect(s.frames[0]?.boxes.map((b) => [b.outcome, b.foot])).toEqual([["stopped", "Stopped"], [null, "Waits for its second pass"], [null, "Checks waiting to run"]]);
    expect(s.counts).toMatchObject({ stopped: 1, checking: 2 });
  });

  it("names the chat a finished ticket waits for", () => {
    const s = run({ items: [it_("alpha/one#1", "handed", { handed: { to: "main-chat", at: 0 } })] });
    expect(box("alpha/one#1", s)?.foot).toBe("To integrate · main-chat");
    expect(s.counts).toMatchObject({ checking: 1 });
  });

  it("names the chat that builds a ticket it took, and says when its checks run or failed", () => {
    const chat = { runner: "chat", agent: "main-chat", started: T };
    expect(box("alpha/one#1", run({ items: [it_("alpha/one#1", "running", chat)] }))?.foot).toBe("In chat main-chat");
    expect(box("alpha/one#1", run({ items: [it_("alpha/one#1", "running", { ...chat, done_ask: { by: "main-chat", note: "", at: T } })] }))?.foot)
      .toBe("Checks run · chat main-chat");
    expect(box("alpha/one#1", run({ items: [it_("alpha/one#1", "running", { ...chat, chat_back: "one/test failed", chat_back_at: T })] }))?.foot)
      .toBe("Back to chat main-chat");
  });

  it("puts a column per project and each box at its start time, a row per half hour; what runs at its start, what is queued below now", () => {
    const x = run({ now: T + 3.5 * H, items: [
      it_("alpha/one#1", "done", { started: T, ended: T + H / 2 }),
      it_("beta/two#2", "failed", { started: T + H / 4, ended: T + H / 2 }),
      it_("beta/two#3", "done", { started: T + 2 * H, ended: T + 2.5 * H }),
      it_("alpha/one#2", "running", { started: T + 3 * H }),
      it_("alpha/one#3", "queued"),
    ] });
    expect(x.columns.map((c) => c.project)).toEqual(["alpha", "beta"]);
    const at = (k: string) => [box(k, x)?.y, box(k, x)?.phase];
    expect(at("alpha/one#1")).toEqual([HEAD, "ran"]);
    expect(at("beta/two#2")).toEqual([HEAD + HR / 4, "ran"]);
    expect(at("beta/two#3")).toEqual([HEAD + 2 * HR, "ran"]);
    expect(at("alpha/one#2")).toEqual([HEAD + 3 * HR, "now"]);
    expect(x.nowY).toBe(HEAD + 3.5 * HR);
    // a box is as tall as its run took, at least a box: #1's half hour is one row; #2 runs up to now
    expect(box("alpha/one#1", x)?.h).toBe(HR / 2);
    expect(box("beta/two#2", x)?.h).toBe(NODE_H);
    expect(box("alpha/one#2", x)?.h).toBe(HR / 2);
    expect(box("alpha/one#1", x)?.foot).toBe("Done · 30 min");
    // the queued one starts below the now line and below the running box it would follow
    expect(box("alpha/one#3", x)).toMatchObject({ phase: "next", y: HEAD + 3.5 * HR + ROW_H / 2, h: NODE_H });
    // the clock: the first start, every half hour, now, and about when the queued row starts (#2's start and the
    // night's usual half-hour run); each text on its time's line
    expect(x.rows.map((r) => r.clock)).toEqual(["21:00", "21:30", "22:00", "22:30", "23:00", "23:30", "00:00", "now 00:30", `≈${clock(T + 3 * H + H / 2)}`]);
    expect(x.rows.map((r) => r.phase)).toEqual(["ran", "ran", "ran", "ran", "ran", "ran", "ran", "now", "next"]);
    expect((x.rows[1]?.y ?? 0) + NODE_H / 2).toBe(HEAD + ROW_H);
    expect((x.rows[7]?.y ?? 0) + NODE_H / 2).toBe(x.nowY);
    expect(new Set(x.rows.map((r) => r.row)).size).toBe(x.rows.length);
    // every box the same column x in its project; time runs down
    expect(box("alpha/one#1", x)?.x).toBe(box("alpha/one#3", x)?.x);
    expect(x.boxes.map((b) => b.lane)).toEqual([0, 0, 0, 0, 0]);
  });

  it("puts two projects that run at once side by side at about the same height", () => {
    const x = run({ now: 600, items: [it_("alpha/one#2", "running", { started: 10 }), it_("beta/two#1", "running", { started: 500 })] });
    expect(Math.abs((box("alpha/one#2", x)?.y ?? 0) - (box("beta/two#1", x)?.y ?? 0))).toBeLessThan(ROW_H / 2);
    expect(box("alpha/one#2", x)?.phase).toBe("now");
    expect(box("alpha/one#2", x)?.x).not.toBe(box("beta/two#1", x)?.x);
  });

  it("puts two tickets of one project whose runs overlapped at about the same height in two lanes; one after both goes back to the first", () => {
    const x = run({ atOnce: new Map([["alpha", 2]]), items: [
      it_("alpha/one#1", "done", { started: T, ended: T + H }),
      it_("alpha/one#2", "done", { started: T + 0.2 * H, ended: T + 0.8 * H }),
      it_("alpha/one#3", "done", { started: T + 1.5 * H, ended: T + 1.7 * H }),
    ] });
    const [a, b, c] = ["alpha/one#1", "alpha/one#2", "alpha/one#3"].map((k) => box(k, x));
    expect(Math.abs((a?.y ?? 0) - (b?.y ?? 0))).toBeLessThanOrEqual(HR / 4);
    expect([a?.lane, b?.lane, c?.lane]).toEqual([0, 1, 0]);
    expect(b?.x).toBe((a?.x ?? 0) + NODE_W + GAP);
    expect(x.columns[0]?.w).toBe(2 * NODE_W + GAP);
    // a ticket whose run outlasts its box keeps its lane taken: #2 started under #1's run, though below its box
    const long = run({ items: [it_("alpha/one#1", "done", { started: T, ended: T + 4 * H }), it_("alpha/one#2", "done", { started: T + 2 * H, ended: T + 3 * H })] });
    expect(box("alpha/one#2", long)).toMatchObject({ lane: 1, y: HEAD + 2 * HR, h: HR });
    // nothing runs and nothing ends: the night is over, no now line
    expect(x.nowY).toBeNull();
    expect(x.rows.map((r) => r.clock)).toEqual(["21:00", "21:30", "22:00", "22:30"]);
  });

  it("puts a ticket 3 hours later 6 rows lower, but draws a stretch over 2 hours with nothing in it one row tall", () => {
    const near = run({ items: [it_("alpha/one#1", "done", { started: T, ended: T + 2 * H }), it_("alpha/one#2", "done", { started: T + 3 * H, ended: T + 4 * H })] });
    expect((box("alpha/one#2", near)?.y ?? 0) - (box("alpha/one#1", near)?.y ?? 0)).toBe(3 * HR);
    // #1 ends at 21:30 and #2 starts at 03:00: the 5.5 empty hours take one row, and the clock skips them
    const far = run({ items: [it_("alpha/one#1", "done", { started: T, ended: T + H / 2 }), it_("alpha/one#2", "done", { started: T + 6 * H, ended: T + 7 * H })] });
    expect((box("alpha/one#2", far)?.y ?? 0) - (box("alpha/one#1", far)?.y ?? 0)).toBe(2 * ROW_H);
    expect(far.boxes.map((b) => b.lane)).toEqual([0, 0]);
    expect(far.rows.map((r) => r.clock)).toEqual(["21:00", "21:30", "03:00", "03:30", "04:00"]);
    // another project busy in that stretch keeps it full height
    const busy = run({ items: [...far.boxes.map((b) => b.item), it_("beta/two#2", "done", { started: T + 2 * H, ended: T + 5 * H })] });
    expect((box("alpha/one#2", busy)?.y ?? 0) - (box("alpha/one#1", busy)?.y ?? 0)).toBe(6 * HR);
    // hiding that project's map leaves the stretch empty again
    const hid = run({ items: busy.boxes.map((b) => b.item), hidden: new Set(["beta/two"]) });
    expect((box("alpha/one#2", hid)?.y ?? 0) - (box("alpha/one#1", hid)?.y ?? 0)).toBe(2 * ROW_H);
  });

  it("predicts one ticket per project per row, side by side up to what the project runs at once, after what each comes after", () => {
    const items = [it_("alpha/one#1", "queued"), it_("alpha/one#2", "queued"), it_("alpha/one#3", "queued"), it_("beta/two#2", "queued"), it_("beta/two#1", "queued")];
    const one = run({ items });
    const row = (k: string, x = one) => box(k, x)?.row;
    expect([row("alpha/one#1"), row("alpha/one#2"), row("alpha/one#3")]).toEqual([0, 1, 2]);
    // beta's two run in the same rows as alpha's: both projects progress; beta#1 waits for alpha#2 (an 'after' across projects)
    expect(row("beta/two#2")).toBe(0);
    expect(row("beta/two#1")).toBe(2);
    expect(one.boxes.every((b) => b.phase === "next")).toBe(true);
    // nothing ended yet: every row to come still has a rough time, 1.5 h apart, not 'next' and 'then'
    expect(one.rows.map((r) => r.clock.replace(/\d\d:\d\d/, "hh:mm"))).toEqual(["now hh:mm", "≈hh:mm", "≈hh:mm", "≈hh:mm"]);
    // alpha runs two at once: #2 and #3 (both after #1) share a row, side by side
    const two = run({ items, atOnce: new Map([["alpha", 2]]) });
    expect([row("alpha/one#1", two), row("alpha/one#2", two), row("alpha/one#3", two)]).toEqual([0, 1, 1]);
    expect([box("alpha/one#2", two)?.lane, box("alpha/one#3", two)?.lane]).toEqual([0, 1]);
    expect(two.columns[0]?.w).toBeGreaterThan(two.columns[1]?.w ?? 0);
    // a later map of a project waits for the earlier one; a job waits for its project to be empty
    const maps = run({ items: [it_("alpha/six#1", "queued"), it_("alpha/one#1", "queued"), job()], maps: ["alpha/one", "alpha/six"], atOnce: new Map([["alpha", 3]]) });
    expect([row("alpha/one#1", maps), row("alpha/six#1", maps), row("job:close", maps)]).toEqual([0, 1, 2]);
  });

  it("draws every 'after', across projects too, and an arrow from each project's last ticket into one Done box", () => {
    const after = g.edges.filter((e) => e.to !== DONE_ID).map((e) => [e.from, e.to, e.across]).sort();
    expect(after).toEqual([
      ["alpha/one#1", "alpha/one#2", false],
      ["alpha/one#1", "alpha/one#3", false],
      ["alpha/one#2", "beta/two#1", true],
    ]);
    const last = (p: string) => g.boxes.filter((b) => b.project === p).sort((a, b) => b.row - a.row || b.lane - a.lane)[0]?.id;
    expect(g.edges.filter((e) => e.to === DONE_ID).map((e) => e.from).sort()).toEqual([last("alpha"), last("beta")].sort());
    expect(g.done).toMatchObject({ finished: 2, total: 6, line: "2 of 6 finished" });
    expect(g.done?.y).toBeGreaterThan(Math.max(...g.boxes.map((b) => b.y)));
  });

  it("drops a hidden map with its arrows, and the rows only it filled; its chip stays to show it again", () => {
    const h = run({ hidden: new Set(["beta/two"]) });
    expect(h.boxes.some((b) => b.map === "beta/two")).toBe(false);
    expect(h.edges.some((e) => e.from.startsWith("beta/") || e.to.startsWith("beta/"))).toBe(false);
    expect(h.columns.map((c) => c.project)).toEqual(["alpha"]);
    expect(h.frames.find((f) => f.map === "beta/two")).toMatchObject({ hidden: true });
    expect(h.done).toMatchObject({ total: 4 });
    // beta#1's queued row held only it: the rows to come close up, a clock each
    const next = [...new Set(h.boxes.filter((b) => b.phase === "next").map((b) => b.y))].sort((a, b) => a - b);
    expect(next).toEqual([next[0], (next[0] ?? 0) + ROW_H]);
    expect(h.rows.filter((r) => r.phase === "next")).toHaveLength(next.length);
  });

  it("counts for the run, leaving out zeros, and narrows to a project", () => {
    expect(g.frames[0]?.line).toBe("1 done · 1 running · 1 next");
    expect(g.line).toBe("1 done · 1 running · 3 next · 1 fell short");
    expect(countsLine({ done: 5, landed: 0, running: 2, checking: 0, next: 9, "fell short": 1, stopped: 0 })).toBe("5 done · 2 running · 9 next · 1 fell short");
    const one = run({ scope: { project: "alpha", map: "" } });
    expect(one.frames.map((f) => f.title)).toEqual(["Map one", "Jobs"]);
    expect(one.edges.filter((e) => e.to !== DONE_ID)).toHaveLength(2);
    expect(run({ scope: { project: "beta", map: "" } }).frames.map((f) => f.title)).toEqual(["Map two"]);
  });

  it("updates live: a ticket queued late takes its predicted row, one that starts sits at its start, the others stay", () => {
    const base = [it_("alpha/one#1", "done", { started: T, ended: T + H / 2 }), it_("alpha/one#2", "running", { started: T + H }), it_("alpha/one#3", "queued")];
    const a = run({ items: base, now: T + 1.5 * H });
    const where = (x: typeof a) => new Map(x.boxes.map((b) => [b.id, [b.x, b.y]] as const));
    // another project queues a ticket: it lands in the first row to come; nothing else moves
    const b = run({ items: [...base, it_("beta/two#2", "queued")], now: T + 1.5 * H, prev: a.memo });
    expect(box("beta/two#2", b)?.row).toBe(box("alpha/one#3", b)?.row);
    for (const [id, p] of where(a)) expect(where(b).get(id)).toEqual(p);
    // #2 ends and #3 starts: #3 moves to its start, under the now line's old place; #1 and #2 stay, the columns keep their x
    const c = run({ items: [base[0], { ...base[1], state: "done", ended: T + 2 * H }, { ...base[2], state: "running", started: T + 2.5 * H }, it_("beta/two#2", "queued")] as QueueItem[], now: T + 2.6 * H, prev: b.memo });
    expect(box("alpha/one#3", c)).toMatchObject({ phase: "now", y: HEAD + 2.5 * HR, lane: 0 });
    expect(box("alpha/one#1", c)?.y).toBe(box("alpha/one#1", a)?.y);
    expect(box("alpha/one#2", c)?.y).toBe(box("alpha/one#2", a)?.y);
    expect(c.columns.map((x) => x.x)).toEqual(b.columns.map((x) => x.x));
  });

  it("does not move a box when a newer one arrives, nor when an older one shows up late (it keeps its lane)", () => {
    const at = { atOnce: new Map([["alpha", 3]]) };
    const a = run({ ...at, now: T + 1.2 * H, items: [it_("alpha/one#1", "done", { started: T, ended: T + H }), it_("alpha/one#2", "running", { started: T + 0.5 * H })] });
    const where = (x: typeof a) => new Map(x.boxes.map((b) => [b.id, [b.x, b.y, b.lane]] as const));
    expect(where(a).get("alpha/one#2")?.[2]).toBe(1);
    // a newer one starts in another project and a newer one in alpha: the old boxes stay
    const b = run({ ...at, now: T + 1.3 * H, prev: a.memo, items: [...a.boxes.map((x) => x.item), it_("alpha/one#3", "running", { started: T + 0.9 * H }), it_("beta/two#2", "running", { started: T + 1.1 * H })] });
    for (const [id, p] of where(a)) expect(where(b).get(id)).toEqual(p);
    // a ticket that started before #2 shows up only now (a chat's): #2 keeps lane 1, the late one takes the next free
    const late = [...b.boxes.map((x) => x.item), it_("alpha/one#9", "done", { started: T + 0.1 * H, ended: T + 0.3 * H })];
    const c = run({ ...at, now: T + 1.3 * H, prev: b.memo, items: late });
    for (const [id, p] of where(b)) expect(where(c).get(id)).toEqual(p);
    expect(box("alpha/one#9", c)?.lane).toBe(2);
    // without the memo it would have pushed #2 over
    expect(box("alpha/one#2", run({ ...at, now: T + 1.3 * H, items: late }))?.lane).toBe(2);
  });

  it("draws an ended run as it ran: a ticket's kept arrows and map title win over what the maps say today", () => {
    // today alpha/one#2 no longer comes after #1 and the map was renamed; the run kept both as they were
    const today = { maps: new Map([["alpha/one", "Renamed"]]), tickets: new Map([["alpha/one#2", { title: "Second, renamed", after: [] }]]) };
    const kept = [
      it_("alpha/one#1", "done", { started: T, ended: T + H, title: "First", after: [], map_title: "Map one" }),
      it_("alpha/one#2", "done", { started: T + H, ended: T + 2 * H, title: "Second", after: ["alpha/one#1"], map_title: "Map one" }),
    ];
    const f = frozenInfo(kept, today);
    expect(f.tickets.get("alpha/one#2")).toEqual({ title: "Second", after: ["alpha/one#1"] });
    expect(f.maps.get("alpha/one")).toBe("Map one");
    const x = nightGraph({ items: kept, maps: ["alpha/one"], info: f, scope: EVERYTHING, now: T + 2 * H });
    expect(x.edges.filter((e) => e.to !== DONE_ID).map((e) => e.id)).toEqual(["alpha/one#1>alpha/one#2"]);
    expect(x.frames[0]?.title).toBe("Map one");
    // a ticket that kept nothing (a run from before) keeps today's
    const old = frozenInfo([it_("alpha/one#2", "done")], today);
    expect(old.tickets.get("alpha/one#2")).toEqual({ title: "Second, renamed", after: [] });
  });

  it("centres on the now line, under what runs now, else under what is queued", () => {
    const b = box("alpha/one#2");
    expect(g.nowY).not.toBeNull();
    expect(focusOf(g)).toEqual({ x: (b?.x ?? 0) + 110, y: g.nowY });
    expect(focusOf(run({ items: [it_("alpha/one#1", "done")] }))).toBeNull();
  });

  it("measures the whole graph across, so the view can open with every column in sight", () => {
    const last = g.columns[g.columns.length - 1];
    expect(spanOf(g)).toBe((last?.x ?? 0) + (last?.w ?? 0));
    expect(spanOf({ columns: [] })).toBe(0);
  });

  it("reads the hub's real queue and ticket rows (contract fixtures): its first map's two side by side, then the next map, then the jobs alone", () => {
    const body = (f: string): unknown => (JSON.parse(readFileSync(join(import.meta.dirname, `../../../contract/fixtures/${f}`), "utf8")) as { body: unknown }).body;
    const state = body("state.json") as State;
    const rows = body("tickets.json") as TicketRow[];
    const q = state.queue;
    const x = nightGraph({ items: q.items, maps: q.maps ?? [], info: infoOf([], rows), scope: EVERYTHING, atOnce: atOnceOf(q.repos) });
    expect(x.columns.map((c) => c.project)).toEqual(["repo"]);
    const row = (k: string) => x.boxes.find((b) => b.id === k)?.row;
    expect([row("repo/two#5"), row("repo/two#6"), row("repo/one#3"), row("repo/one#2")]).toEqual([0, 0, 1, 1]);
    expect([row("job:aaaaaaaaaaaa:1"), row("job:tttttttttttt:1")]).toEqual([2, 3]);
    expect(x.frames.map((f) => f.map)).toEqual(["repo/two", "repo/one", ""]);
    expect(x.done).toMatchObject({ finished: 0, total: 6 });
  });
});

describe("chunkGraph: 15-minute columns, left to right", () => {
  const M = 60;
  const t = (title: string, after: string[] = []): TicketInfo => ({ title, after });
  const tickets = (...rows: [string, string[]?][]): ChunkInput["info"] => ({ maps: new Map(), tickets: new Map(rows.map(([k, a]) => [k, t(k, a ?? [])])) });
  const chunks = (more: Partial<ChunkInput> & Pick<ChunkInput, "items">): ChunkGraph =>
    chunkGraph({ maps: ["alpha/one", "beta/two"], info: tickets(), scope: EVERYTHING, ...more });
  const bar = (g: ChunkGraph, id: string) => {
    const b = g.bars.find((x) => x.id === id);
    if (b === undefined) throw new Error(`no bar ${id}`);
    return b;
  };
  /** Every bar's arrow leaves its right end and meets the next one's left end; Done's left end too. */
  const ends = (g: ChunkGraph) => g.edges.map((e) => {
    const from = bar(g, e.from);
    const to = e.to === DONE_ID ? (g.done?.x ?? 0) : bar(g, e.to).x;
    return [from.x + from.w, to] as const;
  });
  const overlapsInTrack = (g: ChunkGraph): string[] => {
    const out: string[] = [];
    for (const a of g.bars) for (const b of g.bars) if (a.id < b.id && a.project === b.project && a.track === b.track && a.from <= b.to && b.from <= a.to) out.push(`${a.id}~${b.id}`);
    return out;
  };

  it("starts at the quarter the night's first start falls in and labels each column with its clock", () => {
    const g = chunks({ items: [it_("alpha/one#1", "done", { started: T + 5 * M, ended: T + 40 * M })], now: T + 2 * H });
    expect(g.columns.map((c) => c.clock)).toEqual(["21:00", "21:15", "21:30"]);
    expect(g.columns.map((c) => c.x)).toEqual([LEFT, LEFT + CHUNK_W, LEFT + 2 * CHUNK_W]);
  });

  it("puts two overlapping tickets of one band on two tracks, and a later one back on the first", () => {
    const g = chunks({
      items: [
        it_("alpha/one#1", "done", { started: T, ended: T + 40 * M }),
        it_("alpha/one#2", "done", { started: T + 20 * M, ended: T + 50 * M }),
        it_("alpha/one#3", "done", { started: T + 60 * M, ended: T + 70 * M }),
      ],
      now: T + 2 * H,
    });
    expect([bar(g, "alpha/one#1").track, bar(g, "alpha/one#2").track, bar(g, "alpha/one#3").track]).toEqual([0, 1, 0]);
    expect(g.bands).toMatchObject([{ project: "alpha", tracks: 2 }]);
    expect(bar(g, "alpha/one#2").y).toBeGreaterThan(bar(g, "alpha/one#1").y);
    expect(overlapsInTrack(g)).toEqual([]);
  });

  it("draws a 50-minute ticket across 4 columns, and a running one to the now column", () => {
    const g = chunks({ items: [it_("alpha/one#1", "done", { started: T, ended: T + 50 * M }), it_("beta/two#1", "running", { started: T + 10 * M })], now: T + 65 * M });
    expect(bar(g, "alpha/one#1")).toMatchObject({ from: 0, to: 3, x: LEFT, w: 4 * CHUNK_W - BAR_GAP });
    // a run ending on a column's line stays out of that column
    expect(bar(chunks({ items: [it_("alpha/one#1", "done", { started: T, ended: T + 60 * M })], now: T + 2 * H }), "alpha/one#1").to).toBe(3);
    expect(bar(g, "beta/two#1")).toMatchObject({ from: 0, to: 4, phase: "now" });
    expect(g.nowX).toBe(LEFT + (65 / 15) * CHUNK_W);
    expect(g.columns.find((c) => c.chunk === 4)?.phase).toBe("now");
  });

  it("puts a queued ticket right of the estimated end of the ticket it comes after, running or queued", () => {
    // the night's usual run: the one finished ticket's 45 minutes
    const g = chunks({
      items: [
        it_("alpha/one#1", "done", { started: T, ended: T + 45 * M }),
        it_("alpha/one#2", "running", { started: T + 50 * M }),
        it_("alpha/one#3", "queued"),
        it_("alpha/one#4", "queued"),
      ],
      info: tickets(["alpha/one#3", ["alpha/one#2"]], ["alpha/one#4", ["alpha/one#3"]]),
      paths: new Map([["alpha/one#2", ["a/"]], ["alpha/one#3", ["b/"]], ["alpha/one#4", ["c/"]]]),
      now: T + 60 * M,
    });
    const two = bar(g, "alpha/one#2");
    const three = bar(g, "alpha/one#3");
    expect(two.until).toBe(T + 95 * M);
    // 22:35 ends #2, so #3 takes the 22:45 column, right of the now line and of that end
    expect(three.from).toBe(7);
    expect(three.x).toBeGreaterThanOrEqual(LEFT + (95 / 15) * CHUNK_W);
    expect(three.x).toBeGreaterThan(g.nowX ?? Infinity);
    expect(bar(g, "alpha/one#4").from).toBe(three.to + 1);
  });

  it("lets two queued tickets with paths apart share a column; two that share a path, or one naming none, wait", () => {
    const g = chunks({
      items: [it_("alpha/one#1", "queued"), it_("alpha/one#2", "queued"), it_("alpha/one#3", "queued"), it_("alpha/one#4", "queued"), it_("beta/two#1", "queued")],
      paths: new Map([["alpha/one#1", ["src/a/"]], ["alpha/one#2", ["src/b"]], ["alpha/one#3", ["src/a/x.ts"]], ["beta/two#1", ["src/a/"]]]),
      now: T,
    });
    const [one, two, three, four, other] = ["alpha/one#1", "alpha/one#2", "alpha/one#3", "alpha/one#4", "beta/two#1"].map((k) => bar(g, k));
    expect(two?.from).toBe(one?.from);
    expect(three?.from).toBe((one?.to ?? 0) + 1);
    // #4 names no path: it waits for everything else of its project
    expect(four?.from).toBe((three?.to ?? 0) + 1);
    // another project never shares
    expect(other?.from).toBe(one?.from);
    expect(one?.track).not.toBe(two?.track);
    expect(overlapsInTrack(g)).toEqual([]);
    expect(pathsMeet(["/src/a/"], ["src/a/b.ts"])).toBe(true);
    expect(pathsMeet(["src/ab"], ["src/a"])).toBe(false);
  });

  it("notes a future column whose layout runs more than the project's at-once limit", () => {
    const items = [it_("alpha/one#1", "queued"), it_("alpha/one#2", "queued"), it_("alpha/one#3", "queued")];
    const paths = new Map([["alpha/one#1", ["a"]], ["alpha/one#2", ["b"]], ["alpha/one#3", ["c"]]]);
    const g = chunks({ items, paths, now: T });
    const first = bar(g, "alpha/one#1").from;
    expect(g.notes.find((n) => n.chunk === first)).toMatchObject({ project: "alpha", could: 3, runs: 1, text: "3 could run, hub runs 1" });
    expect(g.notes.every((n) => n.chunk > 0)).toBe(true);
    expect(chunks({ items, paths, now: T, atOnce: new Map([["alpha", 3]]) }).notes).toEqual([]);
  });

  it("points every arrow right, Done right of the last column", () => {
    const g = chunks({
      items: [
        it_("alpha/one#1", "done", { started: T, ended: T + 30 * M }),
        it_("alpha/one#2", "running", { started: T + 30 * M }),
        it_("alpha/one#3", "queued"),
        it_("beta/two#1", "queued"),
        it_("beta/two#2", "queued"),
      ],
      info: tickets(["alpha/one#2", ["alpha/one#1"]], ["alpha/one#3", ["alpha/one#2"]], ["beta/two#1", ["alpha/one#1", "alpha/one#3"]], ["beta/two#2", ["beta/two#1"]]),
      now: T + 40 * M,
    });
    expect(g.edges.filter((e) => e.to !== DONE_ID).map((e) => e.id).sort()).toEqual(["alpha/one#1>alpha/one#2", "alpha/one#1>beta/two#1", "alpha/one#2>alpha/one#3", "alpha/one#3>beta/two#1", "beta/two#1>beta/two#2"]);
    expect(g.edges.filter((e) => e.to === DONE_ID)).toHaveLength(2);
    for (const [a, b] of ends(g)) expect(a).toBeLessThan(b);
    const lastCol = g.columns[g.columns.length - 1];
    expect(g.done?.x).toBeGreaterThan((lastCol?.x ?? 0) + CHUNK_W - 1);
  });

  it("keeps the bands where they were when a new project's ticket comes in", () => {
    const items = [it_("alpha/one#1", "running", { started: T }), it_("beta/two#1", "queued")];
    const first = chunks({ items, now: T + 10 * M });
    expect(first.bands.map((b) => b.project)).toEqual(["alpha", "beta"]);
    const more = { items: [...items, it_("gamma/three#1", "queued")], maps: ["gamma/three", "beta/two", "alpha/one"], now: T + 20 * M };
    expect(chunks(more).bands.map((b) => b.project)).toEqual(["gamma", "beta", "alpha"]);
    const second = chunks({ ...more, prev: first.memo });
    expect(second.bands.map((b) => b.project)).toEqual(["alpha", "beta", "gamma"]);
    expect(chunks({ ...more, prev: second.memo }).bands.map((b) => b.project)).toEqual(["alpha", "beta", "gamma"]);
  });

  it("lays out the hub's recorded queue answer (contract fixtures) with its ticket rows' paths: no two bars of a track overlap", () => {
    const body = (f: string): unknown => (JSON.parse(readFileSync(join(import.meta.dirname, `../../../contract/fixtures/${f}`), "utf8")) as { body: unknown }).body;
    // the answer to a stop: repo/one#2 runs, two tickets of each map and a job wait
    const q = (body("queue-stop.json") as { queue: Queue }).queue;
    const rows = body("tickets.json") as TicketRow[];
    const started = q.items.find((i) => i.state === "running")?.started ?? 0;
    const g = chunkGraph({ items: q.items, maps: q.maps ?? [], info: infoOf([], rows), scope: EVERYTHING, atOnce: atOnceOf(q.repos), paths: pathsOf(rows), now: started + 600 });
    expect(g.bars).toHaveLength(q.items.length);
    expect(overlapsInTrack(g)).toEqual([]);
    const from = (k: string) => bar(g, k).from;
    // two#5 and two#6 both name five/: one after the other; one#3 (three/) meets neither, nor the running one#2 (two/)
    expect(from("repo/one#3")).toBe(from("repo/two#5"));
    expect(from("repo/two#6")).toBeGreaterThan(bar(g, "repo/two#5").to);
    // the job names no path, so it waits for every ticket of its project
    expect(from("job:aaaaaaaaaaaa:1")).toBeGreaterThan(Math.max(...g.bars.filter((b) => b.item.kind === "ticket").map((b) => b.to)));
    // the running one, two queued beside it: 3 could run where the repo runs 2 at once
    expect(g.notes[0]).toMatchObject({ project: "repo", could: 3, runs: 2, text: "3 could run, hub runs 2" });
    for (const [a, b] of ends(g)) expect(a).toBeLessThan(b);
  });
});
