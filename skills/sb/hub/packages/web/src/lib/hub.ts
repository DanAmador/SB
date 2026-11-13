/** The hub's data as TanStack queries, and every write as one function that refreshes what it changed. */
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { Queue, RouteAnswer, RouteBody, State, TicketAction } from "@sb-hub/contract";
import { QueueStale } from "@sb-hub/contract";
import { get, post, ticketPath } from "./api.ts";

export const STATE_MS = 2000;
export const TICKETS_MS = 15000;

export const useHubState = () =>
  useQuery({ queryKey: ["state"], queryFn: () => get("GET /api/state"), refetchInterval: STATE_MS, retry: false });
export const useTickets = () =>
  useQuery({ queryKey: ["tickets"], queryFn: () => get("GET /api/tickets"), refetchInterval: TICKETS_MS, retry: 1 });
export const useTicketDetail = (key: string | null) =>
  useQuery({
    queryKey: ["ticket", key],
    queryFn: () => get("GET /api/ticket", { key: key ?? "" }),
    enabled: key !== null && /#\d+$/.test(key),
    refetchInterval: TICKETS_MS,
  });

/** The outcome of a write, in the words the page shows. */
export type Outcome = { ok: true; words: string } | { ok: false; words: string };

type QueueRoute =
  | "POST /api/queue/set"
  | "POST /api/queue/move"
  | "POST /api/queue/pause"
  | "POST /api/queue/agents"
  | "POST /api/queue/options"
  | "POST /api/queue/job"
  | "POST /api/queue/remove_job"
  | "POST /api/queue/clear-finished"
  | "POST /api/queue/item_agent";

function putQueue(qc: QueryClient, queue: Queue): void {
  qc.setQueryData<State>(["state"], (s) => (s ? { ...s, queue } : s));
}

export interface Writes {
  queue: <K extends QueueRoute>(route: K, body: RouteBody<K>, done: string) => Promise<Outcome>;
  ticket: (action: TicketAction, body: RouteBody<"POST /api/ticket/:action">, done: string) => Promise<Outcome>;
  answer: (qid: string, answer: string) => Promise<Outcome>;
  send: (to: string, text: string) => Promise<Outcome>;
  unsend: (id: string) => Promise<Outcome>;
  dismiss: (agent: string) => Promise<Outcome>;
  clearQuiet: () => Promise<Outcome>;
  scan: () => Promise<Outcome>;
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
      const out = await post(route, body);
      if (out.ok) {
        // every queue route answers with the queue (QueueAnswer, or QueueJobAnswer which extends it)
        putQueue(qc, (out.data as RouteAnswer<"POST /api/queue/pause">).queue);
        refresh(true);
        return { ok: true, words: done };
      }
      const stale = QueueStale.safeParse(out.data);
      if (stale.success) {
        putQueue(qc, stale.data.queue);
        return { ok: false, words: "the list changed while you were on it; try again" };
      }
      return { ok: false, words: out.error };
    },
    async ticket(action, body, done) {
      const out = await post("POST /api/ticket/:action", body, ticketPath(action));
      refresh(true);
      void qc.invalidateQueries({ queryKey: ["ticket", body.key] });
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
    async scan() {
      const out = await post("POST /api/agents/scan", {});
      refresh(false);
      return out.ok ? { ok: true, words: "Agents scanned." } : { ok: false, words: out.error };
    },
  };
}
