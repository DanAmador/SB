/**
 * Usage pace: what each account has used of its 5-hour window and its week, what its running work still holds,
 * and what is free. Read-only arithmetic over the hub's state; the gates and costs mirror sbhub.py's pacing
 * (GATE_5H, GATE_7D, DEFAULT_COST, _cost), which stays the one place that decides what starts.
 */
import type { Installed, State } from "@sb-hub/contract";
import { poolOf } from "./board.ts";

/** Nothing starts that would take an account's 5-hour window past this. */
export const GATE_5H = 0.9;
/** Nothing starts on an account whose week is used past this. */
export const GATE_7D = 0.8;
export const WINDOW = 5 * 3600;
export const WEEK_SECONDS = 7 * 86400;
/** A reading older than this is shown as old: the hub no longer trusts it either. */
export const READING_OLD = 1800;
/** A week's rate is not judged before this share of it has passed. */
const WEEK_MIN_GONE = 0.02;
const DEFAULT_COST = { sonnet: 0.15, opus: 0.3 } as const;

export type Tier = keyof typeof DEFAULT_COST;
export const tierOf = (model: string | null | undefined): Tier => ((model ?? "").includes("opus") ? "opus" : "sonnet");

/** The share of a 5-hour window one ticket of `tier` costs on this account: learned, else the default. */
export function costOf(e: Installed, tier: Tier): number {
  const costs = e.costs ?? {};
  const floor = DEFAULT_COST[tier] / 3;
  const own = costs[tier];
  if (own) return Math.max(floor, own.avg);
  const other = costs[tier === "opus" ? "sonnet" : "opus"];
  if (other) return Math.max(floor, other.avg * (tier === "opus" ? 2 : 0.5));
  return DEFAULT_COST[tier];
}

/** The least a Codex ticket is taken to cost: Codex counts in whole percents, so a small one can read as 0. */
const CODEX_FLOOR = 0.01;

/** The share of a 5-hour window one ticket costs on a Codex account, learned by the hub from its runs (sbhub.py
 * codex_run_cost); null until its first finished ticket. Never a Claude default: the two are not alike. */
export function codexCost(e: Installed): number | null {
  const own = e.costs?.codex;
  return own ? Math.max(CODEX_FLOOR, own.avg) : null;
}

export interface WeekPace {
  used: number;
  resets: number;
  /** The share of the week that has passed. */
  gone: number;
  /** Where use would stand now if the week were spent evenly up to its stop. */
  even: number;
  /** When use reaches the stop at the rate so far; null when the week lasts, or it is too early to tell. */
  stopsAt: number | null;
  /** Already past the stop. */
  stopped: boolean;
}

export interface AccountPace {
  name: string;
  inPool: boolean;
  /** Workers running on it now. */
  running: number;
  /** A Codex account: shown, never paced, so left out of the pool's sums. */
  codex: boolean;
  /** null: no reading to go by (never read, or not a Claude account). */
  five: {
    used: number;
    /** What its running work is still expected to take. */
    held: number;
    /** What is left under the gate after both. */
    free: number;
    /** null: the window it was read in has ended; the next one opens with the next work. */
    resets: number | null;
    /** How many more tickets of each tier fit under the gate; a Codex account's count of its own tickets, null
     * while no cost is learned. */
    fits: Record<Tier, number> | { tickets: number | null };
    /** The reading is too old for the hub to trust. */
    old: boolean;
    at: number;
  } | null;
  week: WeekPace | null;
}

export function accountPace(name: string, e: Installed, state: State): AccountPace {
  const now = state.now;
  const mine = state.queue.items.filter((i) => i.state === "running" && i.runner === name);
  const codex = e.kind === "codex";
  const base = { name, inPool: poolOf(state).includes(name), running: mine.length, codex };
  const u = e.kind === "agy" ? undefined : e.usage; // Claude streams it; Codex is read from its session files
  if (!u) return { ...base, five: null, week: null };
  const live = (u.five_hour_resets ?? 0) > now;
  const used = live ? u.five_hour : 0;
  const each = codex ? codexCost(e) : null;
  const held = codex ? mine.length * (each ?? 0) : mine.reduce((n, i) => n + costOf(e, tierOf(i.model)), 0);
  const free = Math.max(0, GATE_5H - used - held);
  const fits = codex
    ? { tickets: each === null ? null : Math.floor(free / each + 1e-9) }
    : { sonnet: Math.floor(free / costOf(e, "sonnet") + 1e-9), opus: Math.floor(free / costOf(e, "opus") + 1e-9) };
  const five = { used, held, free, resets: live ? u.five_hour_resets : null, fits, old: now - u.at > READING_OLD, at: u.at };
  return { ...base, five, week: weekPace(u.seven_day, u.seven_day_resets, now) };
}

export function weekPace(used: number | null, resets: number | null, now: number): WeekPace | null {
  if (used === null || resets === null || resets <= now) return null;
  const start = resets - WEEK_SECONDS;
  const gone = Math.min(1, Math.max(0, (now - start) / WEEK_SECONDS));
  const stopped = used >= GATE_7D;
  let stopsAt: number | null = null;
  if (!stopped && used > 0 && gone >= WEEK_MIN_GONE) {
    const at = start + (GATE_7D / used) * (now - start);
    if (at < resets) stopsAt = at;
  }
  return { used, resets, gone, even: gone * GATE_7D, stopsAt, stopped };
}

export interface PoolPace {
  accounts: AccountPace[];
  /** Items in line, and about what they need of a 5-hour window. */
  queued: number;
  need: number;
  /** Free under the gate, summed over the accounts in use (tonight's, and any running work now) that have a reading. */
  free: number;
  /** How many accounts that sum covers. */
  inUse: number;
  /** What stays free once the whole line has run: the part of these windows nothing will use. */
  unused: number;
  /** The earliest reset among tonight's accounts; null when none is known. */
  resets: number | null;
  /** The highest 5-hour use among tonight's accounts, for the button; null with no reading. */
  top: number | null;
  /** An account of tonight's is at its gate, past its week's stop, or will reach that stop before the week ends. */
  tight: boolean;
}

export function poolPace(state: State): PoolPace {
  const accounts = Object.entries(state.installed).map(([n, e]) => accountPace(n, e, state));
  // tonight's accounts, and any other one that is running work now (an item pinned to it, or a changed pool)
  const pool = accounts.filter((a) => (a.inPool || a.running > 0) && a.five !== null && !a.codex);
  const busiest = [...pool].sort((x, y) => y.running - x.running)[0];
  const first = busiest ? state.installed[busiest.name] : poolOf(state).map((n) => state.installed[n]).find((e) => e !== undefined);
  const line = state.queue.items.filter((i) => i.state === "queued");
  const need = first ? line.reduce((n, i) => n + costOf(first, tierOf(i.model)), 0) : 0;
  const free = pool.reduce((n, a) => n + (a.five?.free ?? 0), 0);
  const resets = pool.map((a) => a.five?.resets ?? null).filter((r): r is number => r !== null);
  return {
    accounts,
    queued: line.length,
    need,
    free,
    inUse: pool.length,
    unused: Math.max(0, free - need),
    resets: resets.length > 0 ? Math.min(...resets) : null,
    top: pool.length > 0 ? Math.max(...pool.map((a) => a.five?.used ?? 0)) : null,
    tight: pool.some((a) => (a.five?.free ?? 1) < 0.05 || a.week?.stopped === true || (a.week?.stopsAt ?? null) !== null),
  };
}
