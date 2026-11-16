/**
 * The run's graph: every ticket the queue holds (queued, running, in checks, waiting for its second pass, or ended and
 * not cleared) as boxes, one frame per map in the hub's map order and one for jobs, an arrow for each "after", also
 * across frames. Pure: no React, no DOM. A box keeps the place it first got, so an update moves nothing that stays.
 */
import type { MapRoute, QueueItem, TicketRow } from "@sb-hub/contract";
import { itemInScope, itemMapKey, itemTitle, mapTitle, type Scope } from "./board.ts";
import { mapState, NODE_H, NODE_W, type MapState } from "./map.ts";

export const GAP = 24;
export const PAD = 16;
/** The frame's title and counts line. */
export const HEAD = 56;
/** Boxes side by side in a frame before a row wraps. */
export const WRAP = 4;
export const MIN_W = 260;
export const JOBS = "Jobs";

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

/** Where a box sits in its frame: its rank (layer) and its number among that rank's boxes. */
export interface Slot {
  readonly rank: number;
  readonly idx: number;
}

export interface NightBox {
  id: string;
  frame: string;
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
  /** Relative to its frame. */
  x: number;
  y: number;
}
export interface NightFrame {
  id: string;
  /** The map it stands for; "" for the Jobs frame, which picks nothing. */
  map: string;
  title: string;
  line: string;
  counts: Counts;
  x: number;
  y: number;
  w: number;
  h: number;
  boxes: NightBox[];
}
export interface NightEdge {
  id: string;
  from: string;
  to: string;
  /** From one frame to another. */
  across: boolean;
}
export interface NightGraph {
  frames: NightFrame[];
  edges: NightEdge[];
  counts: Counts;
  line: string;
  /** Every box's place, to hand to the next build so the boxes that stay do not move. */
  slots: ReadonlyMap<string, Slot>;
}

export interface NightInput {
  /** The queue's items, finished ones kept until the run is cleared. */
  items: readonly QueueItem[];
  /** The queued maps in the hub's order. */
  maps: readonly string[];
  info: { tickets: ReadonlyMap<string, TicketInfo>; maps: ReadonlyMap<string, string> };
  scope: Scope;
  prev?: ReadonlyMap<string, Slot> | undefined;
}

/** Boxes' ranks: one more than the deepest box they come after inside the frame. */
function ranks(ids: readonly string[], after: ReadonlyMap<string, readonly string[]>): Map<string, number> {
  const inside = new Set(ids);
  const rank = new Map<string, number>();
  const depth = (id: string, seen: ReadonlySet<string>): number => {
    const known = rank.get(id);
    if (known !== undefined) return known;
    const next = new Set(seen).add(id);
    const r = Math.max(-1, ...(after.get(id) ?? []).filter((a) => inside.has(a) && !next.has(a)).map((a) => depth(a, next))) + 1;
    rank.set(id, r);
    return r;
  };
  for (const id of ids) depth(id, new Set());
  return rank;
}

export function nightGraph(input: NightInput): NightGraph {
  const { info, scope, prev } = input;
  // one box per key; a key the queue holds twice shows its latest
  const latest = new Map<string, QueueItem>();
  for (const i of input.items) if (itemInScope(scope, i)) latest.set(i.key, i);
  const items = [...latest.values()];
  const place = new Map(items.filter((i) => i.state === "queued").map((i, n) => [i.key, n + 1]));

  // the frames: the hub's map order, then any other map as it first shows, then the jobs
  const mapsSeen = [...input.maps, ...items.filter((i) => i.kind !== "job").map(itemMapKey)];
  const order = [...new Set(mapsSeen)].filter((m) => items.some((i) => i.kind !== "job" && itemMapKey(i) === m));
  const groups: { id: string; map: string; title: string; items: QueueItem[] }[] = order.map((m) => ({
    id: `f:${m}`,
    map: m,
    title: input.info.maps.get(m) ?? (m.split("/").pop() ?? m),
    items: items.filter((i) => i.kind !== "job" && itemMapKey(i) === m),
  }));
  const jobs = items.filter((i) => i.kind === "job");
  if (jobs.length > 0) groups.push({ id: "f:jobs", map: "", title: JOBS, items: jobs });

  const after = new Map<string, readonly string[]>();
  for (const i of items) after.set(i.key, info.tickets.get(i.key)?.after ?? []);

  const slots = new Map<string, Slot>();
  const frames: NightFrame[] = [];
  let top = 0;
  for (const g of groups) {
    const rank = ranks(g.items.map((i) => i.key), after);
    const used = new Map<number, number>();
    const next = (r: number): number => {
      const n = used.get(r) ?? 0;
      used.set(r, n + 1);
      return n;
    };
    // boxes that already had a place keep it; the rest take the next free one in their rank
    const kept = g.items.filter((i) => prev?.has(i.key) === true);
    for (const i of kept) {
      const s = prev?.get(i.key);
      if (s === undefined) continue;
      slots.set(i.key, s);
      used.set(s.rank, Math.max(used.get(s.rank) ?? 0, s.idx + 1));
    }
    for (const i of g.items) if (!slots.has(i.key)) { const r = rank.get(i.key) ?? 0; slots.set(i.key, { rank: r, idx: next(r) }); }

    // a rank wider than WRAP wraps onto rows of its own
    const widths = new Map<number, number>();
    for (const i of g.items) {
      const s = slots.get(i.key);
      if (s) widths.set(s.rank, Math.max(widths.get(s.rank) ?? 0, s.idx + 1));
    }
    const rows = new Map<number, number>();
    let row = 0;
    for (const r of [...widths.keys()].sort((a, b) => a - b)) {
      rows.set(r, row);
      row += Math.ceil((widths.get(r) ?? 1) / WRAP);
    }
    const cols = Math.max(1, ...[...widths.values()].map((w) => Math.min(w, WRAP)));
    const boxes: NightBox[] = g.items.map((i) => {
      const s = slots.get(i.key) ?? { rank: 0, idx: 0 };
      const p = place.get(i.key) ?? null;
      const state = boxState(i, p);
      const out = outcomeOf(i);
      const title = info.tickets.get(i.key)?.title ?? itemTitle(i, null);
      return {
        id: i.key,
        frame: g.id,
        item: i,
        title,
        state,
        foot: p !== null ? `${STATE_WORDS[i.state]} ${String(p)}` : STATE_WORDS[i.state],
        place: p,
        outcome: out,
        report: out !== null ? i.links.report : null,
        x: PAD + (s.idx % WRAP) * (NODE_W + GAP),
        y: HEAD + ((rows.get(s.rank) ?? 0) + Math.floor(s.idx / WRAP)) * (NODE_H + GAP),
      };
    });
    const counts = tally(g.items);
    const w = Math.max(MIN_W, PAD * 2 + cols * NODE_W + (cols - 1) * GAP);
    const h = HEAD + row * (NODE_H + GAP) - GAP + PAD;
    frames.push({ id: g.id, map: g.map, title: g.title, line: countsLine(counts), counts, x: 0, y: top, w, h, boxes });
    top += h + 2 * GAP;
  }

  const frameOf = new Map(frames.flatMap((f) => f.boxes.map((b) => [b.id, f.id] as const)));
  const edges: NightEdge[] = [];
  for (const i of items) {
    for (const a of after.get(i.key) ?? []) {
      const from = frameOf.get(a);
      const to = frameOf.get(i.key);
      if (from === undefined || to === undefined || a === i.key) continue;
      const id = `${a}>${i.key}`;
      if (!edges.some((e) => e.id === id)) edges.push({ id, from: a, to: i.key, across: from !== to });
    }
  }
  const counts = tally(items);
  return { frames, edges, counts, line: countsLine(counts), slots };
}

/** The key of the box to centre on: the first ticket that runs now, else the first that is queued, else null. */
export function focusOf(g: NightGraph): { x: number; y: number } | null {
  const boxes = g.frames.flatMap((f) => f.boxes.map((b) => ({ f, b })));
  const run = boxes.filter(({ b }) => b.item.state === "running");
  const pick = run.length > 0 ? run : boxes.filter(({ b }) => b.item.state === "queued");
  if (pick.length === 0) return null;
  const xs = pick.map(({ f, b }) => f.x + b.x + NODE_W / 2);
  const ys = pick.map(({ f, b }) => f.y + b.y + NODE_H / 2);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2 };
}
