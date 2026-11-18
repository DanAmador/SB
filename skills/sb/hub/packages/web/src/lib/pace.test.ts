import { describe, expect, it } from "vitest";
import { State, type Installed, type QueueItem } from "@sb-hub/contract";
import { GATE_7D, WEEK_SECONDS, accountPace, costOf, poolPace, weekPace } from "./pace.ts";

const NOW = 1_800_000_000;
const NO_LINKS = { ticket: null, map: null, board: null, report: null, log: null };
const HOUR = 3600;

const item = (key: string, state: QueueItem["state"], more: Partial<QueueItem> = {}): QueueItem =>
  ({ key, kind: "ticket", agent: null, state, note: "", commit: null, tries: 0, started: null, ended: null, links: NO_LINKS, ...more }) as QueueItem;

const account = (more: Partial<Installed> = {}): Installed => ({ kind: "claude", dir: null, model: null, limited_until: null, ...more });

const usage = (five: number, week: number | null = 0.2, more: Partial<NonNullable<Installed["usage"]>> = {}): NonNullable<Installed["usage"]> => ({
  five_hour: five,
  five_hour_resets: NOW + 2 * HOUR,
  seven_day: week,
  seven_day_resets: NOW + 5 * 86400,
  at: NOW - 60,
  ...more,
});

function state(installed: Record<string, Installed>, items: QueueItem[] = [], agents: string[] = ["a"]): State {
  return State.parse({
    agents: {},
    locks: {},
    questions: {},
    aliases: {},
    messages: {},
    installed,
    seen: [],
    now: NOW,
    providers: {},
    queue: { version: 1, seeded: true, paused: false, agent: null, agents, items },
  });
}

describe("a ticket's cost", () => {
  it("is the default until one is learned, then the learned one, never under a third of the default", () => {
    expect(costOf(account(), "sonnet")).toBe(0.15);
    expect(costOf(account(), "opus")).toBe(0.3);
    expect(costOf(account({ costs: { sonnet: { avg: 0.08, n: 3 } } }), "sonnet")).toBe(0.08);
    expect(costOf(account({ costs: { sonnet: { avg: 0.001, n: 3 } } }), "sonnet")).toBeCloseTo(0.05);
  });
  it("is taken from the other tier when only that one is learned: opus twice sonnet", () => {
    expect(costOf(account({ costs: { sonnet: { avg: 0.08, n: 3 } } }), "opus")).toBeCloseTo(0.16);
    expect(costOf(account({ costs: { opus: { avg: 0.2, n: 3 } } }), "sonnet")).toBeCloseTo(0.1);
  });
});

describe("an account's five hours", () => {
  it("splits into used, held by running work and free under the 90% gate", () => {
    const e = account({ usage: usage(0.22), costs: { sonnet: { avg: 0.06, n: 4 }, opus: { avg: 0.12, n: 4 } } });
    const s = state({ a: e }, [
      item("m#1", "running", { runner: "a", model: "opus" }),
      item("m#2", "running", { runner: "a", model: "sonnet" }),
      item("m#3", "running", { runner: "b", model: "opus" }),
      item("m#4", "queued"),
    ]);
    const p = accountPace("a", e, s);
    expect(p.running).toBe(2);
    expect(p.five?.used).toBe(0.22);
    expect(p.five?.held).toBeCloseTo(0.18);
    expect(p.five?.free).toBeCloseTo(0.5);
    expect(p.five?.fits).toEqual({ sonnet: 8, opus: 4 });
    expect(p.five?.resets).toBe(NOW + 2 * HOUR);
    expect(p.five?.old).toBe(false);
  });
  it("is empty once the window it was read in has ended", () => {
    const e = account({ usage: usage(0.7, 0.2, { five_hour_resets: NOW - 60 }) });
    const p = accountPace("a", e, state({ a: e }));
    expect(p.five?.used).toBe(0);
    expect(p.five?.resets).toBeNull();
    expect(p.five?.free).toBeCloseTo(0.9);
  });
  it("never shows less than nothing free, and marks an old reading", () => {
    const e = account({ usage: usage(0.93, 0.2, { at: NOW - 2 * HOUR }) });
    const p = accountPace("a", e, state({ a: e }));
    expect(p.five?.free).toBe(0);
    expect(p.five?.fits).toEqual({ sonnet: 0, opus: 0 });
    expect(p.five?.old).toBe(true);
  });
  it("has no reading for an account never read, or an agy one", () => {
    const s = state({ a: account(), g: account({ kind: "agy" }) });
    expect(accountPace("a", account(), s).five).toBeNull();
    expect(accountPace("g", account({ kind: "agy", usage: usage(0.3) }), s).five).toBeNull();
    expect(accountPace("g", account({ kind: "agy" }), s).inPool).toBe(false);
  });
  it("shows a Codex account's reading from its session files", () => {
    const e = account({ kind: "codex", usage: usage(0.04, 0.21) });
    const p = accountPace("c", e, state({ c: e }));
    expect(p.five?.used).toBe(0.04);
    expect(p.week).not.toBeNull();
  });
});

describe("an account's week", () => {
  const resets = NOW + 0.7 * WEEK_SECONDS; // 30% of the week has passed
  it("names when it reaches its stop at the rate so far", () => {
    const w = weekPace(0.4, resets, NOW);
    expect(w?.gone).toBeCloseTo(0.3);
    expect(w?.even).toBeCloseTo(0.3 * GATE_7D);
    // 40% in 30% of the week reaches 80% at 60% of the week
    expect(w?.stopsAt).toBeCloseTo(resets - 0.4 * WEEK_SECONDS, 0);
    expect(w?.stopped).toBe(false);
  });
  it("lasts when the rate so far ends under the stop", () => {
    expect(weekPace(0.2, resets, NOW)?.stopsAt).toBeNull();
    expect(weekPace(0, resets, NOW)?.stopsAt).toBeNull();
  });
  it("is stopped once past it, and unknown without a reading or after its reset", () => {
    expect(weekPace(0.85, resets, NOW)).toMatchObject({ stopped: true, stopsAt: null });
    expect(weekPace(null, resets, NOW)).toBeNull();
    expect(weekPace(0.4, NOW - 1, NOW)).toBeNull();
  });
  it("is not judged in its first hours", () => {
    expect(weekPace(0.05, NOW + 0.99 * WEEK_SECONDS, NOW)?.stopsAt).toBeNull();
  });
});

describe("tonight's accounts together", () => {
  it("say what the line needs and what will go unused", () => {
    const e = account({ usage: usage(0.2), costs: { sonnet: { avg: 0.05, n: 4 }, opus: { avg: 0.1, n: 4 } } });
    const other = account({ usage: usage(0.5, 0.2, { five_hour_resets: NOW + HOUR }) });
    const s = state({ a: e, b: other }, [item("m#1", "queued", { model: "opus" }), item("m#2", "queued"), item("m#3", "done")]);
    const p = poolPace(s);
    expect(p.queued).toBe(2);
    expect(p.need).toBeCloseTo(0.15);
    expect(p.free).toBeCloseTo(0.7); // only a is tonight's
    expect(p.unused).toBeCloseTo(0.55);
    expect(p.resets).toBe(NOW + 2 * HOUR);
    expect(p.top).toBe(0.2);
    expect(p.tight).toBe(false);
    expect(p.accounts.map((a) => [a.name, a.inPool])).toEqual([
      ["a", true],
      ["b", false],
    ]);
  });
  it("count an account that runs work now though it is not one of tonight's", () => {
    const idle = account({ usage: usage(0.1) });
    const busy = account({ usage: usage(0.4), costs: { sonnet: { avg: 0.1, n: 2 } } });
    const p = poolPace(state({ a: idle, b: busy }, [item("m#1", "running", { runner: "b" }), item("m#2", "queued")]));
    expect(p.top).toBe(0.4);
    expect(p.free).toBeCloseTo(0.8 + 0.4);
    expect(p.need).toBeCloseTo(0.1); // priced on the account doing the work
  });
  it("are tight at the gate or when a week will not last", () => {
    const full = account({ usage: usage(0.88) });
    expect(poolPace(state({ a: full })).tight).toBe(true);
    const fast = account({ usage: usage(0.1, 0.6, { seven_day_resets: NOW + 0.7 * WEEK_SECONDS }) });
    expect(poolPace(state({ a: fast })).tight).toBe(true);
  });
  it("have nothing to say with no reading", () => {
    const p = poolPace(state({ a: account() }, [item("m#1", "queued")]));
    expect(p.top).toBeNull();
    expect(p.free).toBe(0);
    expect(p.resets).toBeNull();
  });
});
