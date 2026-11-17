/** The Run tab's grouping: the night map by map. Pure: no React, no DOM. */
import type { AgentRow, Night as NightRecord, Queue, QueueItem, State, Waits } from "@sb-hub/contract";
import { countsLine as itemCounts, tally } from "./nightGraph.ts";
import { IDLE, type SessionCard } from "./sessions.ts";
import { agentOf, CHAT_RUNNER, dur, landedShort, endedToday, itemInScope, itemMap, mapTitle, projOf, type Scope, type TicketIndex, itemProject, EVERYTHING } from "./board.ts";

/** What a row's mark says. */
export type Mark = "done" | "landed" | "running" | "checking" | "next" | "short" | "stopped" | "recheck" | "unclean";

export const MARK_WORDS: Readonly<Record<Mark, string>> = {
  done: "done",
  landed: "landed, needs your look",
  running: "running",
  checking: "in checks or second pass",
  next: "next",
  short: "fell short",
  stopped: "stopped",
  recheck: "check could not run",
  unclean: "waits for a clean checkout",
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
  readonly line: { readonly running: number; readonly next: number; readonly done: number; readonly landed: number; readonly short: number; readonly stopAt: number | null };
  readonly blocks: readonly NightBlock[];
  /** The queued maps in run order (what move_map counts places in). */
  readonly queuedMaps: readonly string[];
}

const ORDER: readonly Mark[] = ["done", "landed", "running", "checking", "recheck", "unclean", "next", "short", "stopped"];
const WORDS: Readonly<Record<Mark, string>> = { done: "done", landed: "landed, need your look", running: "running", checking: "checking", recheck: "check could not run", unclean: "waits for a clean checkout", next: "next", short: "fell short", stopped: "stopped" };

export function markOf(i: QueueItem): Mark {
  switch (i.state) {
    case "queued": return "next";
    case "running": return "running";
    case "landed":
    case "review": return "checking";
    case "recheck": return "recheck";
    case "unclean": return "unclean";
    case "done": return "done";
    case "skipped": return "stopped";
    default: return landedShort(i) ? "landed" : "short";
  }
}

export function countsLine(c: Readonly<Record<Mark, number>>): string {
  return ORDER.filter((m) => c[m] > 0).map((m) => `${String(c[m])} ${WORDS[m]}`).join(" · ");
}

const GROUP_ORDER: Readonly<Record<Mark, number>> = { done: 0, landed: 0, short: 0, stopped: 0, running: 1, checking: 1, recheck: 2, unclean: 2, next: 3 };

/** Every map with something running, queued or ended today, in the hub's map order; then Jobs. */
export function nightBlocks(state: State, ix: TicketIndex, scope: Scope = EVERYTHING, wholeRun = false): Night {
  const q = state.queue;
  const queued = q.items.filter((i) => i.state === "queued");
  const place = new Map(queued.map((i, n) => [i.key, n + 1] as const));
  const live = q.items.filter((i) => ["queued", "running", "landed", "review", "recheck", "unclean"].includes(i.state));
  // a live run keeps what it finished before midnight; the hub's old line keeps what ended today
  const ended = wholeRun ? q.items.filter((i) => i.state === "done" || i.state === "failed" || i.state === "skipped") : endedToday(state);
  const all = [...live, ...ended].filter((i) => itemInScope(scope, i));
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
      open: counts.running + counts.checking + counts.landed + counts.short + counts.recheck > 0,
      at: queuedMaps.indexOf(map),
    };
  });
  const sum = (m: Mark): number => blocks.reduce((n, b) => n + b.counts[m], 0);
  return {
    line: { running: sum("running") + sum("checking"), next: sum("next"), done: sum("done"), landed: sum("landed"), short: sum("short"), stopAt: q.stop_at ?? null },
    blocks,
    queuedMaps,
  };
}

/** The one line for the night: '1 running · 4 next · 3 done · 1 fell short'. */
export function nightLine(n: Night): string {
  const l = n.line;
  return [`${String(l.running)} running`, `${String(l.next)} next`, `${String(l.done)} done`, ...(l.landed > 0 ? [`${String(l.landed)} landed, need your look`] : []), `${String(l.short)} fell short`].join(" · ");
}

// ---- who is on each ticket ----

/** A worker or a session is live, silent for 5 minutes or more, or ended. */
export type Health = "live" | "silent" | "ended";
export const healthOf = (c: SessionCard): Health => (c.agent.state === "done" ? "ended" : c.silent ? "silent" : "live");

export interface MapPair {
  /** The session in charge of the map, or null: the queue runs it. */
  readonly charge: SessionCard | null;
  /** 'name · state · quiet 4m', or 'run by the queue'. */
  readonly head: string;
  /** The worker on each ticket row, by queue key. */
  readonly workers: ReadonlyMap<string, SessionCard>;
  /** What the session in charge started that belongs to no ticket of the block. */
  readonly helpers: readonly SessionCard[];
}

export interface ChatPair {
  readonly chat: SessionCard;
  readonly helpers: readonly SessionCard[];
}

export interface Pairing {
  /** By block (the map, "" for Jobs). */
  readonly maps: ReadonlyMap<string, MapPair>;
  /** Chats in charge of no map shown above, each with its helpers. */
  readonly chats: readonly ChatPair[];
  /** How many of those chats are live (not idle). */
  readonly liveChats: number;
}

export const QUEUE_HEAD = "run by the queue";

/**
 * Pairs the night's rows with who is on them. `cards` are the queue workers and chats (sessionCards), `helpers` what
 * each chat started (helperCards). The session in charge of a map is the hub's `charge`, else a chat that reports the map.
 */
export function pairNight(state: State, night: Night, cards: readonly SessionCard[], helpers: ReadonlyMap<string, readonly SessionCard[]>): Pairing {
  const byId = new Map(cards.map((c) => [c.id, c] as const));
  const chats = cards.filter((c) => c.kind === "chat");
  const chargeOf = (map: string): SessionCard | null => {
    if (map === "") return null;
    const id = state.charge?.[map];
    const a = id === undefined ? null : agentOf(state, id);
    const named = a === null ? undefined : byId.get(a.agent);
    return named?.kind === "chat" ? named : (chats.find((c) => c.agent.map === map && c.agent.state !== "done") ?? null);
  };
  const used = new Set<string>();
  const maps = new Map<string, MapPair>();
  for (const b of night.blocks) {
    const charge = chargeOf(b.map);
    const keys = new Set(b.rows.map((r) => r.item.key));
    const workers = new Map<string, SessionCard>();
    for (const r of b.rows) {
      const w = byId.get(agentOf(state, r.item.key)?.agent ?? r.item.key);
      if (w?.kind === "worker") workers.set(r.item.key, w);
    }
    if (charge !== null) used.add(charge.id);
    maps.set(b.map, {
      charge,
      head: charge === null ? QUEUE_HEAD : `${charge.title} · ${charge.agent.state ?? "working"} · quiet ${dur(charge.quiet)}`,
      workers,
      helpers: charge === null ? [] : (helpers.get(charge.id) ?? []).filter((h) => !keys.has(h.id) && !(h.agent.ticket !== undefined && keys.has(h.agent.ticket))),
    });
  }
  const others = chats.filter((c) => !used.has(c.id) && c.agent.state !== "done").map((chat) => ({ chat, helpers: helpers.get(chat.id) ?? [] }));
  return { maps, chats: others, liveChats: others.filter((o) => !o.chat.idle).length };
}

// ---- the live run: what the Run tab shows, and nothing of an ended one ----

/**
 * The items of the live run: those that carry its id. A close-off job belongs to no run, an ended run's items are
 * off the line. A hub that knows no runs (queue.night absent) keeps every item.
 */
export function liveItems(queue: Pick<State["queue"], "items" | "night">, chats?: Pick<State, "agents" | "now" | "chat_runs">): QueueItem[] {
  const hub = queue.night === undefined ? queue.items : queue.night === null ? [] : queue.items.filter((i) => i.night === queue.night);
  if (chats === undefined || queue.night === null) return hub;
  return withChats(hub, chatItems(chats, queue.night));
}

/**
 * A run's items with the chats' work on it: a ticket the queue holds keeps the queue's item, unless the queue ended it
 * and a chat works on it now (then the chat's shows). A ticket only a chat touched is added, ended or not.
 */
export function withChats(hub: readonly QueueItem[], chats: readonly QueueItem[]): QueueItem[] {
  const keys = new Set(hub.map((i) => i.key));
  const busy = new Set(hub.filter((i) => !ENDED.has(i.state)).map((i) => i.key));
  const add = chats.filter((c) => !keys.has(c.key) || (c.state === "running" && !busy.has(c.key)));
  const taken = new Set(add.map((c) => c.key));
  return [...hub.filter((i) => !taken.has(i.key)), ...add];
}

const ENDED: ReadonlySet<QueueItem["state"]> = new Set(["done", "failed", "skipped"]);
/** What a chat that works on a ticket reports as, for it to count: working, and heard from in the last half hour. */
const CHAT_WORKING: ReadonlySet<string> = new Set(["working", "waiting", "needs you", "blocked"]);

/**
 * The owner's chats' work on tickets as items of a run (`night`; undefined: every run's), from the stretches the hub
 * keeps (chat_runs). A stretch runs while its chat still reports that ticket, working, heard from within IDLE; an
 * ended one is done when its ticket was resolved during it, else stopped with the ticket still open. One item per
 * ticket: a running stretch wins, else the latest. `runner` is "chat", which tells them from the queue's own.
 */
export function chatItems(s: Pick<State, "agents" | "now" | "chat_runs">, night: string | null | undefined): QueueItem[] {
  const out = new Map<string, QueueItem>();
  for (const r of s.chat_runs ?? []) {
    if (night !== undefined && (r.night ?? null) !== night) continue;
    const a: AgentRow | undefined = s.agents[r.agent];
    const live = a?.ref === r.key && CHAT_WORKING.has(a.state ?? "") && s.now - a.at < IDLE && s.now - r.last < IDLE;
    const item: QueueItem = {
      key: r.key, kind: "ticket", agent: r.agent, state: live ? "running" : r.closed === true ? "done" : "skipped",
      note: live ? (a.note ?? "") : r.closed === true ? "done in a chat" : "the chat stopped; the ticket is still open",
      commit: null, tries: 0, started: r.started, ended: live ? null : r.last, runner: CHAT_RUNNER,
      ...(r.night == null ? {} : { night: r.night }),
      links: { ticket: null, map: null, board: null, report: null, log: null },
    };
    const had = out.get(r.key);
    if (had === undefined || live || (had.state !== "running" && (had.started ?? 0) <= r.started)) out.set(r.key, item);
  }
  return [...out.values()];
}

/** The state the Run tab reads: the queue holds the live run's items, the chats' tickets among them, and no cleared log. */
export const liveState = (state: State): State => ({ ...state, queue: { ...state.queue, items: liveItems(state.queue, state), cleared: [] } });

/** The live run's items inside the sidebar's pick (Everything: all; a project: its maps'; a map: its own). */
export const runItems = (state: State, scope: Scope): QueueItem[] => liveItems(state.queue, state).filter((i) => itemInScope(scope, i));

/** The head's one line: '6 done · 2 running · 9 next · 1 fell short'. */
export const headLine = (items: readonly QueueItem[]): string => itemCounts(tally(items)) || "nothing queued yet";

/** What Stop run asks, once. A ticket not yet started will not be reached; what runs or waits for its judging finishes. */
export function stopAsk(items: readonly QueueItem[]): { running: number; notReached: number; text: string } {
  const running = items.filter((i) => ["running", "landed", "review", "recheck", "unclean"].includes(i.state)).length;
  const notReached = items.filter((i) => i.state === "queued").length;
  const t = (n: number): string => `${String(n)} ticket${n === 1 ? "" : "s"}`;
  return { running, notReached, text: `Let the ${String(running)} running ticket${running === 1 ? "" : "s"} finish, then end the run. ${t(notReached)} will not be reached.` };
}

/** While a run stops: the titles of what still runs, 'Stopping: waiting for A, B to finish'. */
export function stoppingWords(items: readonly QueueItem[], titleOf: (i: QueueItem) => string): string {
  const on = items.filter((i) => ["running", "landed", "review", "recheck", "unclean"].includes(i.state)).map(titleOf);
  return on.length === 0 ? "Stopping: ending the run." : `Stopping: waiting for ${on.join(", ")} to finish.`;
}

/** The record of the live (or stopping) run in the hub's list of runs. */
export const liveRecord = (nights: readonly NightRecord[], id: string | null | undefined): NightRecord | null => nights.find((n) => n.id === id && n.state !== "ended") ?? null;

/** The words for how a run ended. */
export const HOW_WORDS: Readonly<Record<string, string>> = { finished: "Finished", stopped: "Stopped by you", stop_time: "Stop time reached" };
export const stateWords = (n: Pick<NightRecord, "state" | "how">): string => (n.state === "live" ? "Live" : n.state === "stopping" ? "Stopping" : (HOW_WORDS[n.how ?? "finished"] ?? "Finished"));

// ---- why a queued item waits, and the limits the Run tab sets ----

/** A waiting item's reason in plain words. `name` turns a ticket key or a map into its title (the key itself when unknown). */
export function waitWords(w: Waits, name: (keyOrMap: string) => string): string {
  const who = w.with === null ? "" : name(w.with);
  switch (w.kind) {
    case "paused": return "the queue is paused";
    case "build": return `waits: ${w.text}`;
    case "time": return w.text.startsWith("starts at") ? `waits: ${w.text}` : `waits until ${w.text}`;
    case "after": return w.with === null ? w.text : w.with.includes("#") ? `waits for ${who}` : `waits for the map ${who}`;
    case "files": {
      const shared = /^shares (.+?) with /.exec(w.text)?.[1];
      return `waits for ${who}${shared === undefined ? "" : `: both change ${shared}`}`;
    }
    case "limit": {
      const n = /(\d+)/.exec(w.text)?.[1];
      return n === undefined ? w.text : `this repo runs ${n} at once`;
    }
    case "account": return w.text.startsWith("no account") ? w.text : `no account has room: ${w.text}`;
  }
}

/** One repo with work: its limit, what runs, and how many more could run beside them. */
export interface RepoLine {
  readonly repo: string;
  readonly name: string;
  readonly running: number;
  readonly atOnce: number;
  readonly more: number;
  readonly words: string;
}

export function repoLines(queue: Pick<Queue, "repos">): RepoLine[] {
  return Object.entries(queue.repos ?? {})
    .map(([repo, l]) => {
      const more = Math.max(0, Math.min(l.side_by_side, l.at_once - l.running));
      return { repo, name: repo.split("/").filter(Boolean).pop() ?? repo, running: l.running, atOnce: l.at_once, more, words: `${String(l.running)} running of ${String(l.at_once)} at once · ${String(more)} more could run side by side` };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** One account of the pool, and of those installed that are not in it: its two windows and whether it takes work. */
export interface AccountLine {
  readonly name: string;
  readonly inPool: boolean;
  /** 0 to 100, or null when no reading. */
  readonly five: number | null;
  readonly fiveResets: number | null;
  readonly week: number | null;
  readonly weekResets: number | null;
}

export function accountLines(state: Pick<State, "queue" | "installed" | "now">): AccountLine[] {
  const pool = new Set(state.queue.agents && state.queue.agents.length > 0 ? state.queue.agents : state.queue.agent !== null ? [state.queue.agent] : []);
  return Object.entries(state.installed).map(([name, e]) => {
    const u = e.usage;
    const five = u && (u.five_hour_resets ?? 0) > state.now ? u : null;
    const week = u && u.seven_day !== null && (u.seven_day_resets ?? 0) > state.now ? u : null;
    return {
      name,
      inPool: pool.has(name),
      five: five ? Math.round(100 * five.five_hour) : null,
      fiveResets: five?.five_hour_resets ?? null,
      week: week && week.seven_day !== null ? Math.round(100 * week.seven_day) : null,
      weekResets: week?.seven_day_resets ?? null,
    };
  });
}

/** The pool after one account is taken in or out; null when that would leave it empty. */
export function poolWith(pool: readonly string[], name: string, on: boolean): string[] | null {
  const next = on ? [...pool.filter((n) => n !== name), name] : pool.filter((n) => n !== name);
  return next.length === 0 ? null : next;
}
