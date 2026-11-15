import { describe, expect, it } from "vitest";
import type { MapRoute, MapTicket } from "@sb-hub/contract";
import { dimmed, layoutMap, reachKeys, mapState, minutesOf, pickedState, stateCounts } from "./map.ts";

const t = (num: number, after: number[] = [], more: Partial<MapTicket> = {}): MapTicket => ({
  num, title: `Ticket ${String(num)}`, type: "task", status: "open", state: "ready", why: "", priority: null, tier: "sonnet", place: null,
  last_run: null, file: "", links: {} as MapTicket["links"], ...more,
  blocked_by: after.map((n) => ({ map: "sb/one", num: n, title: `Ticket ${String(n)}`, status: "open" })),
});
const route = (tickets: MapTicket[], checks = ["true"]): Pick<MapRoute, "map" | "checks" | "tickets"> => ({ map: "sb/one", checks, tickets });

// a diamond, a chain, a lone ticket and one that waits on another map's ticket and a whole map
const fixture = route([
  t(1, [], { state: "done", status: "resolved" }),
  t(2, [1], { status: "claimed", state: "claimed" }),
  t(3, [1], { place: 1 }),
  t(4, [2, 3]),
  t(5, [4], { state: "blocked" }),
  t(6),
  { ...t(7), blocked_by: [{ map: "other/map", num: 3, title: "Elsewhere", status: "open" }, { map: "third/map", num: null, title: "A whole map", status: "open" }] },
]);

describe("layoutMap", () => {
  const out = layoutMap(fixture);
  const at = new Map(out.nodes.map((n) => [n.id, n]));

  it("makes one node per ticket and a dashed-kind node per blocker elsewhere", () => {
    expect(out.nodes.filter((n) => n.ticket !== null)).toHaveLength(7);
    expect(out.nodes.filter((n) => n.ticket === null).map((n) => n.other).sort()).toEqual(["other/map", "third/map"]);
  });

  it("puts every ticket below all the tickets it comes after", () => {
    expect(out.edges).toHaveLength(7);
    for (const e of out.edges) {
      const from = at.get(e.from);
      const to = at.get(e.to);
      expect(from && to && to.y >= from.y + from.h).toBe(true);
    }
  });

  it("never lets two nodes overlap", () => {
    for (const a of out.nodes) {
      for (const b of out.nodes) {
        if (a === b) continue;
        const apart = a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
        expect(apart).toBe(true);
      }
    }
  });

  it("holds for the largest map: 58 tickets, 85 links", () => {
    const big = route(Array.from({ length: 58 }, (_, i) => t(i + 1, [i - 1, i - 3, i - 7].filter((n) => n >= 1 && n <= 58).slice(0, i % 3 === 0 ? 2 : 1))));
    const l = layoutMap(big);
    expect(l.nodes).toHaveLength(58);
    const m = new Map(l.nodes.map((n) => [n.id, n]));
    for (const e of l.edges) expect((m.get(e.to)?.y ?? 0) >= (m.get(e.from)?.y ?? 0) + 68).toBe(true);
  });
});

describe("mapState", () => {
  it("names one state, finished and claimed first", () => {
    expect(mapState(t(1, [], { state: "done", status: "resolved" }), true)).toBe("done");
    expect(mapState(t(1, [], { status: "claimed", state: "claimed", place: 2 }), true)).toBe("running");
    expect(mapState(t(1, [], { place: 2 }), true)).toBe("queued");
    expect(mapState(t(1, [], { state: "waits for you" }), true)).toBe("decision");
    expect(mapState(t(1, [], { state: "blocked" }), true)).toBe("stuck");
    expect(mapState(t(1), true)).toBe("can run");
    expect(mapState(t(1), false)).toBe("no checks");
    expect(mapState(t(1, [], { state: "out of scope", status: "out-of-scope" }), true)).toBe("out of scope");
  });
});

describe("the legend's counts and the picked state", () => {
  const nodes = layoutMap(fixture).nodes;

  it("counts the map's own tickets per state, not the blockers elsewhere", () => {
    const c = stateCounts(nodes);
    expect(c).toMatchObject({ done: 1, running: 1, queued: 1, "can run": 3, stuck: 1, decision: 0, "no checks": 0, "out of scope": 0 });
    expect(Object.values(c).reduce((a, b) => a + b, 0)).toBe(7);
  });

  it("reads a state from the page link and ignores anything else", () => {
    expect(pickedState("running")).toBe("running");
    expect(pickedState("can run")).toBe("can run");
    expect(pickedState("")).toBeNull();
    expect(pickedState("nonsense")).toBeNull();
  });

  it("dims every box of another state and every blocker elsewhere; nothing picked dims nothing", () => {
    expect(nodes.some((n) => dimmed(n, null))).toBe(false);
    const lit = nodes.filter((n) => !dimmed(n, "running"));
    expect(lit.map((n) => n.id)).toEqual(["2"]);
    expect(nodes.filter((n) => n.ticket === null).every((n) => dimmed(n, "stuck"))).toBe(true);
  });

  it("gives a run's whole minutes so far, and none without a start", () => {
    expect(minutesOf(1000, 1000 + 12 * 60 + 59)).toBe(12);
    expect(minutesOf(1000, 990)).toBe(0);
    expect(minutesOf(null, 1000)).toBeNull();
    expect(minutesOf(undefined, 1000)).toBeNull();
  });
});

describe("reachKeys: tick everything this comes after / that comes after this", () => {
  const out = layoutMap(fixture);
  it("walks back through every blocker, the node itself included", () => {
    expect(reachKeys(out, "sb/one", "5", "before").sort()).toEqual(["sb/one#1", "sb/one#2", "sb/one#3", "sb/one#4", "sb/one#5"]);
    expect(reachKeys(out, "sb/one", "3", "before").sort()).toEqual(["sb/one#1", "sb/one#3"]);
  });
  it("walks forward through every ticket that follows", () => {
    expect(reachKeys(out, "sb/one", "1", "after").sort()).toEqual(["sb/one#1", "sb/one#2", "sb/one#3", "sb/one#4", "sb/one#5"]);
    expect(reachKeys(out, "sb/one", "4", "after").sort()).toEqual(["sb/one#4", "sb/one#5"]);
  });
  it("is just the node when nothing is on that side, and leaves out blockers in other maps", () => {
    expect(reachKeys(out, "sb/one", "6", "before")).toEqual(["sb/one#6"]);
    expect(reachKeys(out, "sb/one", "6", "after")).toEqual(["sb/one#6"]);
    expect(reachKeys(out, "sb/one", "7", "before")).toEqual(["sb/one#7"]);
    expect(reachKeys(out, "sb/one", "x:other/map#3", "after")).toEqual(["sb/one#7"]);
  });
});
