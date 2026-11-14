import { describe, expect, it } from "vitest";
import type { Trail, TrailAction } from "@sb-hub/contract";
import { boardOf, entryOf, mapSvg, stationsOf } from "./sessions.ts";

const a = (tool: string, label: string, more: Partial<TrailAction> = {}): TrailAction => ({ tool, label, start: 1000, end: 1001, ok: true, sub: false, ...more });
const trail = (actions: TrailAction[], ctx: number | null = null): Trail => ({ agent: "demo/board#5", ctx, ended: null, actions });

describe("a trail becomes stations", () => {
  const t = trail([
    a("Read", "src/Board.tsx"),
    a("Edit", "src/Header.tsx"),
    a("Bash", "pnpm test", { ok: false }),
    a("Bash", "curl https://example.com", { start: 1002, end: null, ok: null }),
    a("scout", "check the tests", { sub: true, end: null, ok: null }),
    a("prompt", "go"),
    a("Skill", "wikibrain"),
  ]);

  it("puts each tool at its station and counts them", () => {
    const s = stationsOf(t);
    expect(s.find((x) => x.station === "files")?.count).toBe(2);
    expect(s.find((x) => x.station === "shell")?.count).toBe(1);
    expect(s.find((x) => x.station === "web")?.count).toBe(1);
    expect(s.find((x) => x.station === "agents")?.count).toBe(1);
    expect(s.find((x) => x.station === "skills")?.count).toBe(1);
    expect(s.find((x) => x.station === "you")?.count).toBe(1);
  });

  it("marks a failure and a running call", () => {
    const s = stationsOf(t);
    expect(s.find((x) => x.station === "shell")?.faults).toBe(1);
    expect(s.find((x) => x.station === "web")?.running).toBe(true);
    expect(s.find((x) => x.station === "files")?.running).toBe(false);
  });

  it("reads a subagent's run as the agents station, and a prompt as a signal from you", () => {
    expect(entryOf(a("scout", "x", { sub: true }), 0)).toMatchObject({ station: "agents", from: "core" });
    expect(entryOf(a("prompt", "x"), 0)).toMatchObject({ station: "you", from: "inbound" });
  });

  it("carries the context used and the subagents still running", () => {
    expect(boardOf(trail([a("scout", "x", { sub: true, end: null, ok: null })], 72))).toMatchObject({ context: 72, agents: ["scout"] });
    expect(boardOf(trail([])).context).toBeUndefined();
  });

  it("draws it with lot-map: one SVG, and the dark and light palettes differ", () => {
    const dark = mapSvg(t, 1003, true);
    const light = mapSvg(t, 1003, false);
    expect(dark.startsWith("<svg")).toBe(true);
    expect(dark).not.toBe(light);
    expect(mapSvg(trail([]), 1003, true)).toContain("<svg");
  });
});
