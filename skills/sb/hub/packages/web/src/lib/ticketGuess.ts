/**
 * What a ticket action will most likely change on the page, drawn before the hub answers (its note edit runs sbmap,
 * which takes a moment). Each guess is a set of pure changes to the cached answers it touches; the hub's next answer
 * replaces them. null: nothing to draw (a comment shows only in Obsidian; a recheck is the queue's to say).
 */
import type { MapRoute, RouteBody, TicketAction, TicketDetail, TicketRow } from "@sb-hub/contract";

export interface TicketGuess {
  key: string;
  map: string;
  tickets?: (rows: TicketRow[]) => TicketRow[];
  route?: (m: MapRoute) => MapRoute;
  detail?: (d: TicketDetail) => TicketDetail;
}

const blockerKey = (t: TicketRow, b: number | string): string => (typeof b === "number" ? `${t.map}#${String(b)}` : b);

/** The hub's state and reason of an open ticket (sbqueue.classify), with what it knows of the other rows. */
export function classify(t: TicketRow, rows: readonly TicketRow[]): Pick<TicketRow, "state" | "reason"> {
  if (t.status === "claimed") return { state: "claimed", reason: `claimed by ${t.claimed_by ?? "another session"}` };
  if (t.type === "grilling" || t.type === "architecture")
    return t.ruling ? { state: "not ready", reason: "ruled: a session files the work from your answer" } : { state: "waits for you", reason: `a ${t.type} ticket needs you` };
  if (t.check === "owner") return { state: "waits for you", reason: "you check this one: a worker cannot" };
  if (!t.has_done_when) return { state: "not ready", reason: "no done-when" };
  const queued = new Set(rows.filter((r) => r.queued).map((r) => `${r.map}#${String(r.num)}`));
  const waits = t.blocked_by_open.find((b) => !queued.has(blockerKey(t, b)));
  if (waits === undefined) return { state: "ready", reason: "ready" };
  const title = typeof waits === "number" ? rows.find((r) => r.map === t.map && r.num === waits)?.title : undefined;
  return { state: "blocked", reason: `after ${title ?? (typeof waits === "number" ? `ticket ${String(waits)}` : waits)}` };
}

const splitKey = (key: string): { map: string; num: number } | null => {
  const m = /^(.+)#(\d+)$/.exec(key);
  return m ? { map: m[1] ?? "", num: Number(m[2]) } : null;
};

/** The guess for `action` on the ticket `body.key`; null when there is nothing to draw. */
export function guessTicket(action: TicketAction, body: RouteBody<"POST /api/ticket/:action">): TicketGuess | null {
  const k = splitKey(body.key);
  if (k === null) return null;
  const { map, num } = k;
  const words = (body.text ?? "").split(/\s+/).filter(Boolean).join(" ");
  const mine = (r: { num: number; map?: string }): boolean => r.num === num && (r.map === undefined || r.map === map);
  /** Change this ticket's row, then let the hub's rules say its state again. */
  const row = (f: (r: TicketRow) => TicketRow) => (rows: TicketRow[]) =>
    rows.map((r) => {
      if (!mine(r)) return r;
      const next = f(r);
      return { ...next, ...classify(next, rows) };
    });
  const mapTicket = (f: (t: MapRoute["tickets"][number]) => MapRoute["tickets"][number]) => (m: MapRoute) => ({
    ...m,
    tickets: m.tickets.map((t) => (mine(t) ? f(t) : t)),
  });
  const base = { key: body.key, map };
  switch (action) {
    case "done":
    case "drop": {
      const done = action === "done";
      return {
        ...base,
        tickets: (rows) => rows.filter((r) => !mine(r)),
        route: mapTicket((t) => ({ ...t, status: done ? "resolved" : "out-of-scope", state: done ? "done" : "out of scope", place: null })),
        detail: (d) => ({ ...d, open: false }),
      };
    }
    case "release":
      return {
        ...base,
        tickets: row((r) => ({ ...r, status: "open", claimed_by: null })),
        route: mapTicket((t) => ({ ...t, status: "open" })),
      };
    case "tier":
      return { ...base, tickets: row((r) => ({ ...r, tier: words })), route: mapTicket((t) => ({ ...t, tier: words })) };
    case "rule":
      return { ...base, tickets: row((r) => ({ ...r, ruling: words })) };
    case "done_when": {
      const text = (body.text ?? "").trim();
      return { ...base, tickets: row((r) => ({ ...r, done_when: text, has_done_when: text !== "" })) };
    }
    case "paths": {
      const paths = (body.text ?? "").split("\n").map((p) => p.trim()).filter(Boolean);
      return { ...base, tickets: row((r) => ({ ...r, paths })) };
    }
    case "checks": {
      const checks = (body.text ?? "").split(";").map((c) => c.trim()).filter(Boolean);
      return {
        ...base,
        // a ticket of this map with no checks of its own runs the map's
        tickets: (rows) => rows.map((r) => (r.map === map && r.checks_from !== "ticket" ? { ...r, checks, checks_from: "map" } : r)),
        route: (m) => ({ ...m, checks }),
        detail: (d) => ({ ...d, map_checks: checks }),
      };
    }
    case "comment":
    case "recheck":
    case "after":
      return null;
  }
}
