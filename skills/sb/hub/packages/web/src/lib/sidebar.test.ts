import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { QueueItem, State, TicketRow } from "@sb-hub/contract";
import { describe, expect, it } from "vitest";
import { activeOnly, sidebarTree } from "./sidebar.ts";

const NO_LINKS = { ticket: null, map: null, board: null, report: null, log: null };
const ticket = (map: string, num: number, more: Partial<TicketRow> = {}): TicketRow =>
  ({
    map, num, title: `${map} ${String(num)}`, why: "", type: "task", status: "open", priority: null, blocked_by: [], blocked_by_open: [], paths: [], tier: "sonnet",
    check: "tests", has_done_when: true, done_when: "", question: "", out: "", checks: ["true"], repo: "/r", file: "/f.md", map_title: map, map_order: 1, claimed_by: null,
    queued: false, state: "ready", reason: "ready", links: NO_LINKS, ...more,
  });
const item = (key: string, state: QueueItem["state"], more: Partial<QueueItem> = {}): QueueItem =>
  ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, links: NO_LINKS, ...more }) as QueueItem;
const state = (items: QueueItem[]): State => ({ queue: { items }, agents: {}, now: 0 }) as unknown as State;

// sb/busy: 2 ready, 1 queued, 1 running; sb/idle: 1 ready; sb/quiet: only a claimed ticket; sb/nocheck: ready-looking but no checks
// other/old: nothing at all; other/live: a queued job-free ticket, nothing ready
const tickets = [
  ticket("sb/busy", 1), ticket("sb/busy", 2), ticket("sb/busy", 3), ticket("sb/busy", 4),
  ticket("sb/idle", 1),
  ticket("sb/quiet", 1, { status: "claimed", state: "claimed", reason: "claimed by hub" }),
  ticket("sb/nocheck", 1, { checks: [], state: "not ready", reason: "no check commands" }),
  ticket("sb/nocheck", 2, { checks: [], state: "not ready", reason: "no check commands" }),
  ticket("other/old", 1, { state: "waits for you", type: "grilling" }),
  ticket("other/live", 1, { state: "blocked", reason: "after x" }),
];
const s = state([item("sb/busy#3", "queued"), item("sb/busy#4", "running"), item("other/live#1", "queued"), item("sb/busy#9", "failed")]);
const none = { project: "", map: "" };

describe("sidebarTree", () => {
  it("counts can run now and queued per map, summing them per project and for Everything", () => {
    const t = sidebarTree(s, tickets, none);
    const sb = t.projects.find((p) => p.project === "sb");
    const busy = sb?.maps.find((m) => m.map === "sb/busy");
    // #3 and #4 are in line, so only #1 and #2 can start
    expect([busy?.canRun, busy?.queued]).toEqual([2, 2]);
    expect([sb?.canRun, sb?.queued]).toEqual([3, 2]);
    expect(t.projects.map((p) => [p.project, p.canRun, p.queued])).toEqual([["other", 0, 1], ["sb", 3, 2]]);
    expect([t.all.canRun, t.all.queued]).toEqual([3, 3]);
  });

  it("shows a green dot where a worker runs, on the map, its project and Everything", () => {
    const t = sidebarTree(s, tickets, none);
    expect(t.all.running).toBe(true);
    expect(t.projects.map((p) => [p.project, p.running])).toEqual([["other", false], ["sb", true]]);
    expect(t.projects[1]?.maps.map((m) => [m.map, m.running])).toEqual([["sb/busy", true], ["sb/idle", false], ["sb/nocheck", false], ["sb/quiet", false]]);
    expect(sidebarTree(state([]), tickets, none).all.running).toBe(false);
  });

  it("counts a ticket one of the owner's chats works on as running, so Active only shows its project", () => {
    const chat = { ...state([]), agents: { c: { agent: "c", ref: "other/live#1", state: "working", at: 0 } }, chat_runs: [{ key: "other/live#1", agent: "c", night: null, started: 0, last: 0 }] } as unknown as State;
    const t = sidebarTree(chat, tickets, none);
    expect(t.projects.find((p) => p.project === "other")?.running).toBe(true);
    expect(activeOnly(t, none).projects.map((p) => p.project)).toContain("other");
  });

  it("has no quiet list: every map is listed, running, can run, queued, stuck, ties by name", () => {
    const t = sidebarTree(s, tickets, none);
    const sb = t.projects.find((p) => p.project === "sb");
    expect(sb?.maps.map((m) => m.map)).toEqual(["sb/busy", "sb/idle", "sb/nocheck", "sb/quiet"]);
    expect(Object.keys(sb ?? {})).not.toContain("quiet");
    expect(t.projects.find((p) => p.project === "other")?.maps.map((m) => m.map)).toEqual(["other/live", "other/old"]);
  });

  it("orders every tier: running, can run, queued, stuck", () => {
    const rows = [ticket("z/a-stuck", 1, { state: "waits for you" }), ticket("z/b-queued", 1, { state: "blocked" }), ticket("z/c-can", 1), ticket("z/d-run", 1, { state: "blocked" })];
    const t = sidebarTree(state([item("z/b-queued#1", "queued"), item("z/d-run#1", "running")]), rows, none);
    expect(t.projects[0]?.maps.map((m) => m.map)).toEqual(["z/d-run", "z/c-can", "z/b-queued", "z/a-stuck"]);
  });

  it("a stuck map carries its reason; a busy one has none", () => {
    const sb = sidebarTree(s, tickets, none).projects.find((p) => p.project === "sb");
    expect(Object.fromEntries((sb?.maps ?? []).map((m) => [m.map, m.reason]))).toEqual({ "sb/busy": "", "sb/idle": "", "sb/nocheck": "no checks", "sb/quiet": "claimed" });
    expect(sidebarTree(s, tickets, none).projects.find((p) => p.project === "other")?.maps.map((m) => m.reason)).toEqual(["", "waits for you"]);
  });

  it("reads the recorded contract fixture: a ticket that waits for you makes its map stuck", () => {
    const body = (JSON.parse(readFileSync(join(import.meta.dirname, "../../../contract/fixtures/tickets.json"), "utf8")) as { body: TicketRow[] }).body;
    const waiting = body.filter((r) => r.state === "waits for you");
    expect(waiting.length).toBeGreaterThan(0);
    const t = sidebarTree(state([item("repo/one#2", "running")]), body.filter((r) => r.state !== "ready" || r.map === "repo/one"), none);
    const maps = t.projects[0]?.maps ?? [];
    expect(maps.map((m) => [m.map, m.reason])).toEqual([["repo/one", ""], ["repo/two", "waits for you"]]);
    expect(maps[0]?.running).toBe(true);
  });

  it("marks a map whose tickets cannot run only for want of checks", () => {
    const sb = sidebarTree(s, tickets, none).projects.find((p) => p.project === "sb");
    const flags = Object.fromEntries((sb?.maps ?? []).map((m) => [m.map, m.noChecks]));
    expect(flags).toEqual({ "sb/busy": false, "sb/idle": false, "sb/nocheck": true, "sb/quiet": false });
  });

  it("counts a queued job in its project, not in a map", () => {
    const job = item("job-1", "queued", { kind: "job", project: "/work/sb" });
    const t = sidebarTree(state([job]), tickets, none);
    expect(t.projects.find((p) => p.project === "sb")?.queued).toBe(1);
    expect(t.all.queued).toBe(1);
  });

  it("leaves out the waiting morning close-off, and shows it while it runs", () => {
    const off = (st: "queued" | "running"): QueueItem => item("job-off", st, { kind: "job", project: "/hub/close-off", close_off: true });
    expect(sidebarTree(state([off("queued")]), tickets, none).projects.find((p) => p.project === "close-off")).toBeUndefined();
    expect(sidebarTree(state([off("running")]), tickets, none).projects.find((p) => p.project === "close-off")?.queued).toBe(1);
  });
});

describe("activeOnly", () => {
  it("keeps only the projects and maps with something queued or running", () => {
    const t = activeOnly(sidebarTree(s, tickets, none), none);
    expect(t.projects.map((p) => [p.project, p.maps.map((m) => m.map)])).toEqual([["other", ["other/live"]], ["sb", ["sb/busy"]]]);
    // the totals on Everything stay those of the whole board
    expect([t.all.canRun, t.all.queued]).toEqual([3, 3]);
  });

  it("keeps a picked quiet map, and a picked project with nothing in play", () => {
    const picked = { project: "sb", map: "sb/idle" };
    const t = activeOnly(sidebarTree(s, tickets, picked), picked);
    expect(t.projects.find((p) => p.project === "sb")?.maps.map((m) => m.map)).toEqual(["sb/busy", "sb/idle"]);
    const idle = state([]);
    const lone = { project: "sb", map: "" };
    expect(activeOnly(sidebarTree(idle, tickets, lone), lone).projects.map((p) => p.project)).toEqual(["sb"]);
    expect(activeOnly(sidebarTree(idle, tickets, none), none).projects).toEqual([]);
  });
});
