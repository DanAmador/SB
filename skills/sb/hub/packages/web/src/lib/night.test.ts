import { describe, expect, it } from "vitest";
import type { QueueItem, State, TicketRow } from "@sb-hub/contract";
import { ticketIndex } from "./board.ts";
import { countsLine, nightBlocks, nightLine } from "./night.ts";

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
