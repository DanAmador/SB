import { describe, expect, it } from "vitest";
import type { QueueItem } from "@sb-hub/contract";
import { EVERYTHING } from "./board.ts";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { State, TicketRow } from "@sb-hub/contract";
import { atOnceOf, clock, countsLine, DONE_ID, focusOf, infoOf, nightGraph, type NightInput, type TicketInfo } from "./nightGraph.ts";

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

  it("puts a column per project and rows by start order, what ran above now, what runs on it, what is queued below", () => {
    const x = run({ items: [
      it_("alpha/one#1", "done", { started: 1000, ended: 1500 }),
      it_("beta/two#2", "failed", { started: 1100, ended: 1200 }),
      it_("beta/two#3", "done", { started: 1300, ended: 1400 }),
      it_("alpha/one#2", "running", { started: 1600 }),
      it_("alpha/one#3", "queued"),
    ] });
    expect(x.columns.map((c) => c.project)).toEqual(["alpha", "beta"]);
    const at = (k: string) => [box(k, x)?.row, box(k, x)?.phase];
    // alpha#1 and beta#2 started first and share a row; beta#3 is beta's next, so a row of its own
    expect(at("alpha/one#1")).toEqual([0, "ran"]);
    expect(at("beta/two#2")).toEqual([0, "ran"]);
    expect(at("beta/two#3")).toEqual([1, "ran"]);
    expect(at("alpha/one#2")).toEqual([2, "now"]);
    expect(at("alpha/one#3")).toEqual([3, "next"]);
    expect(x.rows.map((r) => r.clock.replace(/\d\d:\d\d/, "hh:mm"))).toEqual(["hh:mm", "hh:mm", "now hh:mm", "≈hh:mm"]);
    expect(x.rows[0]?.clock).toBe(clock(1000));
    expect(x.nowY).toBeLessThan(box("alpha/one#2", x)?.y ?? 0);
    expect(x.nowY).toBeGreaterThan(box("beta/two#3", x)?.y ?? 0);
    // every box the same column x in its project; time runs down
    expect(box("alpha/one#1", x)?.x).toBe(box("alpha/one#3", x)?.x);
    expect((box("alpha/one#3", x)?.y ?? 0) > (box("alpha/one#2", x)?.y ?? 0)).toBe(true);
  });

  it("puts two projects that run at once on the same row", () => {
    const x = run({ items: [it_("alpha/one#2", "running", { started: 10 }), it_("beta/two#1", "running", { started: 500 })] });
    expect(box("alpha/one#2", x)?.row).toBe(box("beta/two#1", x)?.row);
    expect(box("alpha/one#2", x)?.phase).toBe("now");
    expect(box("alpha/one#2", x)?.x).not.toBe(box("beta/two#1", x)?.x);
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
    expect(one.rows.map((r) => r.clock.replace(/\d\d:\d\d/, "hh:mm"))).toEqual(["≈hh:mm", "≈hh:mm", "≈hh:mm"]);
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
    expect(new Set(h.boxes.map((b) => b.row)).size).toBe(h.rows.length);
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

  it("updates live: a ticket queued late takes its predicted row, one that starts moves to now, the others stay", () => {
    const base = [it_("alpha/one#1", "done", { started: 100, ended: 200 }), it_("alpha/one#2", "running", { started: 300 }), it_("alpha/one#3", "queued")];
    const a = run({ items: base });
    const where = (x: typeof a) => new Map(x.boxes.map((b) => [b.id, [b.x, b.y]] as const));
    // another project queues a ticket: it lands in the first row to come; nothing else moves
    const b = run({ items: [...base, it_("beta/two#2", "queued")], prev: a.memo });
    expect(box("beta/two#2", b)?.row).toBe(box("alpha/one#3", b)?.row);
    for (const [id, p] of where(a)) expect(where(b).get(id)).toEqual(p);
    // #2 ends and #3 starts: #3 moves onto the now row, #1 and #2 stay above it, the columns keep their x
    const c = run({ items: [base[0], { ...base[1], state: "done", ended: 400 }, { ...base[2], state: "running", started: 450 }, it_("beta/two#2", "queued")] as QueueItem[], prev: b.memo });
    expect(box("alpha/one#3", c)?.phase).toBe("now");
    expect(box("alpha/one#1", c)?.y).toBe(box("alpha/one#1", a)?.y);
    expect(box("alpha/one#2", c)?.y).toBe(box("alpha/one#2", a)?.y);
    expect(c.columns.map((x) => x.x)).toEqual(b.columns.map((x) => x.x));
  });

  it("centres on what runs now, else on what is queued", () => {
    const b = box("alpha/one#2");
    expect(focusOf(g)).toEqual({ x: (b?.x ?? 0) + 110, y: (b?.y ?? 0) + 34 });
    expect(focusOf(run({ items: [it_("alpha/one#1", "done")] }))).toBeNull();
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
