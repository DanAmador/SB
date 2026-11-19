import { RunsPage, type Night, type QueueItem, type Run } from "@sb-hub/contract";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { dayStart } from "./board.ts";
import { choices, clampZoom, filterItems, filterRuns, groupByDay, itemOutcome, minutesOf, nightWords, rangeOf, searchLog, sinceOf, sortNights, stepIndex, type Filters } from "./history.ts";
import { readLink, writeLink } from "./link.ts";

const NOW = new Date(2026, 10, 13, 15, 0).getTime() / 1000;
const none: Filters = { q: "", outcome: "", pictures: false, account: "", model: "" };
const links = { ticket: null, map: null, board: null, report: null, log: null };
const run = (key: string, more: Partial<Run> = {}): Run => ({
  key, title: `Ticket ${key}`, project: key.split("/")[0] ?? "", map: key.replace(/#\d+$/, ""), outcome: "done", reason: "", account: "main", model: "sonnet",
  started: NOW - 3600, ended: NOW - 3000, commit: "abc1234def", tries: 1, refused: 0, refused_lines: [], pictures: [], links, ...more,
});
const runs = [
  run("a/one#1", { title: "Draw the header", pictures: ["x.png"] }),
  run("a/one#2", { title: "Fix the sheet", outcome: "failed", reason: "ended without a commit", commit: null, account: "spare", model: "opus" }),
  run("a/two#3", { title: "Pick fonts", outcome: "skipped", reason: "someone else had claimed it", ended: NOW - 86400 }),
  run("b/site#4", { title: "Write copy", outcome: "unknown", commit: "ffff000", account: null, model: null, ended: NOW - 86400 * 3 }),
];

describe("the run listing the hub serves", () => {
  it("parses the fixture the hub wrote, newest first", () => {
    const file = JSON.parse(readFileSync(join(import.meta.dirname, "../../../contract/fixtures/runs.json"), "utf8")) as { body: unknown };
    const page = RunsPage.parse(file.body);
    expect(page.runs.length).toBeGreaterThan(1);
    const ends = page.runs.map((r) => r.ended ?? 0);
    expect(ends).toEqual([...ends].sort((a, b) => b - a));
    expect(page.runs.map((r) => r.outcome)).toContain("failed");
  });
});

describe("filters", () => {
  const keys = (f: Partial<Filters>, scope = { project: "", map: "" }): string[] => filterRuns(runs, { ...none, ...f }, scope).map((r) => r.key);
  it("keeps everything with no filter", () => {
    expect(keys({})).toHaveLength(4);
  });
  it("searches titles, reasons and commits, every word", () => {
    expect(keys({ q: "header" })).toEqual(["a/one#1"]);
    expect(keys({ q: "without commit" })).toEqual(["a/one#2"]);
    expect(keys({ q: "claimed" })).toEqual(["a/two#3"]);
    expect(keys({ q: "ffff0" })).toEqual(["b/site#4"]);
    expect(keys({ q: "header nothing" })).toEqual([]);
  });
  it("chips: outcome, has pictures, account, model", () => {
    expect(keys({ outcome: "failed" })).toEqual(["a/one#2"]);
    expect(keys({ pictures: true })).toEqual(["a/one#1"]);
    expect(keys({ account: "spare" })).toEqual(["a/one#2"]);
    expect(keys({ model: "opus" })).toEqual(["a/one#2"]);
    expect(keys({ outcome: "done", account: "spare" })).toEqual([]);
  });
  it("the sidebar's project and map apply", () => {
    expect(keys({}, { project: "a", map: "" })).toEqual(["a/one#1", "a/one#2", "a/two#3"]);
    expect(keys({}, { project: "a", map: "a/two" })).toEqual(["a/two#3"]);
    expect(keys({}, { project: "b", map: "" })).toEqual(["b/site#4"]);
  });
  it("offers the accounts and models that appear", () => {
    expect(choices(runs)).toEqual({ accounts: ["main", "spare"], models: ["opus", "sonnet"] });
  });
});

describe("time range", () => {
  it("today starts at local midnight, 7 days six days before it, all at 0", () => {
    expect(sinceOf("today", NOW)).toBe(dayStart(NOW));
    expect(sinceOf("7d", NOW)).toBe(new Date(2026, 10, 7).getTime() / 1000);
    expect(sinceOf("30d", NOW)).toBe(new Date(2026, 9, 15).getTime() / 1000);
    expect(sinceOf("all", NOW)).toBe(0);
  });
  it("an unknown range is the 7 day default", () => {
    expect(rangeOf("")).toBe("7d");
    expect(rangeOf("bogus")).toBe("7d");
    expect(rangeOf("30d")).toBe("30d");
  });
});

describe("grouping and numbers", () => {
  it("groups by the day a run ended", () => {
    const days = groupByDay(runs, NOW);
    expect(days.map((d) => d.label).slice(0, 2)).toEqual(["Today", "Yesterday"]);
    expect(days.map((d) => d.runs.length)).toEqual([2, 1, 1]);
  });
  it("minutes, log search, steps and zoom", () => {
    expect(minutesOf({ started: 0, ended: 600 })).toBe(10);
    expect(minutesOf({ started: null, ended: 600 })).toBeNull();
    expect(searchLog("a one\nb two\nc one two", "one two")).toEqual({ lines: ["c one two"], found: 1 });
    expect(searchLog("a\nb", "")).toEqual({ lines: ["a", "b"], found: 0 });
    expect(stepIndex(0, -1, 3)).toBe(2);
    expect(stepIndex(2, 1, 3)).toBe(0);
    expect(clampZoom(0.2)).toBe(1);
    expect(clampZoom(99)).toBe(6);
  });
  it("the open run and filters live in the page link", () => {
    const link = readLink("?view=history&run=a%2Fone%231&pic=x.png&range=30d&out=failed&pics=1&acct=main&model=opus&q=rope");
    expect(link.view).toBe("history");
    expect(link.run).toBe("a/one#1");
    expect(readLink(writeLink(link))).toEqual(link);
  });
});

describe("History by run", () => {
  const counts = (c: Partial<Night["counts"]>): Night["counts"] => ({ items: 0, queued: 0, running: 0, done: 0, failed: 0, skipped: 0, not_reached: 0, ...c });
  const night = (id: string, started: number, more: Partial<Night> = {}): Night => ({ id, name: id, started, by: null, state: "ended", ended: started + 100, how: "finished", not_reached: [], drain: true, counts: counts({}), ...more });
  it("lists runs newest first, whatever order the hub gave", () => {
    const list = [night("a", 100), night("c", 300, { state: "live", ended: null, how: null }), night("b", 200)];
    expect(sortNights(list).map((n) => n.id)).toEqual(["c", "b", "a"]);
  });
  it("says each run's counts: done, fell short, not reached, no word for a zero", () => {
    expect(nightWords(counts({ done: 5, failed: 1, not_reached: 2 }))).toBe("5 done · 1 fell short · 2 not reached");
    expect(nightWords(counts({ done: 3 }))).toBe("3 done");
    expect(nightWords(counts({}))).toBe("nothing finished");
  });
  it("filters the tickets inside one run by outcome, search, pictures, account and model", () => {
    const it = (key: string, state: QueueItem["state"], more: Record<string, unknown> = {}): QueueItem =>
      ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, ...more }) as unknown as QueueItem;
    const items = [it("a/m#1", "done", { runner: "main", model: "opus", media: ["x.png"] }), it("a/m#2", "failed", { runner: "spare" }), it("a/m#3", "skipped")];
    const f = { q: "", outcome: "" as const, pictures: false, account: "", model: "" };
    const title = (i: QueueItem): string => `Title ${i.key}`;
    expect(items.map(itemOutcome)).toEqual(["done", "fell short", "stopped"]);
    expect(filterItems(items, { ...f, outcome: "failed" }, title).map((i) => i.key)).toEqual(["a/m#2"]);
    expect(filterItems(items, { ...f, pictures: true }, title).map((i) => i.key)).toEqual(["a/m#1"]);
    expect(filterItems(items, { ...f, account: "spare" }, title).map((i) => i.key)).toEqual(["a/m#2"]);
    expect(filterItems(items, { ...f, model: "opus" }, title).map((i) => i.key)).toEqual(["a/m#1"]);
    expect(filterItems(items, { ...f, q: "m#3" }, title).map((i) => i.key)).toEqual(["a/m#3"]);
  });
});
