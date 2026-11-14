/** History's rules: which runs a filter keeps, how they group by day, and what the time range asks the hub for. */
import type { Run, RunOutcome } from "@sb-hub/contract";
import { dayStart, mapInScope, type Scope } from "./board.ts";

export const RANGES = ["today", "7d", "30d", "all"] as const;
export type Range = (typeof RANGES)[number];
export const DEFAULT_RANGE: Range = "7d";
export const RANGE_WORDS: Readonly<Record<Range, string>> = { today: "Today", "7d": "7 days", "30d": "30 days", all: "All" };
export const OUTCOMES: readonly RunOutcome[] = ["done", "failed", "skipped", "unknown"];

export const rangeOf = (v: string): Range => RANGES.find((r) => r === v) ?? DEFAULT_RANGE;
export const outcomeOf = (v: string): RunOutcome | "" => OUTCOMES.find((o) => o === v) ?? "";

/** The epoch a range starts at: local midnight today, 6 or 29 days before it (so "7 days" counts today), or 0. */
export function sinceOf(range: Range, now: number): number {
  const today = dayStart(now);
  const back = { today: 0, "7d": 6, "30d": 29, all: -1 }[range];
  if (back < 0) return 0;
  const d = new Date(today * 1000);
  d.setDate(d.getDate() - back);
  return d.getTime() / 1000;
}

export interface Filters {
  readonly q: string;
  readonly outcome: RunOutcome | "";
  readonly pictures: boolean;
  readonly account: string;
  readonly model: string;
}

/** The runs a filter and the sidebar's scope keep, in the order given. Search reads titles, reasons, commits and keys. */
export function filterRuns(runs: readonly Run[], f: Filters, scope: Scope): Run[] {
  const words = f.q.toLowerCase().split(/\s+/).filter(Boolean);
  return runs.filter((r) => {
    if (!mapInScope(scope, r.map)) return false;
    if (f.outcome !== "" && r.outcome !== f.outcome) return false;
    if (f.pictures && r.pictures.length === 0) return false;
    if (f.account !== "" && r.account !== f.account) return false;
    if (f.model !== "" && r.model !== f.model) return false;
    const hay = `${r.title} ${r.reason} ${r.commit ?? ""} ${r.key}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** The accounts and models the runs name, for the filter's choices. */
export function choices(runs: readonly Run[]): { accounts: string[]; models: string[] } {
  const uniq = (xs: (string | null)[]): string[] => [...new Set(xs.filter((x): x is string => x !== null && x !== ""))].sort();
  return { accounts: uniq(runs.map((r) => r.account)), models: uniq(runs.map((r) => r.model)) };
}

export interface Day {
  readonly label: string;
  readonly runs: Run[];
}

/** Runs (newest first) in groups by the local day they ended: Today, Yesterday, then the date. */
export function groupByDay(runs: readonly Run[], now: number): Day[] {
  const today = dayStart(now);
  const days: Day[] = [];
  for (const r of runs) {
    const at = r.ended ?? 0;
    const start = at === 0 ? 0 : dayStart(at);
    const label = at === 0 ? "No end time" : labelOf(start, today);
    const last = days[days.length - 1];
    if (last?.label === label) last.runs.push(r);
    else days.push({ label, runs: [r] });
  }
  return days;
}

function labelOf(start: number, today: number): string {
  const d = new Date(start * 1000);
  const t = new Date(today * 1000);
  const y = new Date(today * 1000);
  y.setDate(t.getDate() - 1);
  if (d.getTime() === t.getTime()) return "Today";
  if (d.getTime() === y.getTime()) return "Yesterday";
  return d.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}

/** Whole minutes a run took, or null when it has no start. */
export const minutesOf = (r: Pick<Run, "started" | "ended">): number | null =>
  r.started === null || r.ended === null ? null : Math.max(0, Math.round((r.ended - r.started) / 60));

/** The lines of a log that hold every word of a search, and how many; no search keeps every line. */
export function searchLog(text: string, q: string): { lines: string[]; found: number } {
  const lines = text.split("\n");
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return { lines, found: 0 };
  const hit = lines.filter((l) => words.every((w) => l.toLowerCase().includes(w)));
  return { lines: hit, found: hit.length };
}

/** Step to a neighbour in a list of pictures, wrapping at the ends. */
export const stepIndex = (i: number, by: 1 | -1, n: number): number => (n === 0 ? 0 : (i + by + n) % n);

/** Clamp a zoom to 1x to 6x, so a picture never shrinks below its frame. */
export const clampZoom = (z: number): number => Math.min(6, Math.max(1, Math.round(z * 100) / 100));
