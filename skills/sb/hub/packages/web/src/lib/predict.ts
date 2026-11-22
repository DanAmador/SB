/**
 * The queue a write will most likely leave, drawn before the hub answers so the page moves at once. The hub's answer
 * replaces it either way: a guess only has to be close (a move the hub clamps behind a blocker lands there a moment
 * later). null: no good guess, the page waits for the hub as before.
 */
import type { Queue, QueueItem, RouteBody, TicketItem } from "@sb-hub/contract";

/** Every queue write the page sends. */
export type QueueRoute =
  | "POST /api/queue/set"
  | "POST /api/queue/move"
  | "POST /api/queue/map"
  | "POST /api/queue/move_map"
  | "POST /api/queue/pause"
  | "POST /api/queue/agents"
  | "POST /api/queue/parallel"
  | "POST /api/queue/options"
  | "POST /api/queue/job"
  | "POST /api/queue/remove_job"
  | "POST /api/queue/stop"
  | "POST /api/queue/item_agent";

type Body<K extends QueueRoute> = RouteBody<K>;

const isQueuedTicket = (i: QueueItem): i is TicketItem => i.kind === "ticket" && i.state === "queued";
const mapOf = (key: string): string => (key.includes("#") ? key.slice(0, key.lastIndexOf("#")) : key);
const clamp = (n: number, hi: number): number => Math.max(0, Math.min(n, hi));

/** `items` with the queued tickets replaced by `queued`, in the places the queued tickets had (the rest stay put);
 * more of them go last, fewer leave places empty. */
function withQueued(items: readonly QueueItem[], queued: readonly TicketItem[]): QueueItem[] {
  const next = [...queued];
  const out: QueueItem[] = [];
  for (const i of items) {
    if (!isQueuedTicket(i)) out.push(i);
    else {
      const n = next.shift();
      if (n !== undefined) out.push(n);
    }
  }
  return [...out, ...next];
}

function fresh(key: string): TicketItem {
  return {
    key,
    kind: "ticket",
    agent: null,
    state: "queued",
    note: "",
    commit: null,
    tries: 0,
    started: null,
    ended: null,
    links: { ticket: null, map: null, board: null, report: null, log: null },
  };
}

/** The selection becomes `keys`: what was queued keeps its order, a new ticket goes last in its map (or last). */
function select(q: Queue, keys: readonly string[]): Queue | null {
  const want = new Set(keys);
  const queued = q.items.filter(isQueuedTicket);
  const kept = queued.filter((i) => want.has(i.key));
  const have = new Map(q.items.filter((i): i is TicketItem => i.kind === "ticket").map((i) => [i.key, i]));
  const again = new Set<string>();
  const seq = [...kept];
  for (const k of new Set(keys)) {
    if (seq.some((i) => i.key === k)) continue;
    const old = have.get(k);
    // a running or finished ticket is never queued twice; a failed or skipped one is queued afresh
    if (old !== undefined && old.state !== "failed" && old.state !== "skipped") continue;
    if (old !== undefined) again.add(k);
    const item: TicketItem = old === undefined ? fresh(k) : { ...fresh(k), agent: old.agent, links: old.links };
    const m = mapOf(k);
    const end = seq.reduce((at, i, n) => (mapOf(i.key) === m ? n + 1 : at), seq.length);
    seq.splice(end, 0, item);
  }
  const items = withQueued(q.items.filter((i) => !again.has(i.key)), seq);
  return { ...q, items };
}

/** The queue after `route` with `body`, as the hub will most likely answer it; null when there is no good guess. */
export function predictQueue<K extends QueueRoute>(q: Queue, route: K, body: RouteBody<K>): Queue | null {
  const r: QueueRoute = route;
  const raw: unknown = body;
  switch (r) {
    case "POST /api/queue/pause": {
      const b = raw as Body<typeof r>;
      if (b.paused) return { ...q, paused: true };
      const rest: Queue = { ...q, paused: false };
      delete rest.note;
      return rest;
    }
    case "POST /api/queue/move": {
      const b = raw as Body<typeof r>;
      const queued = q.items.filter(isQueuedTicket);
      const it = queued.find((i) => i.key === b.key);
      if (it === undefined) return null;
      const rest = queued.filter((i) => i !== it);
      rest.splice(clamp(b.to, rest.length), 0, it);
      return { ...q, items: withQueued(q.items, rest) };
    }
    case "POST /api/queue/move_map": {
      const b = raw as Body<typeof r>;
      if (!q.maps?.includes(b.map)) return null;
      const maps = q.maps.filter((m) => m !== b.map);
      maps.splice(clamp(b.to, maps.length), 0, b.map);
      const place = new Map(maps.map((m, n) => [m, n]));
      const rank = (i: TicketItem): number => place.get(mapOf(i.key)) ?? maps.length;
      // the hub keeps the queued tickets map by map, each in its place inside its map
      const queued = q.items.filter(isQueuedTicket).map((i, n) => ({ i, n }));
      queued.sort((a, b2) => rank(a.i) - rank(b2.i) || a.n - b2.n);
      return { ...q, maps, items: withQueued(q.items, queued.map((x) => x.i)) };
    }
    case "POST /api/queue/set":
      return select(q, (raw as Body<typeof r>).keys);
    case "POST /api/queue/remove_job": {
      const b = raw as Body<typeof r>;
      const it = q.items.find((i) => i.key === b.key);
      if (it?.kind !== "job" || it.state !== "queued") return null;
      return { ...q, items: q.items.filter((i) => i !== it) };
    }
    case "POST /api/queue/stop": {
      const b = raw as Body<typeof r>;
      const words = b.reason.split(/\s+/).filter(Boolean).join(" ");
      if (!q.items.some((i) => i.key === b.key && i.state === "running")) return null;
      const items = q.items.map((i) =>
        i.key === b.key ? { ...i, stop_asked: { reason: words, at: Date.now() / 1000 }, note: `stopping, by you: ${words}` } : i,
      );
      return { ...q, items };
    }
    case "POST /api/queue/item_agent": {
      const b = raw as Body<typeof r>;
      if (!q.items.some((i) => i.key === b.key && i.state === "queued")) return null;
      const items = q.items.map((i): QueueItem => {
        if (i.key !== b.key || i.state !== "queued") return i;
        const named = b.name !== undefined ? { ...i, agent: b.name } : i;
        return b.model !== undefined && named.tries === 0 ? { ...named, model: b.model } : named;
      });
      return { ...q, items };
    }
    case "POST /api/queue/agents": {
      const names = [...new Set((raw as Body<typeof r>).names)];
      return { ...q, agents: names, agent: names[0] ?? q.agent };
    }
    case "POST /api/queue/parallel": {
      const b = raw as Body<typeof r>;
      const repos = q.repos ?? {};
      const load = repos[b.repo] ?? { running: 0, side_by_side: 0, at_once: b.n };
      return { ...q, repos: { ...repos, [b.repo]: { ...load, at_once: b.n } } };
    }
    case "POST /api/queue/options": {
      const b = raw as Body<typeof r>;
      return { ...q, stop_at: b.stop_at ?? null, final_review: b.final_review ?? false };
    }
    // which of a map's tickets can run, and a new job's whole row, are the hub's to say
    case "POST /api/queue/map":
    case "POST /api/queue/job":
      return null;
  }
}
