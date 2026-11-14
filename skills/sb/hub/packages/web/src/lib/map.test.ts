import { describe, expect, it } from "vitest";
import type { MapRoute, MapTicket } from "@sb-hub/contract";
import { layoutMap, mapState } from "./map.ts";

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
