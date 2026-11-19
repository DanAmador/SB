/**
 * The run's graph as a timeline: a column per project, time running down, one row (ROW_H) per half hour (SLOT). What
 * ran and what runs sits at the time it started, measured from the night's first start, and is as tall as its run
 * took (at least a box's height); boxes of a project whose runs or boxes would overlap go side by side, each in the
 * first lane free (in start order), and keep that lane as the run goes on. A stretch over LONG_EMPTY with nothing
 * shown running is drawn one slot tall. Below the now line what is
 * queued sits in the rows the hub would start it in (its queue order, the 'after' arrows, its maps one at a time per
 * project, one ticket per project at a time unless the project runs more at once). Every 'after' is an arrow, also
 * across projects, and each project's last ticket points at one Done box. Pure: no React, no DOM.
 */
import type { MapRoute, Queue, QueueItem, TicketRow } from "@sb-hub/contract";
import { CHAT_RUNNER, ESTIMATE, folder, itemInScope, landedShort, itemMapKey, itemTitle, mapTitle, projOf, type Scope } from "./board.ts";
import { mapState, NODE_H, NODE_W, type MapState } from "./map.ts";

/** Between rows, and between boxes side by side in a column. */
export const GAP = 24;
/** Between project columns. */
export const COL_GAP = 56;
/** The clock column at the left. */
export const CLOCK_W = 76;
/** The project names above the columns. */
export const HEAD = 40;
/** A row, and a slot of the night. */
export const ROW_H = NODE_H + GAP;
/** The time one row stands for, in seconds: half an hour. */
export const SLOT = 1800;
/** An empty stretch longer than this (seconds; nothing shown runs or starts in it) is drawn one slot tall. */
export const LONG_EMPTY = 2 * 3600;
/** Clock labels closer than this (px) drop the less telling one. */
const LABEL_APART = 28;
export const JOBS = "Jobs";
/** A map's colour inside its project: the first map takes the first. */
export const HUES = ["#2563eb", "#d97706", "#0d9488", "#c026d3", "#65a30d", "#dc2626"] as const;
export const JOB_HUE = "#64748b";

/** How an ended ticket is told. */
export type Outcome = "done" | "landed" | "fell short" | "stopped";
export interface Counts {
  done: number;
  landed: number;
  running: number;
  checking: number;
  next: number;
  "fell short": number;
  stopped: number;
}
const ORDER = ["done", "landed", "running", "checking", "next", "fell short", "stopped"] as const;
const COUNT_WORDS: Readonly<Record<(typeof ORDER)[number], string>> = {
  done: "done",
  landed: "landed, need your look",
  running: "running",
  checking: "in checks",
  next: "next",
  "fell short": "fell short",
  stopped: "stopped",
};

/** '5 done · 2 running · 9 next · 1 fell short': the words for the counts, none for a zero. */
export const countsLine = (c: Counts): string =>
  ORDER.filter((k) => c[k] > 0).map((k) => `${String(c[k])} ${COUNT_WORDS[k]}`).join(" · ");

const emptyCounts = (): Counts => ({ done: 0, landed: 0, running: 0, checking: 0, next: 0, "fell short": 0, stopped: 0 });
function countOf(i: QueueItem): keyof Counts {
  switch (i.state) {
    case "done": return "done";
    case "running": return "running";
    case "queued": return "next";
    case "failed": return landedShort(i) ? "landed" : "fell short";
    case "skipped": return "stopped";
    case "landed":
    case "review":
    case "recheck":
    case "unclean":
    case "handed": return "checking";
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
  handed: "To integrate",
  done: "Done",
  failed: "Fell short",
  skipped: "Stopped",
};

/** The map's own state word for an item, through the map graph's one state function. */
export function boxState(i: QueueItem, place: number | null): MapState {
  switch (i.state) {
    case "queued": return mapState({ state: "ready", status: "open", place }, true);
    case "done": return mapState({ state: "done", status: "resolved", place: null }, true);
    // landed, the review said partly: amber like a decision, not the red of a ticket with no checks
    case "failed": return mapState({ state: landedShort(i) ? "waits for you" : "ready", status: "open", place: null }, false);
    case "skipped": return mapState({ state: "out of scope", status: "out-of-scope", place: null }, true);
    default: return mapState({ state: "claimed", status: "claimed", place: null }, true);
  }
}
export const outcomeOf = (i: QueueItem): Outcome | null => (i.state === "done" ? "done" : i.state === "failed" ? (landedShort(i) ? "landed" : "fell short") : i.state === "skipped" ? "stopped" : null);

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

/**
 * A run as it ran (ticket 169): each ticket that kept its title, map title and 'after' arrows when it started tells
 * them itself, over what the maps say today; a ticket that kept nothing (a run from before) keeps today's.
 */
export function frozenInfo(items: readonly QueueItem[], base: { tickets: ReadonlyMap<string, TicketInfo>; maps: ReadonlyMap<string, string> }): { tickets: Map<string, TicketInfo>; maps: Map<string, string> } {
  const tickets = new Map(base.tickets);
  const maps = new Map(base.maps);
  for (const i of items) {
    if (i.kind !== "ticket") continue;
    if (i.after !== undefined) tickets.set(i.key, { title: i.title ?? tickets.get(i.key)?.title ?? i.key, after: i.after });
    if (i.map_title !== undefined && i.map_title !== "") maps.set(itemMapKey(i), i.map_title);
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
  /** Its rank from the top among the graph's distinct box heights: a later row is lower. */
  row: number;
  lane: number;
  x: number;
  y: number;
  /** Its height: as long as its run took on the timeline, at least NODE_H; NODE_H for a queued one. */
  h: number;
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
/** One clock label: its text is centred on the time's line, so the node's y is the line less half a box. */
export interface NightRow {
  row: number;
  y: number;
  /** The night's first start, an hour, a start after a long empty stretch, 'now hh:mm', or '≈hh:mm' for a queued row. */
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
/** What the next build keeps so nothing moves: the columns' order, how many boxes wide each got, each started box's lane. */
export interface NightMemo {
  cols: readonly string[];
  lanes: ReadonlyMap<string, number>;
  /** Key -> lane, for the boxes that ran or run. */
  slots?: ReadonlyMap<string, number>;
}
export interface NightGraph {
  frames: NightFrame[];
  boxes: NightBox[];
  columns: NightColumn[];
  rows: NightRow[];
  edges: NightEdge[];
  /** Where the now line runs (at the current time); null when nothing runs or waits. */
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
/** The rows to come by the hub's rules: queued row (0 first) and lane in its column per queued key. */
function queueRows(all: readonly QueueItem[], maps: readonly string[], after: (k: string) => string[], atOnce: ReadonlyMap<string, number> | undefined) {
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
  // a row at a time, the way the hub scans its queue; what ran or runs is already before every row to come
  const cap = (p: string): number => Math.max(1, atOnce?.get(p) ?? 1);
  const rank = (i: QueueItem): number => maps.indexOf(itemMapKey(i));
  let left = all.filter((i) => i.state === "queued");
  const waiting = new Set(left.map((i) => i.key));
  for (let k = 0; left.length > 0; k += 1) {
    const before = (key: string): boolean => !waiting.has(key) || (row.get(key) ?? Infinity) < k;
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
  return { row, lane };
}

interface Span {
  from: number;
  to: number;
}
/**
 * Time -> y: ROW_H per SLOT from t0, except that each stretch over LONG_EMPTY that no span covers is drawn one slot
 * tall (so a box that ended just before it never pushes the next one sideways). Returns the stretches too.
 */
function timeline(spans: readonly Span[], t0: number): { yAt: (t: number) => number; breaks: Span[] } {
  const breaks: Span[] = [];
  let end = -Infinity;
  for (const s of [...spans].sort((a, b) => a.from - b.from)) {
    if (end > -Infinity && s.from - end > LONG_EMPTY) breaks.push({ from: end, to: s.from });
    end = Math.max(end, s.to);
  }
  const yAt = (t: number): number => {
    let v = t - t0;
    for (const g of breaks) {
      const len = g.to - g.from;
      if (t >= g.to) v -= len - SLOT;
      else if (t > g.from) v -= (t - g.from) * (1 - SLOT / len);
    }
    return HEAD + (ROW_H * v) / SLOT;
  };
  return { yAt, breaks };
}

/** The local half hours (:00 and :30) after `from` up to `to`, as seconds. */
function slotsBetween(from: number, to: number): number[] {
  const d = new Date(from * 1000);
  d.setMinutes(d.getMinutes() < 30 ? 0 : 30, 0, 0);
  const out: number[] = [];
  for (d.setMinutes(d.getMinutes() + 30); d.getTime() / 1000 <= to && out.length < 2000; d.setMinutes(d.getMinutes() + 30)) out.push(d.getTime() / 1000);
  return out;
}

/** How long a run took, in words: "25 min", "1 h 5 min". */
export function took(secs: number): string {
  const m = Math.max(1, Math.round(secs / 60));
  if (m < 60) return `${String(m)} min`;
  return m % 60 === 0 ? `${String(m / 60)} h` : `${String(Math.floor(m / 60))} h ${String(m % 60)} min`;
}

/** A box's second line: where it is, and for a finished run how long it took. */
export function footOf(i: QueueItem, p: number | null): string {
  if (p !== null) return `${STATE_WORDS[i.state]} ${String(p)}`;
  const words = i.runner === CHAT_RUNNER ? (i.state === "running" ? "In a chat" : i.state === "done" ? "Done in a chat" : "A chat stopped, still open") : landedShort(i) ? "Landed, needs your look" : i.kind === "ticket" && i.handed ? `To integrate · ${i.handed.to}` : STATE_WORDS[i.state];
  return i.started != null && i.ended != null && i.ended > i.started ? `${words} · ${took(i.ended - i.started)}` : words;
}

export function nightGraph(input: NightInput): NightGraph {
  const { info, scope, maps } = input;
  const hidden = input.hidden ?? new Set<string>();
  // one box per key; a key the queue holds twice shows its latest
  const latest = new Map<string, QueueItem>();
  for (const i of input.items) latest.set(i.key, i);
  const all = [...latest.values()];
  const after = (k: string): string[] => (info.tickets.get(k)?.after ?? []).filter((a) => a !== k && latest.has(a));
  // the rows to come come from the whole run, so a project or map left out still takes the turns it takes
  const plan = queueRows(all, maps, after, input.atOnce);

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
      foot: footOf(i, p),
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

  // the graph: what the chips leave shown
  const shown = scoped.filter((i) => !hidden.has(itemMapKey(i)));
  const prevCols = input.prev?.cols ?? [];
  const projects = [...new Set([...prevCols, ...mapOrder.map(projOf), ...shown.map(projectOf)])].filter((p) => shown.some((i) => projectOf(i) === p));
  const phaseOf = (i: QueueItem): Phase => (i.state === "running" ? "now" : i.state === "queued" ? "next" : "ran");
  const live = shown.some((i) => phaseOf(i) !== "ran");

  // what ran and runs: at its start on the timeline, measured from the night's first start
  const t = input.now ?? Date.now() / 1000;
  const started = shown.filter((i) => phaseOf(i) !== "next");
  const startAt = (i: QueueItem): number | null => i.started ?? i.ended ?? (i.state === "running" ? t : null);
  const known = started.map(startAt).filter((s): s is number => s !== null);
  // a clock behind a start still draws the now line below it
  const nowT = Math.max(t, ...known);
  const t0 = known.length > 0 ? Math.min(...known) : nowT;
  const spanOf = (i: QueueItem): Span => {
    // a ticket with no time at all (stopped before it started) sits at the night's start
    const from = startAt(i) ?? t0;
    return { from, to: i.state === "running" ? nowT : Math.max(from, i.ended ?? from) };
  };
  const spans = new Map(started.map((i) => [i.key, spanOf(i)]));
  const { yAt, breaks } = timeline([...spans.values(), ...(live ? [{ from: nowT, to: nowT }] : [])], t0);

  // a lane per box, in start order: the one it had if still free, else the first free one; the boxes that had a lane
  // go first, so one that shows up late with an earlier start never pushes them over. A box holds its lane from its
  // top down to its bottom or its run's end, whichever is lower, plus a gap.
  const prevSlots = input.prev?.slots ?? new Map<string, number>();
  const slots = new Map(prevSlots);
  const where = new Map<string, { y: number; lane: number; h: number }>();
  const taken = new Map<string, Span[][]>();
  let lowest = -Infinity;
  const byStart = [...started].sort((a, b) => (spans.get(a.key)?.from ?? 0) - (spans.get(b.key)?.from ?? 0));
  for (const i of [...byStart.filter((o) => prevSlots.has(o.key)), ...byStart.filter((o) => !prevSlots.has(o.key))]) {
    const s = spans.get(i.key) ?? { from: t0, to: t0 };
    const top = yAt(s.from);
    const bottom = Math.max(top + NODE_H, yAt(s.to));
    const col = taken.get(projectOf(i)) ?? [];
    taken.set(projectOf(i), col);
    const fits = (l: number): boolean => (col[l] ?? []).every((o) => top >= o.to + GAP - 0.5 || bottom + GAP <= o.from + 0.5);
    let l = prevSlots.get(i.key);
    if (l === undefined || !fits(l)) {
      l = 0;
      while (!fits(l)) l += 1;
    }
    (col[l] ??= []).push({ from: top, to: bottom });
    where.set(i.key, { y: top, lane: l, h: bottom - top });
    slots.set(i.key, l);
    lowest = Math.max(lowest, bottom);
  }
  const nowY = live ? yAt(nowT) : null;

  // what is queued: below the now line, a row at a time; a row nothing shown sits in drops out
  const qRows = [...new Set(shown.filter((i) => phaseOf(i) === "next").map((i) => plan.row.get(i.key) ?? 0))].sort((a, b) => a - b);
  const qTop = nowY === null ? 0 : Math.max(nowY + ROW_H / 2, lowest + GAP);
  const qY = (o: number): number => qTop + Math.max(0, qRows.indexOf(o)) * ROW_H;
  for (const i of shown) if (phaseOf(i) === "next") where.set(i.key, { y: qY(plan.row.get(i.key) ?? 0), lane: plan.lane.get(i.key) ?? 0, h: NODE_H });

  const lanes = new Map(input.prev?.lanes ?? []);
  for (const i of shown) lanes.set(projectOf(i), Math.max(lanes.get(projectOf(i)) ?? 1, (where.get(i.key)?.lane ?? 0) + 1));
  const columns: NightColumn[] = [];
  let x = CLOCK_W;
  for (const p of projects) {
    const n = lanes.get(p) ?? 1;
    const w = n * NODE_W + (n - 1) * GAP;
    columns.push({ project: p, x, w });
    x += w + COL_GAP;
  }
  const colOf = new Map(columns.map((c) => [c.project, c]));
  const levels = [...new Set([...where.values()].map((w) => w.y))].sort((a, b) => a - b);
  const boxes: NightBox[] = shown.map((i) => {
    const { y, lane: l, h } = where.get(i.key) ?? { y: HEAD, lane: 0, h: NODE_H };
    return { ...cardOf(i), phase: phaseOf(i), row: levels.indexOf(y), lane: l, x: (colOf.get(projectOf(i))?.x ?? CLOCK_W) + l * (NODE_W + GAP), y, h };
  });

  // the clock: 'now', the night's first start and each start after a long empty stretch, every half hour between, and
  // about when each queued row would start, from the night's usual run; a label too close to a more telling one drops
  const runs = all.filter((i) => i.started != null && i.ended != null && i.state !== "skipped").map((i) => (i.ended ?? 0) - (i.started ?? 0)).sort((a, b) => a - b);
  // no ticket ended yet: the same rough 1.5 h a ticket the toolbar's end time counts with
  const usual = runs[Math.floor(runs.length / 2)] ?? ESTIMATE;
  const running = all.filter((i) => i.state === "running");
  const nextAt = Math.max(t, ...running.map((i) => (i.started ?? t) + usual));
  const labels: { at: number; clock: string; phase: Phase }[] = [];
  if (nowY !== null) labels.push({ at: nowY, clock: `now ${clock(t)}`, phase: "now" });
  if (started.length > 0) {
    labels.push({ at: yAt(t0), clock: clock(t0), phase: "ran" });
    for (const g of breaks) labels.push({ at: yAt(g.to), clock: clock(g.to), phase: "ran" });
    const end = Math.max(live ? nowT : t0, ...[...spans.values()].map((s) => s.to));
    for (const h of slotsBetween(t0, end)) if (!breaks.some((g) => h > g.from && h < g.to)) labels.push({ at: yAt(h), clock: clock(h), phase: "ran" });
  }
  for (const [n, o] of qRows.entries()) labels.push({ at: qTop + n * ROW_H, clock: `≈${clock(nextAt + o * usual)}`, phase: "next" });
  const kept: typeof labels = [];
  for (const l of labels) if (kept.every((k) => Math.abs(k.at - l.at) >= LABEL_APART)) kept.push(l);
  const rows: NightRow[] = kept.sort((a, b) => a.at - b.at).map((l, n) => ({ row: n, y: l.at - NODE_H / 2, clock: l.clock, phase: l.phase }));

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
      const last = boxes.filter((b) => b.project === c.project).sort((a, b) => b.y - a.y || b.lane - a.lane)[0];
      if (last !== undefined) edges.push({ id: `${last.id}>${DONE_ID}`, from: last.id, to: DONE_ID, across: false });
    }
    const finished = boxes.filter((b) => b.outcome !== null).length;
    const right = x - COL_GAP;
    const bottom = Math.max(...boxes.map((b) => b.y + b.h));
    done = { x: CLOCK_W + Math.max(0, (right - CLOCK_W - NODE_W) / 2), y: bottom + 2 * GAP, finished, total: boxes.length, line: `${String(finished)} of ${String(boxes.length)} finished` };
  }

  const counts = tally(scoped);
  return { frames, boxes, columns, rows, edges, nowY, done, counts, line: countsLine(counts), memo: { cols: [...new Set([...prevCols, ...projects])], lanes, slots } };
}

/** The point to centre on: the now line, under the tickets that run (else the ones queued); null when nothing does. */
/** How wide the whole graph is, its clock included: the view opens zoomed so all of it fits across. */
export function spanOf(g: Pick<NightGraph, "columns">): number {
  return Math.max(0, ...g.columns.map((c) => c.x + c.w));
}

export function focusOf(g: Pick<NightGraph, "boxes"> & Partial<Pick<NightGraph, "nowY">>): { x: number; y: number } | null {
  const run = g.boxes.filter((b) => b.phase === "now");
  const pick = run.length > 0 ? run : g.boxes.filter((b) => b.phase === "next");
  if (pick.length === 0) return null;
  const xs = pick.map((b) => b.x + NODE_W / 2);
  const ys = pick.map((b) => b.y + NODE_H / 2);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: g.nowY ?? Math.min(...ys) };
}
