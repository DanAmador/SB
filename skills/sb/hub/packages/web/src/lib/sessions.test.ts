import { describe, expect, it } from "vitest";
import type { AgentRow, QueueItem, State, Trail, TrailAction } from "@sb-hub/contract";
import { splitAgents, ticketIndex } from "./board.ts";
import { actionWords, boardOf, entryOf, IDLE, mapSvg, sessionCards, stationsOf } from "./sessions.ts";

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

describe("a worker whose run ended, or that went silent", () => {
  const NOW = 1_800_000_000;
  const row = (agent: string, more: Partial<AgentRow>): AgentRow => ({ agent, role: "worker", parent: "chat-1", state: "working", at: NOW - 10, ...more });
  const cards = (agents: Record<string, AgentRow>, items: QueueItem[] = [], now = NOW) => {
    const state = { agents, queue: { items, agent: null }, now } as unknown as State;
    return sessionCards(state, ticketIndex([], state), splitAgents(state));
  };
  const chat = row("chat-1", { role: undefined, parent: undefined, joined: { night: "n1", role: "integrator" as const, at: NOW - 60 } });
  // a worker the queue knows nothing of: its item was cleared, or its chat is gone
  const helper = (more: Partial<AgentRow> = {}): AgentRow => row("helper-1", { parent: "queue", ...more });
  const live = (c: ReturnType<typeof cards>): string[] => c.filter((x) => !x.idle).map((x) => x.id);

  it("is idle once the queue ended it", () => {
    const c = cards({ "r#1": row("r#1", { parent: "queue", state: "done" }), "r#2": row("r#2", { parent: "queue" }) }, [{ key: "r#2", state: "running" } as QueueItem]);
    expect(live(c)).toEqual(["r#2"]);
    expect(c.map((x) => x.id)).toEqual(["r#2", "r#1"]);
  });

  it("with no queue item reads 'silent since' after 30 minutes, sorts last and is out of the live count", () => {
    const at = NOW - IDLE - 60;
    const c = cards({ "chat-1": chat, "helper-1": helper({ at }) });
    const h = c.find((x) => x.id === "helper-1");
    expect(h).toMatchObject({ idle: true });
    expect(h?.silentSince).toMatch(/^\d\d:\d\d$/);
    expect(c.at(-1)?.id).toBe("helper-1");
    expect(live(c)).toEqual(["chat-1"]);
  });

  it("is live again on a fresh event", () => {
    const c = cards({ "chat-1": chat, "helper-1": helper({ at: NOW - 5 }) });
    expect(live(c).sort()).toEqual(["chat-1", "helper-1"]);
    expect(c.find((x) => x.id === "helper-1")?.silentSince).toBeNull();
  });

  it("with a queue item stays as the queue says", () => {
    const c = cards({ "r#1": row("r#1", { parent: "queue", at: NOW - IDLE - 60 }) }, [{ key: "r#1", state: "running" } as QueueItem]);
    expect(live(c)).toEqual(["r#1"]);
  });
});

describe("actionWords", () => {
  it("says what the newest tool call did", () => {
    expect(actionWords([a("Read", "a.ts"), a("Bash", "pnpm typecheck", { end: null, ok: null })])).toBe("Bash: pnpm typecheck");
  });
  it("skips a subagent's run and gives the bare tool when it has no label", () => {
    expect(actionWords([a("Bash", "ls"), a("Agent", "check", { sub: true })])).toBe("Bash: ls");
    expect(actionWords([a("Bash", "")])).toBe("Bash");
    expect(actionWords([])).toBeNull();
  });
});
