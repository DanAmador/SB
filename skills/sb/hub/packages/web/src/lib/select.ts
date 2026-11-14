/**
 * The ticked tickets, outside React, and what each bar action does with them: which of the ticked it applies to and
 * which it skips. The table ticks; the bar acts; a graph can tick the same keys later.
 */
import { useSyncExternalStore } from "react";
import type { TableRow } from "./board.ts";
import { Store } from "./store.ts";

const ticked = new Store<ReadonlySet<string>>(new Set());
/** The row last ticked: Shift-click ticks from it. */
const anchor = new Store<string | null>(null);

export const useSelection = (): ReadonlySet<string> => useSyncExternalStore(ticked.subscribe, ticked.get, ticked.get);

export const selected = (): ReadonlySet<string> => ticked.get();
export function tick(keys: Iterable<string>, on: boolean): void {
  const next = new Set(ticked.get());
  for (const k of keys) {
    if (on) next.add(k);
    else next.delete(k);
  }
  ticked.set(next);
}
export const clearSelection = (): void => {
  ticked.set(new Set());
  anchor.set(null);
};

/** The keys from one row to another in the order shown, both included; just `to` when `from` is not shown. */
export function between(order: readonly string[], from: string | null, to: string): string[] {
  const a = from === null ? -1 : order.indexOf(from);
  const b = order.indexOf(to);
  if (b < 0) return [];
  if (a < 0) return [to];
  return order.slice(Math.min(a, b), Math.max(a, b) + 1);
}

/** A click on a row's box: Shift ticks the range from the last one (on or off as that one now is); else it flips this row. */
export function clickRow(order: readonly string[], key: string, shift: boolean): void {
  const was = ticked.get().has(key);
  if (shift && anchor.get() !== null) {
    const from = anchor.get();
    tick(between(order, from, key), from !== null && ticked.get().has(from) ? true : !was);
  } else tick([key], !was);
  anchor.set(key);
}

export const ACTS = ["queue", "unqueue", "drop", "done", "tier", "comment"] as const;
export type Act = (typeof ACTS)[number];
export const ACT_WORDS: Readonly<Record<Act, string>> = { queue: "Queue", unqueue: "Unqueue", drop: "Drop", done: "Mark done", tier: "Set tier", comment: "Comment" };

const OPEN = new Set<TableRow["state"]>(["can run now", "can run after another", "queued", "needs a decision", "no checks", "claimed", "stuck behind another"]);
/** Whether an action means anything for a ticket in this state: a queued ticket is unqueued before it is dropped or done. */
export function applies(act: Act, r: TableRow): boolean {
  switch (act) {
    case "queue": return r.state === "can run now" || r.state === "can run after another";
    case "unqueue": return r.state === "queued";
    case "drop":
    case "done": return OPEN.has(r.state) && r.state !== "queued";
    case "tier": return OPEN.has(r.state);
    case "comment": return true;
  }
}

/** The ticked rows an action applies to, and those it skips. */
export function split(act: Act, rows: readonly TableRow[]): { apply: TableRow[]; skip: TableRow[] } {
  const apply: TableRow[] = [];
  const skip: TableRow[] = [];
  for (const r of rows) (applies(act, r) ? apply : skip).push(r);
  return { apply, skip };
}
