import { describe, expect, it } from "vitest";
import type { QueueItem } from "@sb-hub/contract";
import { EVERYTHING } from "./board.ts";
import { countsLine, focusOf, nightGraph, type NightInput, type TicketInfo } from "./nightGraph.ts";

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
  const box = (id: string) => g.frames.flatMap((f) => f.boxes).find((b) => b.id === id);

  it("makes one frame per map in the hub's order, then Jobs", () => {
    expect(g.frames.map((f) => f.title)).toEqual(["Map one", "Map two", "Jobs"]);
    expect(g.frames.map((f) => f.map)).toEqual(["alpha/one", "beta/two", ""]);
    expect(run({ maps: ["beta/two", "alpha/one"] }).frames.map((f) => f.title)).toEqual(["Map two", "Map one", "Jobs"]);
  });

  it("gives each box its state, outcome and place in the whole line; a ticket never queued is absent", () => {
    expect(box("alpha/one#1")).toMatchObject({ state: "done", outcome: "done", foot: "Done", report: "obsidian://report-1", place: null });
    expect(box("alpha/one#2")).toMatchObject({ state: "running", outcome: null, foot: "Running", report: null });
    // beta/two#1 is first in the queue's items, alpha/one#3 second: places count across frames
    expect(box("beta/two#1")).toMatchObject({ state: "queued", place: 1, foot: "Queued 1" });
    expect(box("alpha/one#3")).toMatchObject({ state: "queued", place: 2, foot: "Queued 2" });
    expect(box("beta/two#2")).toMatchObject({ outcome: "fell short", foot: "Fell short", report: "obsidian://report-2" });
    expect(box("job:close")).toMatchObject({ frame: "f:jobs", title: "Close off the night", place: 3 });
    expect(box("alpha/one#9")).toBeUndefined();
    expect(g.frames.flatMap((f) => f.boxes)).toHaveLength(6);
  });

  it("marks a stopped ticket and one in checks", () => {
    const s = run({ items: [it_("alpha/one#1", "skipped"), it_("alpha/one#2", "landed"), it_("alpha/one#3", "recheck")] });
    expect(s.frames[0]?.boxes.map((b) => [b.outcome, b.foot])).toEqual([["stopped", "Stopped"], [null, "Waits for its second pass"], [null, "Checks waiting to run"]]);
    expect(s.counts).toMatchObject({ stopped: 1, checking: 2 });
  });

  it("draws an arrow for each 'after', across frames too, none to a ticket that is not shown", () => {
    expect(g.edges.map((e) => [e.from, e.to, e.across]).sort()).toEqual([
      ["alpha/one#1", "alpha/one#2", false],
      ["alpha/one#1", "alpha/one#3", false],
      ["alpha/one#2", "beta/two#1", true],
    ]);
  });

  it("counts per frame and for the run, leaving out zeros", () => {
    expect(g.frames[0]?.line).toBe("1 done · 1 running · 1 next");
    expect(g.frames[1]?.line).toBe("1 next · 1 fell short");
    expect(g.line).toBe("1 done · 1 running · 3 next · 1 fell short");
    expect(countsLine({ done: 5, running: 2, checking: 0, next: 9, "fell short": 1, stopped: 0 })).toBe("5 done · 2 running · 9 next · 1 fell short");
  });

  it("narrows to a project: only its frames, only its arrows, a job by its folder", () => {
    const one = run({ scope: { project: "alpha", map: "" } });
    expect(one.frames.map((f) => f.title)).toEqual(["Map one", "Jobs"]);
    expect(one.edges).toHaveLength(2);
    expect(run({ scope: { project: "beta", map: "" } }).frames.map((f) => f.title)).toEqual(["Map two"]);
  });

  it("puts a ticket below the ones it comes after, inside its frame, and stacks the frames", () => {
    const one = g.frames[0];
    expect((box("alpha/one#2")?.y ?? 0) > (box("alpha/one#1")?.y ?? 0)).toBe(true);
    expect(box("alpha/one#2")?.y).toBe(box("alpha/one#3")?.y);
    expect((g.frames[1]?.y ?? 0) >= (one?.y ?? 0) + (one?.h ?? 0)).toBe(true);
  });

  it("keeps every box where it was when a state changes or a ticket joins", () => {
    const where = (x: ReturnType<typeof run>) => new Map(x.frames.flatMap((f) => f.boxes.map((b) => [b.id, [f.x + b.x, f.y + b.y]] as const)));
    const before = where(g);
    const changed = items().map((i) => (i.key === "beta/two#1" ? { ...i, state: "running" as const } : i.key === "alpha/one#2" ? { ...i, state: "done" as const } : i));
    const after = nightGraph({ items: changed, maps: ["alpha/one", "beta/two"], info: info(), scope: EVERYTHING, prev: g.slots });
    expect(where(after)).toEqual(before);
    expect(after.frames.flatMap((f) => f.boxes).find((b) => b.id === "alpha/one#2")?.state).toBe("done");
    // a ticket queued late takes a free place in its frame; the others stay
    const joined = nightGraph({ items: [...changed, it_("alpha/one#9", "queued")], maps: ["alpha/one", "beta/two"], info: info(), scope: EVERYTHING, prev: after.slots });
    const now = where(joined);
    for (const [id, p] of before) expect(now.get(id)).toEqual(p);
    expect(now.has("alpha/one#9")).toBe(true);
  });

  it("centres on what runs now, else on what is queued", () => {
    const f = focusOf(g);
    const two = g.frames[0];
    const b = box("alpha/one#2");
    expect(f).toEqual({ x: (two?.x ?? 0) + (b?.x ?? 0) + 110, y: (two?.y ?? 0) + (b?.y ?? 0) + 34 });
    expect(focusOf(run({ items: [it_("alpha/one#1", "done")] }))).toBeNull();
  });
});
