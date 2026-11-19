/** The Map view's data: a map's tickets as graph nodes and arrows, laid out in layers. Pure: no React, no DOM. */
import dagre from "@dagrejs/dagre";
import type { MapRoute, MapTicket } from "@sb-hub/contract";

/** What a node's colour says. */
export const MAP_STATES = ["done", "running", "queued", "can run", "stuck", "decision", "no checks", "out of scope"] as const;
export type MapState = (typeof MAP_STATES)[number];

export const MAP_STATE_WORDS: Readonly<Record<MapState, string>> = {
  done: "Done",
  running: "Running",
  queued: "Queued",
  "can run": "Not queued",
  stuck: "Stuck behind another",
  decision: "Needs a decision",
  "no checks": "No checks",
  "out of scope": "Out of scope",
};

/** The one state a ticket shows, from the hub's words and the map's checks. */
export function mapState(t: Pick<MapTicket, "state" | "status" | "place">, hasChecks: boolean): MapState {
  if (t.state === "done" || t.status === "resolved") return "done";
  if (t.state === "out of scope" || t.status === "out-of-scope") return "out of scope";
  if (t.status === "claimed" || t.state === "claimed") return "running";
  if (t.place !== null) return "queued";
  if (t.state === "waits for you") return "decision";
  if (t.state === "blocked" || t.state === "not ready") return "stuck";
  return hasChecks ? "can run" : "no checks";
}

/** How many tickets of the map show each state; a blocker in another map is not one of them. */
export function stateCounts(nodes: readonly Pick<MapNode, "state" | "ticket">[]): Record<MapState, number> {
  const out = Object.fromEntries(MAP_STATES.map((s) => [s, 0])) as Record<MapState, number>;
  for (const n of nodes) if (n.ticket !== null) out[n.state] += 1;
  return out;
}

/** The state picked in the page link, or null when the link names none. */
export const pickedState = (ms: string): MapState | null => MAP_STATES.find((s) => s === ms) ?? null;

/** A picked state dims every box of another state, and every blocker elsewhere; nothing picked dims nothing. */
export const dimmed = (n: Pick<MapNode, "state" | "ticket">, pick: MapState | null): boolean => pick !== null && (n.ticket === null || n.state !== pick);

/** Whole minutes a run has taken so far; null when it has no start. */
export const minutesOf = (started: number | null | undefined, now: number): number | null => (started == null ? null : Math.max(0, Math.floor((now - started) / 60)));

export const NODE_W = 220;
export const NODE_H = 68;

export interface MapNode {
  /** `<num>` for a ticket of this map; `x:<map>#<num>` for a blocker elsewhere. */
  id: string;
  /** The ticket, or null for a blocker in another map. */
  ticket: MapTicket | null;
  title: string;
  state: MapState;
  /** The map a blocker lives in; "" for a ticket of this map. */
  other: string;
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface MapEdge {
  id: string;
  /** The blocker, and the ticket that comes after it. */
  from: string;
  to: string;
}
export interface MapLayout {
  nodes: MapNode[];
  edges: MapEdge[];
  width: number;
  height: number;
}

/** Nodes at their top-left corner, in layers from the first tickets down; one arrow per "after". */
export function layoutMap(route: Pick<MapRoute, "map" | "checks" | "tickets">, across = false): MapLayout {
  const own = new Set(route.tickets.map((t) => t.num));
  const hasChecks = route.checks.length > 0;
  const nodes = new Map<string, MapNode>();
  const edges: MapEdge[] = [];
  const put = (n: Omit<MapNode, "x" | "y" | "w" | "h">): void => {
    nodes.set(n.id, { ...n, x: 0, y: 0, w: NODE_W, h: NODE_H });
  };
  for (const t of route.tickets) put({ id: String(t.num), ticket: t, title: t.title, state: mapState(t, hasChecks), other: "" });
  for (const t of route.tickets) {
    for (const b of t.blocked_by) {
      const inside = b.map === route.map && b.num !== null && own.has(b.num);
      const id = inside ? String(b.num) : `x:${b.map}${b.num === null ? "" : `#${String(b.num)}`}`;
      if (!nodes.has(id)) put({ id, ticket: null, title: b.title, state: b.status === "resolved" ? "done" : "stuck", other: b.map });
      if (id !== String(t.num) && !edges.some((e) => e.from === id && e.to === String(t.num))) edges.push({ id: `${id}>${String(t.num)}`, from: id, to: String(t.num) });
    }
  }
  const g = new dagre.graphlib.Graph();
  // vertical: what comes after sits below; horizontal (the graph layout setting): to the right
  g.setGraph({ rankdir: across ? "LR" : "TB", nodesep: 24, ranksep: across ? 64 : 48, marginx: 16, marginy: 16 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes.values()) g.setNode(n.id, { width: n.w, height: n.h });
  for (const e of edges) g.setEdge(e.from, e.to);
  dagre.layout(g);
  let width = 0;
  let height = 0;
  for (const n of nodes.values()) {
    const p = g.node(n.id) as { x: number; y: number };
    n.x = Math.round(p.x - n.w / 2);
    n.y = Math.round(p.y - n.h / 2);
    width = Math.max(width, n.x + n.w);
    height = Math.max(height, n.y + n.h);
  }
  return { nodes: [...nodes.values()], edges, width: width + 16, height: height + 16 };
}

/**
 * The tickets of this map on one side of a node along the arrows, the node itself included: "before" is everything it
 * comes after (its blockers, and theirs), "after" everything that comes after it. A blocker in another map is not a
 * ticket here and is left out. Returns the ticket keys (`<map>#<num>`).
 */
export function reachKeys(layout: Pick<MapLayout, "nodes" | "edges">, map: string, id: string, way: "before" | "after"): string[] {
  const seen = new Set<string>([id]);
  const todo = [id];
  for (let at = todo.pop(); at !== undefined; at = todo.pop()) {
    for (const e of layout.edges) {
      const next = way === "before" ? (e.to === at ? e.from : null) : e.from === at ? e.to : null;
      if (next !== null && !seen.has(next)) {
        seen.add(next);
        todo.push(next);
      }
    }
  }
  return layout.nodes.filter((n) => seen.has(n.id) && n.ticket !== null).map((n) => `${map}#${String(n.ticket?.num ?? 0)}`);
}

/** The head's one line of counts: '3 done · 1 running · 2 can run'. Zeros are left out; tickets without checks are named last. */
export function countsLine(c: Readonly<Record<MapState, number>>): string {
  const parts: [number, string][] = [[c.done, "done"], [c.running, "running"], [c.queued, "queued"], [c["can run"], "can run"], [c.stuck, "stuck"], [c.decision, "need a decision"], [c["no checks"], "without checks"]];
  const out = parts.filter(([n]) => n > 0).map(([n, w]) => `${String(n)} ${w}`);
  return out.length === 0 ? "No tickets" : out.join(" · ");
}

/** What 'Queue this map' would take: tickets that can run now, and the ones that wait on an earlier ticket of the map. */
export const queueable = (c: Readonly<Record<MapState, number>>): number => c["can run"] + c.stuck;

/** The map's runs that ended on the local day of `now` (seconds): how many ended done and how many fell short. Null when none ran. */
export function ranToday(tickets: readonly Pick<MapTicket, "last_run">[], now: number): { done: number; short: number } | null {
  const d = new Date(now * 1000);
  const from = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
  const runs = tickets.flatMap((t) => (t.last_run?.ended != null && t.last_run.ended >= from ? [t.last_run] : []));
  if (runs.length === 0) return null;
  const done = runs.filter((r) => r.state === "done").length;
  return { done, short: runs.length - done };
}
