/** The hub's data as TanStack queries, and every write as one function that refreshes what it changed. */
import { keepPreviousData, useQueries, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { MapRoute, Queue, RouteAnswer, RouteBody, State, TicketAction, TicketDetail, TicketRow } from "@sb-hub/contract";
import { QueueStale } from "@sb-hub/contract";
import { get, HubError, post, READONLY, ticketPath } from "./api.ts";
import { predictQueue, type QueueRoute } from "./predict.ts";
import { guessTicket, type TicketGuess } from "./ticketGuess.ts";

export const STATE_MS = 2000;
export const TRAIL_MS = 2000;
export const TICKETS_MS = 15000;

/** Queue writes on their way to the hub, per client: while one is, a poll keeps the queue the page drew. */
const pending = new WeakMap<QueryClient, number>();
const inFlight = (qc: QueryClient): number => pending.get(qc) ?? 0;

export const useHubState = () => {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["state"],
    queryFn: async () => {
      const s = await get("GET /api/state");
      // a poll that left before the write landed would put the old queue back for a moment
      const drawn = qc.getQueryData<State>(["state"]);
      return inFlight(qc) > 0 && drawn !== undefined ? { ...s, queue: drawn.queue } : s;
    },
    refetchInterval: STATE_MS,
    retry: 1,
    retryDelay: 400,
  });
};
/** Ticket actions on their way to the hub, per client: a read that lands meanwhile gets their guesses too. */
const guesses = new WeakMap<QueryClient, Set<TicketGuess>>();
const guessesOf = (qc: QueryClient): Set<TicketGuess> => {
  let g = guesses.get(qc);
  if (g === undefined) guesses.set(qc, (g = new Set()));
  return g;
};
const withGuesses = {
  tickets: (qc: QueryClient, rows: TicketRow[]): TicketRow[] => [...guessesOf(qc)].reduce((r, g) => g.tickets?.(r) ?? r, rows),
  route: (qc: QueryClient, m: MapRoute): MapRoute => [...guessesOf(qc)].reduce((r, g) => (g.map === m.map ? (g.route?.(r) ?? r) : r), m),
  detail: (qc: QueryClient, d: TicketDetail): TicketDetail => [...guessesOf(qc)].reduce((r, g) => (g.key === d.key ? (g.detail?.(r) ?? r) : r), d),
};
/** Ticket actions reach the hub one at a time, in the order they were made: sbmap rewrites the map's note. */
const ticketLine = new WeakMap<QueryClient, Promise<unknown>>();
function inLine<T>(qc: QueryClient, run: () => Promise<T>): Promise<T> {
  const next = (ticketLine.get(qc) ?? Promise.resolve()).then(run, run);
  ticketLine.set(qc, next.catch(() => undefined));
  return next;
}
const getMap = (qc: QueryClient, map: string) => async () => withGuesses.route(qc, await get("GET /api/map", { map }));

export const useTickets = () => {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["tickets"],
    queryFn: async () => withGuesses.tickets(qc, await get("GET /api/tickets")),
    refetchInterval: TICKETS_MS,
    retry: 1,
  });
};
export const useTicketDetail = (key: string | null) => {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["ticket", key],
    queryFn: async () => withGuesses.detail(qc, await get("GET /api/ticket", { key: key ?? "" })),
    enabled: key !== null && /#\d+$/.test(key),
    refetchInterval: TICKETS_MS,
  });
};

/** A map and every ticket of it, finished ones too. */
export const useMapRoute = (map: string) => {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["map", map],
    queryFn: getMap(qc, map),
    enabled: map !== "",
    refetchInterval: TICKETS_MS,
    placeholderData: keepPreviousData,
    retry: 1,
  });
};

/** Several maps at once, read through the same cache as one map's page. */
export const useMapRoutes = (maps: readonly string[]) => {
  const qc = useQueryClient();
  return useQueries({
    queries: maps.map((map) => ({
      queryKey: ["map", map],
      queryFn: getMap(qc, map),
      refetchInterval: TICKETS_MS,
      placeholderData: keepPreviousData,
      retry: 1,
    })),
  });
};

/** One session's last actions, every 2 s; null when the hub has none for it (a session that has not acted yet). */
export const useTrail = (agent: string) =>
  useQuery({
    queryKey: ["trail", agent],
    queryFn: () => get("GET /api/trail", { agent }).catch((e: unknown) => (e instanceof HubError && e.status === 404 ? null : Promise.reject(e as Error))),
    refetchInterval: TRAIL_MS,
    retry: false,
  });

/** History's runs from `since` on, newest first, the newest `limit` of them. */
export const useRuns = (since: number, limit: number) =>
  useQuery({
    queryKey: ["runs", since, limit],
    queryFn: () => get("GET /api/runs", { since: String(since), limit: String(limit) }),
    refetchInterval: TICKETS_MS,
    placeholderData: keepPreviousData,
    retry: 1,
  });
/** One run with its checks, report and log tail. */
export const useRun = (key: string) =>
  useQuery({ queryKey: ["run", key], queryFn: () => get("GET /api/run", { key }), enabled: key !== "", refetchInterval: TICKETS_MS, retry: 1 });

/** The hub's runs, newest first with counts; polled with the state, since the head of the live one follows a stop. */
export const useNights = () =>
  useQuery({ queryKey: ["nights"], queryFn: () => get("GET /api/nights"), refetchInterval: STATE_MS, placeholderData: keepPreviousData, retry: 1 });
/** One run with its items. */
export const useNight = (id: string) =>
  useQuery({ queryKey: ["night", id], queryFn: () => get("GET /api/night", { id }), enabled: id !== "", refetchInterval: TICKETS_MS, retry: 1 });

/** The outcome of a write, in the words the page shows. */
export type Outcome = { ok: true; words: string } | { ok: false; words: string };

type NightRoute = "POST /api/night/start" | "POST /api/night/stop" | "POST /api/night/rename";

function putQueue(qc: QueryClient, queue: Queue): void {
  qc.setQueryData<State>(["state"], (s) => (s ? { ...s, queue } : s));
}

export interface Writes {
  queue: <K extends QueueRoute>(route: K, body: RouteBody<K>, done: string | ((answer: RouteAnswer<K>) => string)) => Promise<Outcome>;
  /** Rename the live run, or stop it after what runs. */
  night: <K extends NightRoute>(route: K, body: RouteBody<K>, done: string) => Promise<Outcome>;
  ticket: (action: TicketAction, body: RouteBody<"POST /api/ticket/:action">, done: string) => Promise<Outcome>;
  answer: (qid: string, answer: string) => Promise<Outcome>;
  send: (to: string, text: string) => Promise<Outcome>;
  unsend: (id: string) => Promise<Outcome>;
  dismiss: (agent: string) => Promise<Outcome>;
  clearQuiet: () => Promise<Outcome>;
  /** Start every waiting review at once; the maps it started (keys) come with the outcome. */
  reviewNow: () => Promise<Outcome & { started: readonly string[] }>;
  scan: () => Promise<Outcome>;
  /** Mark ended runs seen (`<key>@<ended>` each): they leave Waits for you at once and the hub keeps the mark. */
  seen: (keys: readonly string[]) => Promise<Outcome>;
}

/** The hub's writes. Queue writes carry the version the page last read; a stale one redraws from the hub's queue. */
export function useWrites(): Writes {
  const qc = useQueryClient();
  const refresh = (tickets: boolean): void => {
    void qc.invalidateQueries({ queryKey: ["state"] });
    if (tickets) void qc.invalidateQueries({ queryKey: ["tickets"] });
  };
  return {
    async queue(route, body, done) {
      // draw the likely result at once; the hub's answer replaces it, and a refusal puts the old queue back
      const before = qc.getQueryData<State>(["state"])?.queue;
      const guess = before === undefined || READONLY ? null : predictQueue(before, route, body);
      pending.set(qc, inFlight(qc) + 1);
      if (guess !== null) {
        await qc.cancelQueries({ queryKey: ["state"] });
        putQueue(qc, guess);
      }
      const out = await post(route, body).finally(() => pending.set(qc, inFlight(qc) - 1));
      if (out.ok) {
        // every queue route answers with the queue (QueueAnswer, or QueueJobAnswer which extends it)
        putQueue(qc, (out.data as RouteAnswer<"POST /api/queue/pause">).queue);
        refresh(true);
        return { ok: true, words: typeof done === "string" ? done : done(out.data) };
      }
      const stale = QueueStale.safeParse(out.data);
      if (stale.success) {
        putQueue(qc, stale.data.queue);
        return { ok: false, words: "the list changed while you were on it; try again" };
      }
      if (guess !== null && before !== undefined) {
        putQueue(qc, before);
        refresh(false);
      }
      return { ok: false, words: out.error };
    },
    async night(route, body, done) {
      const out = await post(route, body);
      void qc.invalidateQueries({ queryKey: ["nights"] });
      void qc.invalidateQueries({ queryKey: ["night"] });
      refresh(true);
      return out.ok ? { ok: true, words: done } : { ok: false, words: out.error };
    },
    async ticket(action, body, done) {
      // draw the likely result at once; the hub's answer replaces it, and a refusal puts the old answers back
      const guess = READONLY ? null : guessTicket(action, body);
      const keys = guess === null ? [] : [["tickets"], ["map", guess.map], ["ticket", guess.key]];
      const before = keys.map((k) => [k, qc.getQueryData(k)] as const);
      if (guess !== null) {
        guessesOf(qc).add(guess);
        await Promise.all(keys.map((k) => qc.cancelQueries({ queryKey: k, exact: true })));
        qc.setQueryData<TicketRow[]>(["tickets"], (r) => (r && guess.tickets ? guess.tickets(r) : r));
        qc.setQueryData<MapRoute>(["map", guess.map], (m) => (m && guess.route ? guess.route(m) : m));
        qc.setQueryData<TicketDetail>(["ticket", guess.key], (d) => (d && guess.detail ? guess.detail(d) : d));
      }
      const out = await inLine(qc, () => post("POST /api/ticket/:action", body, ticketPath(action)));
      if (guess !== null) {
        guessesOf(qc).delete(guess);
        // with no other action on its way, the answers as they were are right; otherwise the reads below redraw
        if (!out.ok && guessesOf(qc).size === 0) for (const [k, v] of before) qc.setQueryData(k, v);
      }
      refresh(true);
      void qc.invalidateQueries({ queryKey: ["ticket", body.key] });
      if (guess !== null) void qc.invalidateQueries({ queryKey: ["map", guess.map] });
      return out.ok ? { ok: true, words: done } : { ok: false, words: out.error };
    },
    async answer(qid, answer) {
      const out = await post("POST /api/answer", { qid, answer });
      refresh(false);
      return out.ok ? { ok: true, words: "Answered." } : { ok: false, words: out.error };
    },
    async send(to, text) {
      const out = await post("POST /api/send", { to, text });
      refresh(false);
      return out.ok ? { ok: true, words: "Queued for delivery." } : { ok: false, words: out.error };
    },
    async unsend(id) {
      const out = await post("POST /api/unsend", { id });
      refresh(false);
      return out.ok ? { ok: true, words: "Taken back." } : { ok: false, words: out.error };
    },
    async dismiss(agent) {
      const out = await post("POST /api/agents/dismiss", { agent });
      refresh(false);
      return out.ok ? { ok: true, words: "Dismissed: it comes back with its next event." } : { ok: false, words: out.error };
    },
    async clearQuiet() {
      const out = await post("POST /api/agents/clear-quiet", {});
      refresh(false);
      return out.ok ? { ok: true, words: `Cleared ${String(out.data.cleared)} quiet sessions.` } : { ok: false, words: out.error };
    },
    async seen(keys) {
      if (READONLY) return { ok: true, words: "Seen marks are kept on the Mac." };
      qc.setQueryData<State>(["state"], (s) => (s ? { ...s, seen: [...s.seen.filter((k) => !keys.includes(k)), ...keys] } : s));
      const outs = await Promise.all(keys.map((key) => post("POST /api/run/seen", { key })));
      refresh(false);
      for (const o of outs) if (!o.ok) return { ok: false, words: o.error };
      return { ok: true, words: "Marked seen." };
    },
    async reviewNow() {
      const out = await post("POST /api/review/now", {});
      refresh(true);
      return out.ok ? { ok: true, words: "Reviews started.", started: out.data.started } : { ok: false, words: out.error, started: [] };
    },
    async scan() {
      const out = await post("POST /api/agents/scan", {});
      refresh(false);
      return out.ok ? { ok: true, words: "Agents scanned." } : { ok: false, words: out.error };
    },
  };
}
