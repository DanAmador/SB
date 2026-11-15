import { beforeEach, describe, expect, it } from "vitest";
import type { MapTicket, TicketRow } from "@sb-hub/contract";
import { chipCounts, filterRows, liveOf, nextSort, pageOf, PAGE, rowOfMapTicket, rowOfTicket, sortRows, ticketIndex, type TableRow } from "./board.ts";
import { applies, between, clearSelection, clickRow, selected, split, tick } from "./select.ts";

const NO_LINKS = { ticket: null, map: null, board: null, report: null, log: null };
const row = (num: number, more: Partial<TableRow> = {}): TableRow => ({
  key: `a/one#${String(num)}`, map: "a/one", mapTitle: "One", num, title: `Ticket ${String(num)}`, type: "task", state: "can run now", place: null, priority: null, tier: "sonnet", links: undefined, ...more,
});
const rows: TableRow[] = [
  row(1, { state: "can run now", priority: "A" }),
  row(2, { state: "can run after another", priority: "B", title: "Beta ticket" }),
  row(3, { state: "queued", place: 2, type: "grilling" }),
  row(4, { state: "queued", place: 1, priority: "A", tier: "opus" }),
  row(5, { state: "done", priority: "C", mapTitle: "Other map", map: "b/two", key: "b/two#5" }),
];
const none = { q: "", state: "", type: "", priority: "" };

describe("filterRows", () => {
  it("keeps everything with no filter", () => {
    expect(filterRows(rows, none)).toHaveLength(5);
  });
  it("narrows by state, type and priority together", () => {
    expect(filterRows(rows, { ...none, state: "queued" }).map((r) => r.num)).toEqual([3, 4]);
    expect(filterRows(rows, { ...none, state: "queued", type: "grilling" }).map((r) => r.num)).toEqual([3]);
    expect(filterRows(rows, { ...none, priority: "A" }).map((r) => r.num)).toEqual([1, 4]);
    expect(filterRows(rows, { ...none, priority: "none" }).map((r) => r.num)).toEqual([3]);
  });
  it("matches every word over map, title and number", () => {
    expect(filterRows(rows, { ...none, q: "other map" }).map((r) => r.num)).toEqual([5]);
    expect(filterRows(rows, { ...none, q: "beta 2" }).map((r) => r.num)).toEqual([2]);
    expect(filterRows(rows, { ...none, q: "zzz" })).toEqual([]);
  });
});

describe("chipCounts", () => {
  it("counts a facet under the words and the other facets, not its own choice", () => {
    const c = chipCounts(rows, { ...none, state: "queued" });
    expect(c.state.get("queued")).toBe(2);
    expect(c.state.get("can run now")).toBe(1);
    expect(c.type.get("task")).toBe(1);
    expect(c.type.get("grilling")).toBe(1);
    expect(c.priority.get("A")).toBe(1);
  });
  it("sums to the rows under the other filters", () => {
    const c = chipCounts(rows, { ...none, q: "ticket" });
    expect([...c.state.values()].reduce((a, b) => a + b, 0)).toBe(5);
  });
});

describe("sortRows and nextSort", () => {
  it("sorts by state in the chips' order, the queue's place within queued", () => {
    expect(sortRows(rows, "state").map((r) => r.num)).toEqual([1, 2, 4, 3, 5]);
    expect(sortRows(rows, "-state").map((r) => r.num)).toEqual([5, 3, 4, 2, 1]);
  });
  it("sorts priority with none last, ties in the map's order", () => {
    expect(sortRows(rows, "priority").map((r) => r.num)).toEqual([1, 4, 2, 5, 3]);
  });
  it("sorts titles case-insensitively and leaves the order alone with no sort", () => {
    expect(sortRows(rows, "title").map((r) => r.num)).toEqual([2, 1, 3, 4, 5].sort((a, b) => (rows[a - 1]?.title ?? "").toLowerCase().localeCompare((rows[b - 1]?.title ?? "").toLowerCase(), undefined, { numeric: true })));
    expect(sortRows(rows, "").map((r) => r.num)).toEqual([1, 2, 3, 4, 5]);
    expect(sortRows(rows, "bogus").map((r) => r.num)).toEqual([1, 2, 3, 4, 5]);
  });
  it("a click goes ascending, descending, then back", () => {
    expect(nextSort("", "tier")).toBe("tier");
    expect(nextSort("tier", "tier")).toBe("-tier");
    expect(nextSort("-tier", "tier")).toBe("");
    expect(nextSort("tier", "type")).toBe("type");
  });
});

describe("pageOf", () => {
  const many = Array.from({ length: PAGE * 2 + 5 }, (_, n) => n);
  it("pages after 200 rows and clamps", () => {
    expect(pageOf(many.slice(0, PAGE), 1).pages).toBe(1);
    expect(pageOf(many, 1)).toMatchObject({ pages: 3, page: 1 });
    expect(pageOf(many, 3).rows).toHaveLength(5);
    expect(pageOf(many, 9).page).toBe(3);
    expect(pageOf([], 0)).toEqual({ rows: [], page: 1, pages: 1 });
  });
});

const tk = (num: number, more: Partial<TicketRow> = {}): TicketRow => ({
  map: "a/one", num, title: `T${String(num)}`, why: "", type: "task", status: "open", priority: null, blocked_by: [], blocked_by_open: [], paths: [], tier: "sonnet",
  check: "tests", has_done_when: true, done_when: "x", question: "", out: "", checks: ["true"], repo: "/r", file: "", map_title: "One", map_order: 1, claimed_by: null, queued: false,
  state: "ready", reason: "", links: NO_LINKS, ...more,
});
describe("the state words", () => {
  const list = [tk(1), tk(2, { state: "blocked", blocked_by_open: [1] }), tk(3, { state: "blocked", blocked_by_open: [9] }), tk(4, { state: "waits for you" }), tk(5, { status: "claimed", state: "claimed" }), tk(6, { checks: [] }), tk(7), tk(8)];
  const queue = { items: [{ key: "a/one#7", state: "queued" }, { key: "a/one#8", state: "running" }] };
  const st = { queue } as never;
  const ix = ticketIndex(list, st);
  const live = liveOf(st);
  it("splits can run now from can run after another, and names the rest", () => {
    expect(list.map((t) => rowOfTicket(t, ix, live).state)).toEqual(["can run now", "can run after another", "stuck behind another", "needs a decision", "claimed", "no checks", "queued", "running"]);
    expect(rowOfTicket(tk(7), ix, live).place).toBe(1);
  });
  it("reads a map's finished and left-out tickets from their status", () => {
    const mt = (more: Partial<MapTicket>): MapTicket => ({ num: 1, title: "T", type: "task", status: "open", state: "ready", why: "", priority: null, tier: "sonnet", place: null, last_run: null, blocked_by: [], file: "", links: NO_LINKS, ...more });
    expect(rowOfMapTicket("a/one", "One", true, mt({ status: "resolved", state: "done" }), ix, live).state).toBe("done");
    expect(rowOfMapTicket("a/one", "One", true, mt({ status: "out-of-scope", state: "out of scope" }), ix, live).state).toBe("out of scope");
    expect(rowOfMapTicket("a/one", "One", true, mt({ num: 77 }), ix, live).state).toBe("can run now");
    expect(rowOfMapTicket("a/one", "One", false, mt({ num: 77 }), ix, live).state).toBe("no checks");
  });
});

describe("the selection", () => {
  beforeEach(clearSelection);
  const order = ["k1", "k2", "k3", "k4", "k5"];
  it("between gives the range either way round", () => {
    expect(between(order, "k2", "k4")).toEqual(["k2", "k3", "k4"]);
    expect(between(order, "k4", "k2")).toEqual(["k2", "k3", "k4"]);
    expect(between(order, null, "k3")).toEqual(["k3"]);
    expect(between(order, "gone", "k3")).toEqual(["k3"]);
  });
  it("a click flips a row and Shift ticks the range from the last click", () => {
    clickRow(order, "k2", false);
    clickRow(order, "k4", true);
    expect([...selected()].sort()).toEqual(["k2", "k3", "k4"]);
    clickRow(order, "k3", false);
    expect([...selected()].sort()).toEqual(["k2", "k4"]);
    tick(["k1"], true);
    expect(selected().has("k1")).toBe(true);
  });
  it("splits ticked rows into those an action applies to and those it skips", () => {
    const ticked = [row(1), row(2, { state: "can run after another" }), row(3, { state: "queued" }), row(5, { state: "done" })];
    expect(split("queue", ticked).apply.map((r) => r.num)).toEqual([1, 2]);
    expect(split("queue", ticked).skip.map((r) => r.num)).toEqual([3, 5]);
    expect(split("unqueue", ticked).apply.map((r) => r.num)).toEqual([3]);
    expect(split("drop", ticked).apply.map((r) => r.num)).toEqual([1, 2]);
    expect(split("tier", ticked).apply.map((r) => r.num)).toEqual([1, 2, 3]);
    expect(split("comment", ticked).skip).toEqual([]);
    expect(applies("done", row(9, { state: "running" }))).toBe(false);
  });
});
