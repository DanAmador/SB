/** The Run tab's grouping: the night map by map. Pure: no React, no DOM. */
import type { QueueItem, State } from "@sb-hub/contract";
import { endedToday, itemInScope, itemMap, mapTitle, projOf, type Scope, type TicketIndex, itemProject, EVERYTHING } from "./board.ts";

/** What a row's mark says. */
export type Mark = "done" | "running" | "checking" | "next" | "short" | "stopped" | "recheck";

export const MARK_WORDS: Readonly<Record<Mark, string>> = {
  done: "done",
  running: "running",
  checking: "in checks or second pass",
  next: "next",
  short: "fell short",
  stopped: "stopped",
  recheck: "check could not run",
};

export interface NightRow {
  readonly item: QueueItem;
  readonly mark: Mark;
  /** Its place in the whole line (1 is next) while it is queued, else null. */
  readonly place: number | null;
}

export interface NightBlock {
  /** The map, or "" for Jobs. */
  readonly map: string;
  readonly title: string;
  readonly project: string;
  readonly rows: readonly NightRow[];
  readonly counts: Readonly<Record<Mark, number>>;
  /** 'Run order' counts line: '3 done · 1 running · 4 next · 1 fell short'. */
  readonly line: string;
  readonly open: boolean;
  /** Its place among the queued maps, or -1 when it is not queued. */
  readonly at: number;
}

export interface Night {
  readonly line: { readonly running: number; readonly next: number; readonly done: number; readonly short: number; readonly stopAt: number | null };
  readonly blocks: readonly NightBlock[];
  /** The queued maps in run order (what move_map counts places in). */
  readonly queuedMaps: readonly string[];
}

const ORDER: readonly Mark[] = ["done", "running", "checking", "recheck", "next", "short", "stopped"];
const WORDS: Readonly<Record<Mark, string>> = { done: "done", running: "running", checking: "checking", recheck: "check could not run", next: "next", short: "fell short", stopped: "stopped" };

export function markOf(i: QueueItem): Mark {
  switch (i.state) {
    case "queued": return "next";
    case "running": return "running";
    case "landed":
    case "review": return "checking";
    case "recheck": return "recheck";
    case "done": return "done";
    case "skipped": return "stopped";
    default: return "short";
  }
}

export function countsLine(c: Readonly<Record<Mark, number>>): string {
  return ORDER.filter((m) => c[m] > 0).map((m) => `${String(c[m])} ${WORDS[m]}`).join(" · ");
}

const GROUP_ORDER: Readonly<Record<Mark, number>> = { done: 0, short: 0, stopped: 0, running: 1, checking: 1, recheck: 2, next: 3 };

/** Every map with something running, queued or ended today, in the hub's map order; then Jobs. */
export function nightBlocks(state: State, ix: TicketIndex, scope: Scope = EVERYTHING): Night {
  const q = state.queue;
  const queued = q.items.filter((i) => i.state === "queued");
  const place = new Map(queued.map((i, n) => [i.key, n + 1] as const));
  const live = q.items.filter((i) => ["queued", "running", "landed", "review", "recheck"].includes(i.state));
  const all = [...live, ...endedToday(state)].filter((i) => itemInScope(scope, i));
  const maps = new Map<string, QueueItem[]>();
  for (const i of all) {
    const m = i.kind === "job" ? "" : itemMap(i);
    maps.set(m, [...(maps.get(m) ?? []), i]);
  }
  const queuedMaps = q.maps ?? [];
  const rest = [...maps.keys()].filter((m) => m !== "" && !queuedMaps.includes(m));
  const orderOf = (m: string): number => ix.byKey.get(`${m}#1`)?.map_order ?? [...ix.byKey.values()].find((t) => t.map === m)?.map_order ?? 1e9;
  rest.sort((x, y) => orderOf(x) - orderOf(y));
  const keys = [...queuedMaps.filter((m) => maps.has(m)), ...rest, ...(maps.has("") ? [""] : [])];
  const blocks = keys.map((map): NightBlock => {
    const items = maps.get(map) ?? [];
    const rows = items
      .map((item, n): [NightRow, number] => [{ item, mark: markOf(item), place: place.get(item.key) ?? null }, n])
      .sort(([a, an], [b, bn]) => {
        const g = GROUP_ORDER[a.mark] - GROUP_ORDER[b.mark];
        if (g !== 0) return g;
        if (a.mark === "next") return (a.place ?? 0) - (b.place ?? 0);
        if (GROUP_ORDER[a.mark] === 0) return (a.item.ended ?? 0) - (b.item.ended ?? 0) || an - bn;
        return (a.item.started ?? 0) - (b.item.started ?? 0) || an - bn;
      })
      .map(([r]) => r);
    const counts = Object.fromEntries(ORDER.map((m) => [m, rows.filter((r) => r.mark === m).length])) as Record<Mark, number>;
    const first = items[0];
    const t = ix.byKey.get(`${map}#1`) ?? [...ix.byKey.values()].find((x) => x.map === map);
    return {
      map,
      title: map === "" ? "Jobs" : t ? mapTitle(t) : map,
      project: map === "" ? "" : first ? itemProject(first, ix.byKey.get(first.key)) || projOf(map) : projOf(map),
      rows,
      counts,
      line: countsLine(counts),
      open: counts.running + counts.checking + counts.short + counts.recheck > 0,
      at: queuedMaps.indexOf(map),
    };
  });
  const sum = (m: Mark): number => blocks.reduce((n, b) => n + b.counts[m], 0);
  return {
    line: { running: sum("running") + sum("checking"), next: sum("next"), done: sum("done"), short: sum("short"), stopAt: q.stop_at ?? null },
    blocks,
    queuedMaps,
  };
}

/** The one line for the night: '1 running · 4 next · 3 done · 1 fell short'. */
export function nightLine(n: Night): string {
  const l = n.line;
  return [`${String(l.running)} running`, `${String(l.next)} next`, `${String(l.done)} done`, `${String(l.short)} fell short`].join(" · ");
}
