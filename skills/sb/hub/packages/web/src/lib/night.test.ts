import { describe, expect, it } from "vitest";
import type { QueueItem, State, TicketRow } from "@sb-hub/contract";
import { ticketIndex } from "./board.ts";
import { countsLine, healthOf, nightBlocks, nightLine, pairNight, QUEUE_HEAD } from "./night.ts";
import { helperCards, sessionCards } from "./sessions.ts";

const NOW = 1_800_000_000;
const item = (key: string, state: QueueItem["state"], more: Record<string, unknown> = {}): QueueItem =>
  ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, ...more }) as unknown as QueueItem;
const ticket = (map: string, num: number, order: number): TicketRow => ({ map, num, title: `T${String(num)} of ${map}`, map_title: `Map ${map}`, map_order: order, state: "ready" }) as unknown as TicketRow;
const state = (items: QueueItem[], maps: string[]): State => ({ now: NOW, queue: { version: 1, items, maps, paused: false, agent: "main", stop_at: null }, installed: {} }) as unknown as State;

describe("nightBlocks", () => {
  // two maps: b is first in the queue's map order though a comes first in the vault
  const items = [
    item("p/a#1", "done", { ended: NOW - 100 }),
    item("p/a#2", "running", { started: NOW - 60 }),
    item("p/b#1", "failed", { ended: NOW - 50 }),
    item("p/b#2", "queued"),
    item("p/b#3", "queued"),
    item("p/a#3", "queued"),
    item("p/old#1", "done", { ended: NOW - 3 * 86400 }),
  ];
  const tickets = [ticket("p/a", 1, 1), ticket("p/b", 1, 2), ticket("p/old", 1, 3)];
  const night = nightBlocks(state(items, ["p/b", "p/a"]), ticketIndex(tickets, { queue: { items } } as never));

  it("makes one block per map with something live or ended today, in the queue's map order", () => {
    expect(night.blocks.map((b) => b.map)).toEqual(["p/b", "p/a"]);
    expect(night.blocks.map((b) => b.title)).toEqual(["Map p/b", "Map p/a"]);
  });
  it("counts each block and says it in one line", () => {
    expect(night.blocks.map((b) => b.line)).toEqual(["2 next · 1 fell short", "1 done · 1 running · 1 next"]);
    expect(nightLine(night)).toBe("1 running · 3 next · 1 done · 1 fell short");
    expect(countsLine({ done: 3, running: 1, checking: 0, recheck: 0, next: 4, short: 1, stopped: 0 })).toBe("3 done · 1 running · 4 next · 1 fell short");
  });
  it("lists a block's rows in run order with the right marks, and the place in the whole line", () => {
    const a = night.blocks[1];
    expect(a?.rows.map((r) => [r.item.key, r.mark, r.place])).toEqual([["p/a#1", "done", null], ["p/a#2", "running", null], ["p/a#3", "next", 3]]);
    expect(night.blocks[0]?.rows.map((r) => [r.item.key, r.mark])).toEqual([["p/b#1", "short"], ["p/b#2", "next"], ["p/b#3", "next"]]);
  });
  it("opens the blocks with something running or fallen short, and no other", () => {
    expect(night.blocks.map((b) => b.open)).toEqual([true, true]);
    expect(nightBlocks(state([item("p/a#3", "queued")], ["p/a"]), ticketIndex(tickets, { queue: { items } } as never)).blocks[0]?.open).toBe(false);
  });
  it("puts jobs in a block called Jobs, last", () => {
    const job = { ...item("job:1", "queued"), kind: "job", title: "Close off", project: "/w/p", repo: "/w/p", name: "close" } as unknown as QueueItem;
    const n = nightBlocks(state([...items, job], ["p/b", "p/a"]), ticketIndex(tickets, { queue: { items } } as never));
    expect(n.blocks.at(-1)?.title).toBe("Jobs");
  });
});

describe("pairNight: who is on each ticket", () => {
  const agent = (id: string, more: Record<string, unknown>): [string, unknown] => [id, { agent: id, project: "/w/p", state: "working", at: NOW - 30, ...more }];
  const items = [
    item("p/a#1", "running", { started: NOW - 600, runner: "main" }),
    item("p/a#2", "running", { started: NOW - 1200, runner: "main" }),
    item("p/a#3", "done", { ended: NOW - 100 }),
    item("p/b#1", "queued"),
  ];
  const st = {
    ...state(items, ["p/a", "p/b"]),
    aliases: {},
    charge: { "p/a": "c-1" },
    agents: Object.fromEntries([
      agent("c-1", { title: "Charting a", map: "p/a", at: NOW - 240 }),
      agent("c-2", { title: "Loose chat", state: "your turn" }),
      agent("p/a#1", { role: "worker", parent: "queue", note: "running tests", at: NOW - 20 }),
      agent("p/a#2", { role: "worker", parent: "queue", note: "reading", at: NOW - 400 }),
      agent("p/a#3", { role: "worker", parent: "queue", state: "done" }),
      agent("h-1", { title: "Scout", role: "worker", parent: "c-1" }),
      agent("h-2", { title: "Notes", role: "worker", parent: "c-2" }),
    ]),
  } as unknown as State;
  const tickets = [ticket("p/a", 1, 1), ticket("p/b", 1, 2)];
  const ix = ticketIndex(tickets, st);
  const night = nightBlocks(st, ix);
  const pair = pairNight(st, night, sessionCards(st, ix), helperCards(st, ix));

  it("names the session in charge in the head, or says the queue runs the map", () => {
    expect(pair.maps.get("p/a")?.charge?.id).toBe("c-1");
    expect(pair.maps.get("p/a")?.head).toBe("Charting a · working · quiet 4m");
    expect(pair.maps.get("p/b")?.charge).toBeNull();
    expect(pair.maps.get("p/b")?.head).toBe(QUEUE_HEAD);
  });
  it("pairs each row with its worker and tells live, silent and ended apart", () => {
    const w = pair.maps.get("p/a")?.workers;
    expect([...(w?.keys() ?? [])].sort()).toEqual(["p/a#1", "p/a#2", "p/a#3"]);
    expect(["p/a#1", "p/a#2", "p/a#3"].map((k) => healthOf(w?.get(k) as never))).toEqual(["live", "silent", "ended"]);
    expect(pair.maps.get("p/b")?.workers.size).toBe(0);
  });
  it("lists under Helpers what the session in charge started, and leaves the queue's workers out of it", () => {
    expect(pair.maps.get("p/a")?.helpers.map((h) => h.id)).toEqual(["h-1"]);
    expect(pair.maps.get("p/b")?.helpers).toEqual([]);
  });
  it("puts chats in charge of no map under Other chats with their helpers, and counts the live ones", () => {
    expect(pair.chats.map((c) => [c.chat.id, c.helpers.map((h) => h.id)])).toEqual([["c-2", ["h-2"]]]);
    expect(pair.liveChats).toBe(1);
  });
});
