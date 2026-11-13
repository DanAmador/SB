/**
 * The board's grouping rules, pure: what goes in Questions, which sessions are yours, what is ready, queued,
 * running, done and failed. The views only draw what these return; board.test.ts pins every rule.
 */
import type { AgentRow, Installed, Message, Question, QueueItem, State, TicketRow } from "@sb-hub/contract";

/** A ticket's estimate when the queue's end is reckoned: 1.5 h. */
export const ESTIMATE = 5400;
/** Done shows what ended in the last 7 days; older items stay in the vault. */
export const WEEK = 7 * 86400;
/** An answered question stays on the board this long, so the click shows its result. */
export const ANSWERED_FOR = 20;

/** A map's title, else its name. */
export const mapTitle = (t: Pick<TicketRow, "map" | "map_title">): string => (t.map_title === "" ? t.map : t.map_title);
export const tkey = (t: Pick<TicketRow, "map" | "num">): string => `${t.map}#${String(t.num)}`;
/** A map's wayfinder project, as the hub names it: the folder prefix, else the name before a dash. */
export function projOf(map: string): string {
  const parts = map.split("/");
  return parts.length > 1 ? (parts[0] ?? "") : (map.split("-")[0] ?? "");
}
/** A path's last folder: the project of a session or a job. */
export const folder = (path: string | undefined): string => (path ?? "").split("/").filter(Boolean).pop() ?? "";
export const firstLine = (text: string | undefined): string =>
  (text ?? "").split("\n").map((l) => l.trim()).find(Boolean) ?? "";
const short = (id: string): string => id.slice(0, 6);
const tnum = (t: string): string => (/^\d+$/.test(t) ? `ticket ${t}` : t);

/** One label for an agent everywhere: its title, else its ticket, else its name, else a short id. */
export function agentLabel(a: AgentRow): string {
  return a.title ?? (a.ticket ? tnum(a.ticket) : undefined) ?? a.name ?? short(a.agent);
}

const RANK: Readonly<Record<string, number>> = { "needs you": 0, blocked: 0, "your turn": 1, working: 2, waiting: 2, idle: 3, done: 4 };
export const rank = (a: AgentRow): number => RANK[a.state ?? ""] ?? 2;
const byRank = (x: AgentRow, y: AgentRow): number => rank(x) - rank(y) || y.at - x.at;

export interface Agents {
  /** Your own sessions, the ones you run by hand: never queue workers, never a session's helpers. */
  readonly sessions: readonly AgentRow[];
  /** The queue's headless workers. */
  readonly workers: readonly AgentRow[];
  /** A session's own helpers, by the session's id. */
  readonly kids: ReadonlyMap<string, readonly AgentRow[]>;
}

export function splitAgents(state: Pick<State, "agents">): Agents {
  const all = Object.entries(state.agents).map(([id, a]) => ({ ...a, agent: a.agent || id }));
  const byId = new Map(all.map((a) => [a.agent, a]));
  const isQueueWorker = (a: AgentRow): boolean => a.role === "worker" && a.parent === "queue";
  const parentOf = (a: AgentRow): string | null => {
    if (a.role !== "worker" || a.parent === undefined) return null;
    const p = byId.get(a.parent);
    return p && p.role !== "worker" ? p.agent : null;
  };
  const kids = new Map<string, AgentRow[]>();
  for (const a of all) {
    const p = parentOf(a);
    if (p !== null) kids.set(p, [...(kids.get(p) ?? []), a].sort(byRank));
  }
  return {
    sessions: all.filter((a) => !isQueueWorker(a) && parentOf(a) === null).sort(byRank),
    workers: all.filter(isQueueWorker),
    kids,
  };
}

/** Who an id is: aliases resolve to the agent they report as. */
export function agentOf(state: Pick<State, "agents" | "aliases">, id: string): AgentRow | null {
  return state.agents[state.aliases[id] ?? id] ?? null;
}

// ---- the queue ----

export interface QueueView {
  readonly running: readonly QueueItem[];
  /** Queued items in the order they run. */
  readonly next: readonly QueueItem[];
  /** The queued tickets' keys, in order: what /api/queue/set takes. */
  readonly queuedKeys: readonly string[];
  /** Keys queued or running. */
  readonly live: ReadonlySet<string>;
  /** Ended in the last week (done) or still on the list (failed, skipped), newest first; then the cleared ones. */
  readonly done: readonly QueueItem[];
  readonly doneCleared: readonly QueueItem[];
  readonly failed: readonly QueueItem[];
  readonly failedCleared: readonly QueueItem[];
}

export function queueView(state: Pick<State, "queue" | "now">): QueueView {
  const items = state.queue.items;
  const cleared = state.queue.cleared ?? [];
  const newest = (x: QueueItem, y: QueueItem): number => (y.ended ?? 0) - (x.ended ?? 0);
  const ended = (list: readonly QueueItem[], states: readonly string[], all: boolean): QueueItem[] =>
    list.filter((i) => states.includes(i.state) && (all || state.now - (i.ended ?? 0) < WEEK)).sort(newest);
  const next = items.filter((i) => i.state === "queued");
  return {
    running: items.filter((i) => i.state === "running"),
    next,
    queuedKeys: next.filter((i) => i.kind === "ticket").map((i) => i.key),
    live: new Set(items.filter((i) => i.state === "queued" || i.state === "running").map((i) => i.key)),
    done: ended(items, ["done"], false),
    doneCleared: ended(cleared, ["done"], false),
    failed: ended(items, ["failed", "skipped"], true),
    failedCleared: ended(cleared, ["failed", "skipped"], false),
  };
}

/** The accounts the queue runs on tonight. */
export function poolOf(state: Pick<State, "queue">): string[] {
  const q = state.queue;
  return q.agents && q.agents.length > 0 ? [...q.agents] : q.agent !== null ? [q.agent] : [];
}

// ---- tickets ----

const blockersOf = (t: TicketRow): (string | null)[] =>
  t.blocked_by_open.map((b) => (typeof b === "number" ? `${t.map}#${String(b)}` : null));

export interface TicketIndex {
  readonly byKey: ReadonlyMap<string, TicketRow>;
  readonly live: ReadonlySet<string>;
  readonly doneKeys: ReadonlySet<string>;
  /** Live keys in the queue's order: running first, then queued. */
  readonly order: ReadonlyMap<string, number>;
}
export function ticketIndex(tickets: readonly TicketRow[], state: Pick<State, "queue">): TicketIndex {
  const items = state.queue.items;
  return {
    byKey: new Map(tickets.map((t) => [tkey(t), t])),
    live: new Set(items.filter((i) => i.state === "queued" || i.state === "running").map((i) => i.key)),
    doneKeys: new Set(items.filter((i) => i.kind === "ticket" && i.state === "done").map((i) => i.key)),
    order: new Map(
      [...items.filter((i) => i.state === "running"), ...items.filter((i) => i.state === "queued")].map((i, n) => [i.key, n]),
    ),
  };
}

/** Can a ticket be queued: ready, or blocked only by tickets that are queued or can be queued too. */
export function addable(t: TicketRow, ix: TicketIndex, visited?: Set<string>): boolean {
  if (ix.doneKeys.has(tkey(t))) return false;
  const seen = visited ?? new Set([tkey(t)]);
  if (t.state === "ready") return true;
  if (t.state !== "blocked") return false;
  return blockersOf(t).every((k) => {
    if (k === null) return false;
    if (ix.live.has(k)) return true;
    const o = ix.byKey.get(k);
    if (!o || seen.has(k)) return false;
    seen.add(k);
    return addable(o, ix, seen);
  });
}

/** A ticket and the open tickets it waits on that are not queued yet, blockers first. */
export function withBlockers(key: string, ix: TicketIndex, acc?: string[]): string[] {
  const out = acc ?? [];
  if (out.includes(key)) return out;
  const t = ix.byKey.get(key);
  if (t) for (const b of blockersOf(t)) if (b !== null && !ix.live.has(b)) withBlockers(b, ix, out);
  out.push(key);
  return out;
}

/** The titles a ticket still waits on. */
export function blockerTitles(t: TicketRow, ix: TicketIndex): string[] {
  return t.blocked_by_open.map((b) => {
    if (typeof b !== "number") return b;
    return ix.byKey.get(`${t.map}#${String(b)}`)?.title ?? `ticket ${String(b)}`;
  });
}

/** The Queue's search: words over project, map and title, a project, a map, and which open tickets. */
export interface Find {
  readonly q: string;
  readonly p: string;
  readonly m: string;
  readonly s: Show;
}
export const SHOWS = ["ready", "waits", "later"] as const;
export type Show = (typeof SHOWS)[number];

/** Which list an open ticket is in: can run, needs a decision, not yet; null while it is queued or running. */
export function showOf(t: TicketRow, ix: TicketIndex): Show | null {
  if (ix.live.has(tkey(t))) return null;
  if (t.state === "waits for you") return "waits";
  return addable(t, ix) ? "ready" : "later";
}

/** Open tickets that match every word typed, the chosen project and map, and the chosen list, in map order. */
export function searchTickets(tickets: readonly TicketRow[], ix: TicketIndex, f: Find): TicketRow[] {
  const words = f.q.toLowerCase().split(/\s+/).filter(Boolean);
  return tickets.filter((t) => {
    if (f.p && projOf(t.map) !== f.p) return false;
    if (f.m && t.map !== f.m) return false;
    if (showOf(t, ix) !== f.s) return false;
    const hay = `${projOf(t.map)} ${t.map} ${mapTitle(t)} ${t.title} ${String(t.num)}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** How many open tickets each list holds under the same words, project and map. */
export function showCounts(tickets: readonly TicketRow[], ix: TicketIndex, f: Omit<Find, "s">): Readonly<Record<Show, number>> {
  return { ready: searchTickets(tickets, ix, { ...f, s: "ready" }).length, waits: searchTickets(tickets, ix, { ...f, s: "waits" }).length, later: searchTickets(tickets, ix, { ...f, s: "later" }).length };
}

/** The projects and maps the filters offer: every project with an open ticket; the maps of the chosen one. */
export function filterOptions(tickets: readonly TicketRow[], f: Pick<Find, "p" | "m">): { projects: string[]; maps: [string, string][] } {
  const projects = new Set(tickets.map((t) => projOf(t.map)));
  if (f.p) projects.add(f.p);
  const maps = new Map<string, string>();
  for (const t of tickets) if (!f.p || projOf(t.map) === f.p) maps.set(t.map, mapTitle(t));
  if (f.m && !maps.has(f.m)) maps.set(f.m, f.m);
  return { projects: [...projects].sort(), maps: [...maps].sort((x, y) => x[1].localeCompare(y[1])) };
}

// ---- queue items ----

/** A title, never a bare id: the ticket's own, else what the hub stored, else its map and number. */
export function itemTitle(i: QueueItem, t: TicketRow | null | undefined): string {
  if (t) return t.title;
  if (i.title) return i.title;
  if (i.kind === "job") return i.name || "job";
  const m = /^(.*)#(\d+)$/.exec(i.key);
  return m ? `${m[1] ?? ""} ticket ${m[2] ?? ""}` : i.key;
}
export function itemProject(i: QueueItem, t: TicketRow | null | undefined): string {
  if (i.kind === "job") return folder(i.project) || i.project;
  return projOf(t ? t.map : (i.key.split("#")[0] ?? ""));
}
export const itemMap = (i: QueueItem): string => (i.kind === "job" ? "" : i.key.replace(/#\d+$/, ""));

/** Can a failed ticket be ticked again: its ticket is still open, it is not live, and it is not done since. */
export function canTickAgain(i: QueueItem, ix: TicketIndex): boolean {
  return i.kind === "ticket" && i.state !== "done" && ix.byKey.has(i.key) && !ix.live.has(i.key) && !ix.doneKeys.has(i.key);
}

/**
 * When the queue should end: each repo runs its items one after another, repos side by side, and all of them
 * share the accounts' worker slots (2 for an account with a learned cost, else 1).
 */
export function endsAt(state: State, ix: TicketIndex | null): number {
  const live = state.queue.items.filter((i) => i.state === "running" || i.state === "queued");
  if (live.length === 0) return 0;
  const byRepo = new Map<string, QueueItem[]>();
  for (const i of live) {
    const t = ix?.byKey.get(i.key);
    const r = i.repo ?? t?.repo ?? (itemProject(i, t) || i.key);
    byRepo.set(r, [...(byRepo.get(r) ?? []), i]);
  }
  let end = state.now;
  for (const list of byRepo.values()) {
    const run = list.filter((i) => i.state === "running");
    const from = run.length > 0 ? Math.min(...run.map((i) => i.started ?? state.now)) : state.now;
    end = Math.max(end, from + ESTIMATE * list.length);
  }
  const slots = poolOf(state)
    .map((n) => state.installed[n])
    .filter((e): e is Installed => e !== undefined && e.login !== "expired")
    .reduce((n, e) => n + (e.costs && Object.keys(e.costs).length > 0 ? 2 : 1), 0);
  const queued = live.filter((i) => i.state === "queued").length;
  return Math.max(end, state.now + (ESTIMATE * queued) / Math.max(1, slots));
}

/** An account's state in words, for the toolbar. */
export function accountState(name: string, e: Installed, state: State): { tone: "out" | "run" | "lim" | "ok"; words: string } {
  if (e.login === "expired") return { tone: "out", words: "signed out" };
  if (state.queue.items.some((i) => i.state === "running" && i.runner === name)) return { tone: "run", words: "running" };
  if ((e.limited_until ?? 0) > state.now) return { tone: "lim", words: `limited until ${hm(e.limited_until ?? 0)}` };
  return { tone: "ok", words: "signed in" };
}
/** The share of its 5-hour window an account has used, while that window lasts. */
export function usageOf(e: Installed, now: number): { pct: number; resets: number } | null {
  const u = e.usage;
  return u && (u.five_hour_resets ?? 0) > now ? { pct: Math.round(100 * u.five_hour), resets: u.five_hour_resets ?? 0 } : null;
}

// ---- runs ----

/** A worker silent this long turns amber. */
export const SILENT = 300;

export type RunTone = "ok" | "quiet" | "blocked";
export interface RunRow {
  readonly item: QueueItem;
  readonly ticket: TicketRow | undefined;
  readonly title: string;
  readonly map: string;
  /** The map's short name: its titles run a sentence long. */
  readonly mapName: string;
  readonly project: string;
  readonly account: string;
  /** Seconds since it started. */
  readonly runFor: number;
  /** Its last action in words, and when it reported it. */
  readonly last: string;
  readonly lastAt: number;
  readonly tone: RunTone;
}

const TONE_ORDER: Readonly<Record<RunTone, number>> = { blocked: 0, quiet: 1, ok: 2 };

/** One row per worker run: blocked first, then the silent ones, then by how long they have run. */
export function runRows(state: State, ix: TicketIndex): RunRow[] {
  return state.queue.items
    .filter((i) => i.state === "running")
    .map((i): RunRow => {
      const t = ix.byKey.get(i.key);
      const a = agentOf(state, i.key);
      const started = i.started ?? state.now;
      const lastAt = Math.max(a?.at ?? started, started);
      const tone: RunTone = a !== null && rank(a) === 0 ? "blocked" : state.now - lastAt >= SILENT ? "quiet" : "ok";
      const map = t?.map ?? itemMap(i);
      return {
        item: i,
        ticket: t,
        title: itemTitle(i, t),
        map,
        mapName: map.split("/").pop() ?? "",
        project: itemProject(i, t),
        account: i.runner ?? i.agent ?? state.queue.agent ?? "",
        runFor: state.now - started,
        last: (a?.note ?? firstLine(i.note)) || "starting",
        lastAt,
        tone,
      };
    })
    .sort((x, y) => TONE_ORDER[x.tone] - TONE_ORDER[y.tone] || y.runFor - x.runFor);
}

/** The local midnight before an epoch. */
export function dayStart(now: number): number {
  const d = new Date(now * 1000);
  d.setHours(0, 0, 0, 0);
  return d.getTime() / 1000;
}

/** Runs that ended today, on the list or cleared from it, newest first. */
export function endedToday(state: Pick<State, "queue" | "now">): QueueItem[] {
  const from = dayStart(state.now);
  const seen = new Set<string>();
  return [...state.queue.items, ...(state.queue.cleared ?? [])]
    .filter((i) => (i.state === "done" || i.state === "failed" || i.state === "skipped") && (i.ended ?? 0) >= from)
    .filter((i) => {
      const k = seenKey(i);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    })
    .sort((x, y) => (y.ended ?? 0) - (x.ended ?? 0));
}

// ---- waits for you ----

/** One ended run, once: what "Looks good" and "Set aside" remember. */
export const seenKey = (i: Pick<QueueItem, "key" | "ended">): string => `${i.key}@${String(i.ended ?? 0)}`;

export interface Waits {
  /** Open questions first by deadline, then ones answered in the last 20 s. */
  readonly questions: readonly (readonly [string, Question])[];
  /** Failed or skipped runs still on the list, newest first. */
  readonly failed: readonly QueueItem[];
  /** Runs done in the last week, newest first. */
  readonly done: readonly QueueItem[];
  /** Open tickets in state "waits for you": design work a worker cannot do. */
  readonly tickets: readonly TicketRow[];
  readonly signedOut: readonly string[];
  readonly badWidgets: readonly { project: string; panel: string; label: string; value: string }[];
  /**
   * The tab's count, the page's only alarm: open questions, runs to assess, accounts signed out and failing
   * widgets. Design tickets are listed but not counted: there are dozens and they wait days, not minutes.
   */
  readonly count: number;
}

const valueOf = (w: object): string => {
  const v = (w as { value?: unknown }).value;
  return typeof v === "string" || typeof v === "number" ? String(v) : "";
};

/** What waits for the owner, in the order the tab shows it. Runs already looked at (seen) are left out. */
export function waitsFor(state: State, tickets: readonly TicketRow[] | null, ix: TicketIndex, seen: ReadonlySet<string>): Waits {
  const questions = Object.entries(state.questions)
    .filter(([, q]) => q.answer === null || state.now - (q.answered ?? 0) < ANSWERED_FOR)
    .sort(([, x], [, y]) => Number(x.answer !== null) - Number(y.answer !== null) || x.deadline - y.deadline);
  const qv = queueView(state);
  const fresh = (i: QueueItem): boolean => !seen.has(seenKey(i));
  const failed = qv.failed.filter(fresh);
  const done = qv.done.filter(fresh);
  const waiting = (tickets ?? []).filter((t) => t.state === "waits for you" && !ix.live.has(tkey(t)));
  const badWidgets: Waits["badWidgets"][number][] = [];
  for (const [project, panels] of Object.entries(state.providers)) {
    for (const p of panels) {
      for (const w of p.widgets) {
        if ((w as { level?: unknown }).level === "bad") badWidgets.push({ project, panel: p.title, label: w.label ?? "", value: valueOf(w) });
      }
    }
  }
  const signedOut = Object.entries(state.installed).filter(([, e]) => e.login === "expired").map(([n]) => n);
  const open = questions.filter(([, q]) => q.answer === null).length;
  return {
    questions,
    failed,
    done,
    tickets: waiting,
    signedOut,
    badWidgets,
    count: open + failed.length + done.length + signedOut.length + badWidgets.length,
  };
}

/** Why a run failed or was skipped, in plain words; the raw note stays one click away. */
export function plainReason(i: Pick<QueueItem, "note" | "state">): string {
  const first = firstLine(i.note);
  if (!first) return i.state === "skipped" ? "skipped, no reason recorded" : "no reason recorded";
  if (first.startsWith("no commit after ")) return "ended without a commit";
  const check = /^check failed: (.+)$/.exec(first);
  if (check) {
    const cmd = (check[1] ?? "").trim();
    if (cmd.startsWith("/") || cmd.startsWith("~")) {
      const name = (cmd.split(/\s/)[0] ?? "").split("/").pop()?.replace(/\.[a-z]+$/i, "").replace(/[-_]+/g, " ") ?? cmd;
      return `the ${name} check failed`;
    }
    return `${cmd} failed`;
  }
  const outside = /^commits since the start touch files outside the ticket's paths: (.+)$/.exec(first);
  if (outside) {
    const n = (outside[1] ?? "").split(",").filter((x) => x.trim()).length;
    return n === 1 ? "it changed a file outside its list" : `it changed ${String(n)} files outside its list`;
  }
  const land = /^could not land: .*conflict.* in (\S+)$/.exec(first);
  if (land) return `its commits conflict with the branch in ${(land[1] ?? "").split("/").pop() ?? ""}`;
  const after = /^blocked: after (.+)$/.exec(first);
  if (after) return `waited on “${after[1] ?? ""}”`;
  if (first.startsWith("claimed: ")) return "someone else had claimed it";
  if (first.startsWith("no longer open")) return "its ticket was closed after it was queued";
  return first.length > 140 ? `${first.slice(0, 139)}…` : first;
}

// ---- messages ----

/** Messages queued for an id and not delivered yet. */
export function pendingFor(messages: Readonly<Record<string, Message>>, id: string): [string, Message][] {
  return Object.entries(messages).filter(([, m]) => m.to === id && m.delivered === null && m.lost === undefined);
}
/** When a queued message lands, by the receiver's state. */
export function whenDelivered(a: AgentRow | null): string {
  if (!a) return "";
  if (a.state === "working") return "Delivers after its next tool call.";
  if (a.state === "done") return "It has finished; it will not read this.";
  if (rank(a) === 0) return "Delivers once it continues.";
  return "It is idle: delivers when its next turn starts.";
}

// ---- words ----

export function dur(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  if (s < 60) return `${String(s)}s`;
  if (s < 3600) return `${String(Math.floor(s / 60))}m`;
  if (s < 86400) return `${String(Math.floor(s / 3600))}h`;
  return `${String(Math.floor(s / 86400))}d`;
}
export const ago = (now: number, t: number | null | undefined): string => `${dur(now - (t ?? 0))} ago`;
export const hm = (sec: number): string => new Date(sec * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
export const plural = (n: number, w: string, ws?: string): string => `${String(n)} ${n === 1 ? w : (ws ?? `${w}s`)}`;

/** The next epoch the clock shows HH:MM, or null for anything else. */
export function nextClock(v: string, now: number): number | null {
  if (!/^\d\d:\d\d$/.test(v)) return null;
  const [hh = 0, mm = 0] = v.split(":").map(Number);
  const d = new Date(now * 1000);
  d.setHours(hh, mm, 0, 0);
  if (d.getTime() / 1000 <= now) d.setDate(d.getDate() + 1);
  return d.getTime() / 1000;
}

// ---- the sidebar's scope ----

/** What the sidebar picked: everything (both empty), a project, or one map of it. */
export interface Scope {
  readonly project: string;
  readonly map: string;
}
export const EVERYTHING: Scope = { project: "", map: "" };
export const isScoped = (s: Scope): boolean => s.project !== "" || s.map !== "";

/** Does a map ("" for none, as a job has) fall in the scope. A project-only scope takes a job of that project (by `project`). */
export function mapInScope(s: Scope, map: string, project?: string): boolean {
  if (s.map !== "") return map === s.map;
  if (s.project === "") return true;
  return (map === "" ? (project ?? "") : projOf(map)) === s.project;
}

/** The map a queue item belongs to, "" for a job. */
const itemMapKey = (i: Pick<QueueItem, "key" | "kind">): string => (i.kind === "job" ? "" : i.key.replace(/#\d+$/, ""));
export const itemInScope = (s: Scope, i: QueueItem): boolean => mapInScope(s, itemMapKey(i), i.kind === "job" ? folder(i.project) : undefined);
export const ticketInScope = (s: Scope, t: Pick<TicketRow, "map">): boolean => mapInScope(s, t.map);
export const scopeItems = (s: Scope, items: readonly QueueItem[]): QueueItem[] => items.filter((i) => itemInScope(s, i));

/** The map or project a question's asker works on: a worker's key names its map, a session its folder. */
function askerScope(state: Pick<State, "agents" | "aliases">, id: string): { map: string; project: string } {
  const a = agentOf(state, id);
  const key = a?.agent ?? id;
  if (/#\d+$/.test(key)) return { map: key.replace(/#\d+$/, ""), project: "" };
  return { map: "", project: folder(a?.project) };
}
const questionInScope = (s: Scope, state: Pick<State, "agents" | "aliases">, q: Question): boolean => {
  if (!isScoped(s)) return true;
  const w = askerScope(state, q.agent);
  return mapInScope(s, w.map, w.project);
};

/** What waits for you, narrowed. Accounts signed out are not about a project, so they show only unscoped. */
export function scopeWaits(w: Waits, s: Scope, state: Pick<State, "agents" | "aliases">): Waits {
  if (!isScoped(s)) return w;
  const questions = w.questions.filter(([, q]) => questionInScope(s, state, q));
  const failed = scopeItems(s, w.failed);
  const done = scopeItems(s, w.done);
  const tickets = w.tickets.filter((t) => ticketInScope(s, t));
  const badWidgets = w.badWidgets.filter((b) => s.map === "" && (s.project === "" || folder(b.project) === s.project));
  const open = questions.filter(([, q]) => q.answer === null).length;
  return { questions, failed, done, tickets, signedOut: [], badWidgets, count: open + failed.length + done.length + badWidgets.length };
}

export interface Counts {
  readonly running: number;
  readonly waiting: number;
}
export interface SidebarMap extends Counts {
  readonly map: string;
  readonly title: string;
}
export interface SidebarProject extends Counts {
  readonly project: string;
  readonly maps: readonly SidebarMap[];
}
export interface Sidebar {
  readonly all: Counts;
  readonly projects: readonly SidebarProject[];
}

/** Everything, then each project with its maps, each with its running and waiting-for-you counts. */
export function sidebarTree(state: State, tickets: readonly TicketRow[] | null, waits: Waits): Sidebar {
  const titles = new Map<string, string>();
  for (const t of tickets ?? []) titles.set(t.map, mapTitle(t));
  const run = new Map<string, number>();
  const wait = new Map<string, number>();
  const bump = (m: Map<string, number>, k: string, n = 1): void => {
    m.set(k, (m.get(k) ?? 0) + n);
  };
  const projectOfItem = (i: QueueItem): { map: string; project: string } => {
    const map = itemMapKey(i);
    return { map, project: i.kind === "job" ? folder(i.project) : projOf(map) };
  };
  const proj = new Map<string, Set<string>>();
  const see = (project: string, map: string): void => {
    if (project === "") return;
    const set = proj.get(project) ?? new Set<string>();
    if (map !== "") set.add(map);
    proj.set(project, set);
  };
  for (const m of titles.keys()) see(projOf(m), m);
  const runsByProject = new Map<string, number>();
  const waitsByProject = new Map<string, number>();
  const count = (i: QueueItem, into: "run" | "wait"): void => {
    const w = projectOfItem(i);
    see(w.project, w.map);
    bump(into === "run" ? runsByProject : waitsByProject, w.project);
    if (w.map !== "") bump(into === "run" ? run : wait, w.map);
  };
  for (const i of state.queue.items) if (i.state === "running") count(i, "run");
  for (const i of [...waits.failed, ...waits.done]) count(i, "wait");
  for (const [, q] of waits.questions) {
    if (q.answer !== null) continue;
    const w = askerScope(state, q.agent);
    const project = w.map === "" ? w.project : projOf(w.map);
    see(project, w.map);
    bump(waitsByProject, project);
    if (w.map !== "") bump(wait, w.map);
  }
  for (const b of waits.badWidgets) {
    const p = folder(b.project);
    see(p, "");
    bump(waitsByProject, p);
  }
  const projects = [...proj.entries()]
    .sort(([x], [y]) => x.localeCompare(y))
    .map(([project, maps]): SidebarProject => ({
      project,
      running: runsByProject.get(project) ?? 0,
      waiting: waitsByProject.get(project) ?? 0,
      maps: [...maps]
        .map((map): SidebarMap => ({ map, title: map.split("/").pop() ?? map, running: run.get(map) ?? 0, waiting: wait.get(map) ?? 0 }))
        .sort((x, y) => x.map.localeCompare(y.map)),
    }));
  return {
    all: { running: state.queue.items.filter((i) => i.state === "running").length, waiting: waits.count },
    projects,
  };
}
