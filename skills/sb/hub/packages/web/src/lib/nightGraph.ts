/**
 * The run's graph as a timeline: a column per project, a row per step of the night, oldest at the top. What ran sits
 * above the 'now' line in the order it started, what runs sits on the now row, and what is queued sits below it in
 * the rows the hub would start it in (its queue order, the 'after' arrows, its maps one at a time per project, one
 * ticket per project at a time unless the project runs more at once). Every 'after' is an arrow, also across
 * projects, and each project's last ticket points at one Done box. Pure: no React, no DOM.
 */
import type { MapRoute, Queue, QueueItem, TicketRow } from "@sb-hub/contract";
import { folder, itemInScope, itemMapKey, itemTitle, mapTitle, projOf, type Scope } from "./board.ts";
import { mapState, NODE_H, NODE_W, type MapState } from "./map.ts";

/** Between rows, and between boxes side by side in a column. */
export const GAP = 24;
/** Between project columns. */
export const COL_GAP = 56;
/** The clock column at the left. */
export const CLOCK_W = 76;
/** The project names above the columns. */
export const HEAD = 40;
export const ROW_H = NODE_H + GAP;
export const JOBS = "Jobs";
/** A map's colour inside its project: the first map takes the first. */
export const HUES = ["#2563eb", "#d97706", "#0d9488", "#c026d3", "#65a30d", "#dc2626"] as const;
export const JOB_HUE = "#64748b";

/** How an ended ticket is told. */
export type Outcome = "done" | "fell short" | "stopped";
export interface Counts {
  done: number;
  running: number;
  checking: number;
  next: number;
  "fell short": number;
  stopped: number;
}
const ORDER = ["done", "running", "checking", "next", "fell short", "stopped"] as const;
const COUNT_WORDS: Readonly<Record<(typeof ORDER)[number], string>> = {
  done: "done",
  running: "running",
  checking: "in checks",
  next: "next",
  "fell short": "fell short",
  stopped: "stopped",
};

/** '5 done · 2 running · 9 next · 1 fell short': the words for the counts, none for a zero. */
export const countsLine = (c: Counts): string =>
  ORDER.filter((k) => c[k] > 0).map((k) => `${String(c[k])} ${COUNT_WORDS[k]}`).join(" · ");

const emptyCounts = (): Counts => ({ done: 0, running: 0, checking: 0, next: 0, "fell short": 0, stopped: 0 });
function countOf(i: QueueItem): keyof Counts {
  switch (i.state) {
    case "done": return "done";
    case "running": return "running";
    case "queued": return "next";
    case "failed": return "fell short";
    case "skipped": return "stopped";
    case "landed":
    case "review":
    case "recheck":
    case "unclean": return "checking";
  }
}
export const tally = (items: readonly QueueItem[]): Counts => {
  const c = emptyCounts();
  for (const i of items) c[countOf(i)] += 1;
  return c;
};

/** What the box says on its second line for each queue state. */
const STATE_WORDS: Readonly<Record<QueueItem["state"], string>> = {
  queued: "Queued",
  running: "Running",
  landed: "Waits for its second pass",
  review: "In its second pass",
  recheck: "Checks waiting to run",
  unclean: "Waits for a clean checkout",
  done: "Done",
  failed: "Fell short",
  skipped: "Stopped",
};

/** The map's own state word for an item, through the map graph's one state function. */
export function boxState(i: QueueItem, place: number | null): MapState {
  switch (i.state) {
    case "queued": return mapState({ state: "ready", status: "open", place }, true);
    case "done": return mapState({ state: "done", status: "resolved", place: null }, true);
    case "failed": return mapState({ state: "ready", status: "open", place: null }, false);
    case "skipped": return mapState({ state: "out of scope", status: "out-of-scope", place: null }, true);
    default: return mapState({ state: "claimed", status: "claimed", place: null }, true);
  }
}
const outcomeOf = (i: QueueItem): Outcome | null => (i.state === "done" ? "done" : i.state === "failed" ? "fell short" : i.state === "skipped" ? "stopped" : null);

/** What the run knows of a ticket besides its queue item: its title and the tickets it comes after (as map#num). */
export interface TicketInfo {
  readonly title: string;
  readonly after: readonly string[];
}
export interface MapInfo {
  readonly title: string;
  readonly tickets: ReadonlyMap<string, TicketInfo>;
}

/** The titles and "after" arrows the maps give; the open tickets fill in what a map has not been read for. */
export function infoOf(routes: readonly (MapRoute | undefined)[], rows: readonly TicketRow[]): { tickets: Map<string, TicketInfo>; maps: Map<string, string> } {
  const tickets = new Map<string, TicketInfo>();
  const maps = new Map<string, string>();
  for (const r of rows) {
    const key = `${r.map}#${String(r.num)}`;
    tickets.set(key, { title: r.title, after: r.blocked_by.filter((b): b is number => typeof b === "number").map((n) => `${r.map}#${String(n)}`) });
    if (!maps.has(r.map)) maps.set(r.map, mapTitle(r));
  }
  for (const m of routes) {
    if (m === undefined) continue;
    maps.set(m.map, m.title);
    for (const t of m.tickets) {
      tickets.set(`${m.map}#${String(t.num)}`, { title: t.title, after: t.blocked_by.filter((b) => b.num !== null).map((b) => `${b.map}#${String(b.num)}`) });
    }
  }
  return { tickets, maps };
}

/** One ticket of the run as the list and the graph tell it. */
export interface NightCard {
  id: string;
  /** Its map; "" for a job. */
  map: string;
  project: string;
  item: QueueItem;
  title: string;
  state: MapState;
  /** The box's second line: its outcome, or where it is. */
  foot: string;
  /** Its place in the whole line, for a queued ticket. */
  place: number | null;
  outcome: Outcome | null;
  /** The report's obsidian:// link, for an ended ticket that has one. */
  report: string | null;
  /** Its map's colour. */
  hue: string;
}
/** Where a ticket sits: above the now line, on it, or below it (where the hub would start it). */
export type Phase = "ran" | "now" | "next";
export interface NightBox extends NightCard {
  phase: Phase;
  row: number;
  lane: number;
  x: number;
  y: number;
}
/** One map of the run: its chip above the graph and its group in the phone's list. */
export interface NightFrame {
  id: string;
  /** "" for the jobs. */
  map: string;
  title: string;
  line: string;
  counts: Counts;
  hue: string;
  hidden: boolean;
  boxes: NightCard[];
}
export interface NightColumn {
  project: string;
  x: number;
  w: number;
}
export interface NightRow {
  row: number;
  y: number;
  /** The clock time at its left: when its first ticket started, 'now', or about when it would start. */
  clock: string;
  phase: Phase;
}
export interface NightEdge {
  id: string;
  from: string;
  to: string;
  /** From one project's column to another's. */
  across: boolean;
}
export const DONE_ID = "done";
export interface NightDone {
  x: number;
  y: number;
  finished: number;
  total: number;
  line: string;
}
/** What the next build keeps so the columns do not move: their order and how many boxes wide each got. */
export interface NightMemo {
  cols: readonly string[];
  lanes: ReadonlyMap<string, number>;
}
export interface NightGraph {
  frames: NightFrame[];
  boxes: NightBox[];
  columns: NightColumn[];
  rows: NightRow[];
  edges: NightEdge[];
  /** Where the now line runs; null when nothing runs or waits. */
  nowY: number | null;
  done: NightDone | null;
  counts: Counts;
  line: string;
  memo: NightMemo;
}

export interface NightInput {
  /** The queue's items, finished ones kept until the run is cleared, in the queue's order. */
  items: readonly QueueItem[];
  /** The queued maps in the hub's order. */
  maps: readonly string[];
  info: { tickets: ReadonlyMap<string, TicketInfo>; maps: ReadonlyMap<string, string> };
  scope: Scope;
  /** Maps whose chip is off. */
  hidden?: ReadonlySet<string> | undefined;
  /** Project -> how many of its tickets run at once (the queue's repos); 1 when absent. */
  atOnce?: ReadonlyMap<string, number> | undefined;
  /** Seconds, for the clock of the rows still to come. */
  now?: number | undefined;
  prev?: NightMemo | undefined;
}

/** The queue's repos as project -> tickets at once. */
export const atOnceOf = (repos: Queue["repos"]): Map<string, number> =>
  new Map(Object.entries(repos ?? {}).map(([repo, l]) => [folder(repo), l.at_once] as const));

const pad = (n: number): string => String(n).padStart(2, "0");
/** '21:05', local time. */
export const clock = (sec: number): string => {
  const d = new Date(sec * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const projectOf = (i: QueueItem): string => (i.kind === "job" ? folder(i.project) : projOf(itemMapKey(i)));
const startOf = (i: QueueItem): number => i.started ?? i.ended ?? 0;

/** Rows by the hub's rules: old row number per key, the lane inside its column, and the first row on or below now. */
function place(all: readonly QueueItem[], maps: readonly string[], after: (k: string) => string[], atOnce: ReadonlyMap<string, number> | undefined) {
  const row = new Map<string, number>();
  const lane = new Map<string, number>();
  const used = new Map<string, number>();
  const at = (r: number, p: string): string => `${String(r)}|${p}`;
  const take = (k: string, r: number, p: string): void => {
    const n = used.get(at(r, p)) ?? 0;
    used.set(at(r, p), n + 1);
    row.set(k, r);
    lane.set(k, n);
  };

  // what ran, by start: a row takes one ticket per project, and none that comes after another of the same row
  const ran = all.filter((i) => i.state !== "queued" && i.state !== "running").sort((a, b) => startOf(a) - startOf(b));
  let r = -1;
  const keys = new Set<string>();
  for (const i of ran) {
    const p = projectOf(i);
    if (r < 0 || used.has(at(r, p)) || after(i.key).some((a) => keys.has(a))) {
      r += 1;
      keys.clear();
    }
    keys.add(i.key);
    take(i.key, r, p);
  }
  const now = r + 1;
  for (const i of all) if (i.state === "running") take(i.key, now, projectOf(i));

  // what is queued, a row at a time, the way the hub scans its queue
  const cap = (p: string): number => Math.max(1, atOnce?.get(p) ?? 1);
  const rank = (i: QueueItem): number => maps.indexOf(itemMapKey(i));
  let left = all.filter((i) => i.state === "queued");
  for (let k = now + 1; left.length > 0; k += 1) {
    const before = (key: string): boolean => (row.get(key) ?? Infinity) < k;
    for (const i of left) {
      const p = projectOf(i);
      const n = used.get(at(k, p)) ?? 0;
      if (n >= cap(p) || (i.kind === "job" && n > 0)) continue;
      if (!after(i.key).every(before)) continue;
      // in a project the hub starts tickets only from its first map with work
      const mine = rank(i);
      if (i.kind !== "job" && mine >= 0 && left.some((o) => o.kind !== "job" && projectOf(o) === p && rank(o) >= 0 && rank(o) < mine && !before(o.key))) continue;
      take(i.key, k, p);
      if (i.kind === "job") used.set(at(k, p), cap(p));
    }
    const rest = left.filter((i) => !row.has(i.key));
    // nothing could start (an 'after' that loops): the first one left goes next so the row count stays finite
    const first = rest[0];
    if (rest.length === left.length && first !== undefined) take(first.key, k, projectOf(first));
    left = rest.filter((i) => !row.has(i.key));
  }
  return { row, lane, now };
}

export function nightGraph(input: NightInput): NightGraph {
  const { info, scope, maps } = input;
  const hidden = input.hidden ?? new Set<string>();
  // one box per key; a key the queue holds twice shows its latest
  const latest = new Map<string, QueueItem>();
  for (const i of input.items) latest.set(i.key, i);
  const all = [...latest.values()];
  const after = (k: string): string[] => (info.tickets.get(k)?.after ?? []).filter((a) => a !== k && latest.has(a));
  // the rows come from the whole run, so a project or map left out still takes the turns it takes
  const { row, lane, now } = place(all, maps, after, input.atOnce);

  const scoped = all.filter((i) => itemInScope(scope, i));
  const queued = new Map(scoped.filter((i) => i.state === "queued").map((i, n) => [i.key, n + 1]));
  const mapOrder = [...new Set([...maps, ...scoped.filter((i) => i.kind !== "job").map(itemMapKey)])];
  const hueOf = (m: string): string => {
    if (m === "") return JOB_HUE;
    const same = mapOrder.filter((o) => projOf(o) === projOf(m));
    return HUES[Math.max(0, same.indexOf(m)) % HUES.length] ?? JOB_HUE;
  };
  const cardOf = (i: QueueItem): NightCard => {
    const p = queued.get(i.key) ?? null;
    const m = itemMapKey(i);
    return {
      id: i.key,
      map: m,
      project: projectOf(i),
      item: i,
      title: info.tickets.get(i.key)?.title ?? itemTitle(i, null),
      state: boxState(i, p),
      foot: p !== null ? `${STATE_WORDS[i.state]} ${String(p)}` : STATE_WORDS[i.state],
      place: p,
      outcome: outcomeOf(i),
      report: outcomeOf(i) !== null ? i.links.report : null,
      hue: hueOf(m),
    };
  };

  // the chips and the list: a map each in the hub's order, then the jobs
  const frames: NightFrame[] = [];
  for (const m of [...mapOrder, ""]) {
    const its = scoped.filter((i) => itemMapKey(i) === m);
    if (its.length === 0) continue;
    const counts = tally(its);
    frames.push({
      id: m === "" ? "f:jobs" : `f:${m}`, map: m, title: m === "" ? JOBS : (info.maps.get(m) ?? (m.split("/").pop() ?? m)),
      line: countsLine(counts), counts, hue: hueOf(m), hidden: hidden.has(m), boxes: its.map(cardOf),
    });
  }

  // the graph: what the chips leave shown; a row nothing shown sits in drops out
  const shown = scoped.filter((i) => !hidden.has(itemMapKey(i)));
  const oldRows = [...new Set(shown.map((i) => row.get(i.key) ?? 0))].sort((a, b) => a - b);
  const newRow = new Map(oldRows.map((o, n) => [o, n]));
  const prevCols = input.prev?.cols ?? [];
  const projects = [...new Set([...prevCols, ...mapOrder.map(projOf), ...shown.map(projectOf)])].filter((p) => shown.some((i) => projectOf(i) === p));
  const lanes = new Map(input.prev?.lanes ?? []);
  for (const i of shown) lanes.set(projectOf(i), Math.max(lanes.get(projectOf(i)) ?? 1, (lane.get(i.key) ?? 0) + 1));
  const columns: NightColumn[] = [];
  let x = CLOCK_W;
  for (const p of projects) {
    const n = lanes.get(p) ?? 1;
    const w = n * NODE_W + (n - 1) * GAP;
    columns.push({ project: p, x, w });
    x += w + COL_GAP;
  }
  const colOf = new Map(columns.map((c) => [c.project, c]));
  const yOf = (r: number): number => HEAD + r * ROW_H;
  const phaseOf = (r: number): Phase => (r < now ? "ran" : r === now ? "now" : "next");
  const boxes: NightBox[] = shown.map((i) => {
    const o = row.get(i.key) ?? 0;
    const r = newRow.get(o) ?? 0;
    const l = lane.get(i.key) ?? 0;
    return { ...cardOf(i), phase: phaseOf(o), row: r, lane: l, x: (colOf.get(projectOf(i))?.x ?? CLOCK_W) + l * (NODE_W + GAP), y: yOf(r) };
  });

  // the clock: when a row's first ticket started; about when a row to come would, from the night's usual run
  const t = input.now ?? Date.now() / 1000;
  const runs = all.filter((i) => i.started != null && i.ended != null && i.state !== "skipped").map((i) => (i.ended ?? 0) - (i.started ?? 0)).sort((a, b) => a - b);
  const usual = runs.length > 0 ? (runs[Math.floor(runs.length / 2)] ?? null) : null;
  const running = all.filter((i) => i.state === "running");
  const nextAt = usual === null ? null : Math.max(t, ...running.map((i) => (i.started ?? t) + usual));
  const rows: NightRow[] = oldRows.map((o, n) => {
    const ph = phaseOf(o);
    const starts = boxes.filter((b) => b.row === n).map((b) => startOf(b.item));
    const c = ph === "ran" ? clock(Math.min(...starts)) : ph === "now" ? "now" : nextAt !== null && usual !== null ? `≈${clock(nextAt + (o - now - 1) * usual)}` : o === now + 1 ? "next" : "then";
    return { row: n, y: yOf(n), clock: c, phase: ph };
  });
  const firstLive = rows.find((r) => r.phase !== "ran");
  const nowY = firstLive === undefined ? null : firstLive.y - GAP / 2;

  const shownKeys = new Set(shown.map((i) => i.key));
  const edges: NightEdge[] = [];
  for (const i of shown) {
    for (const a of after(i.key)) {
      const from = latest.get(a);
      if (from === undefined || !shownKeys.has(a)) continue;
      edges.push({ id: `${a}>${i.key}`, from: a, to: i.key, across: projectOf(from) !== projectOf(i) });
    }
  }
  let done: NightDone | null = null;
  if (boxes.length > 0) {
    for (const c of columns) {
      const last = boxes.filter((b) => b.project === c.project).sort((a, b) => b.row - a.row || b.lane - a.lane)[0];
      if (last !== undefined) edges.push({ id: `${last.id}>${DONE_ID}`, from: last.id, to: DONE_ID, across: false });
    }
    const finished = boxes.filter((b) => b.outcome !== null).length;
    const right = x - COL_GAP;
    done = { x: CLOCK_W + Math.max(0, (right - CLOCK_W - NODE_W) / 2), y: yOf(rows.length) + GAP, finished, total: boxes.length, line: `${String(finished)} of ${String(boxes.length)} finished` };
  }

  const counts = tally(scoped);
  return { frames, boxes, columns, rows, edges, nowY, done, counts, line: countsLine(counts), memo: { cols: [...new Set([...prevCols, ...projects])], lanes } };
}

/** The point to centre on: the tickets that run now, else the first row to come, else null. */
export function focusOf(g: Pick<NightGraph, "boxes">): { x: number; y: number } | null {
  const run = g.boxes.filter((b) => b.phase === "now");
  const pick = run.length > 0 ? run : g.boxes.filter((b) => b.phase === "next");
  if (pick.length === 0) return null;
  const xs = pick.map((b) => b.x + NODE_W / 2);
  const ys = pick.map((b) => b.y + NODE_H / 2);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: Math.min(...ys) };
}
