/**
 * A worker's live feed: GET /api/item/feed polled with a cursor, so each poll carries only what its log gained.
 * The hub reads the log the worker writes anyway; nothing runs while no feed is open.
 */
import { useEffect, useRef, useState } from "react";
import type { FeedEvent } from "@sb-hub/contract";
import { get } from "./api.ts";

export const FEED_MS = 2000;
/** The most events a feed keeps; older ones fall off the top. */
export const FEED_KEEP = 800;

export interface Feed {
  readonly events: readonly FeedEvent[];
  readonly live: boolean;
  /** The feed opened on the end of a long log: earlier lines are not shown. */
  readonly cut: boolean;
  /** The log file it reads (its integrate has its own), null before the first answer or while it has none. */
  readonly log: string | null;
  readonly failed: boolean;
}

const EMPTY: Feed = { events: [], live: false, cut: false, log: null, failed: false };

/** Poll one item's feed every FEED_MS while `on`; a new log (its integrate, a new try) starts the list afresh. */
export function useFeed(key: string, on: boolean): Feed {
  const [feed, setFeed] = useState<Feed>(EMPTY);
  const cursor = useRef<{ log: string | null; offset: number }>({ log: null, offset: 0 });
  useEffect(() => {
    if (!on) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    cursor.current = { log: null, offset: 0 }; // the panel is keyed by its item: a new key mounts a new feed
    const poll = async (): Promise<void> => {
      const c = cursor.current;
      try {
        const q: Record<string, string> = { key };
        if (c.log !== null) Object.assign(q, { log: c.log, after: String(c.offset) });
        const a = await get("GET /api/item/feed", q);
        if (stop) return;
        const fresh = a.log !== c.log;
        cursor.current = { log: a.log, offset: a.offset };
        setFeed((f) => {
          const events = fresh ? a.events : a.events.length === 0 ? f.events : [...f.events, ...a.events];
          return { events: events.length > FEED_KEEP ? events.slice(-FEED_KEEP) : events, live: a.live, cut: fresh ? a.cut : f.cut || events.length > FEED_KEEP, log: a.log, failed: false };
        });
      } catch {
        if (!stop) setFeed((f) => ({ ...f, failed: true }));
      }
      if (!stop) timer = setTimeout(() => void poll(), FEED_MS);
    };
    void poll();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [key, on]);
  return feed;
}

/** One line of the feed as the page draws it: a tool call carries its result once it came. */
export type FeedRow =
  | { readonly k: "say"; readonly text: string }
  | { readonly k: "owner"; readonly text: string }
  | { readonly k: "line"; readonly text: string }
  | { readonly k: "tool"; readonly name: string; readonly arg: string; readonly result: { readonly ok: boolean; readonly text: string } | null }
  | { readonly k: "start"; readonly model: string }
  | { readonly k: "end"; readonly ok: boolean; readonly text: string };

export function rowsOf(events: readonly FeedEvent[]): FeedRow[] {
  const rows: FeedRow[] = [];
  const open = new Map<string, number>();
  for (const e of events) {
    if (e.k === "tool") {
      if (e.id !== "") open.set(e.id, rows.length);
      rows.push({ k: "tool", name: e.name, arg: e.arg, result: null });
    } else if (e.k === "result") {
      const at = open.get(e.id) ?? -1;
      const row = rows[at];
      if (row?.k === "tool") rows[at] = { ...row, result: { ok: e.ok, text: e.text } };
    } else rows.push(e);
  }
  return rows;
}

/** The worker's own last sentence: what it says it is doing now. */
export function headlineOf(events: readonly FeedEvent[]): string | null {
  for (let n = events.length - 1; n >= 0; n--) {
    const e = events[n];
    if (e?.k === "say") return e.text.split("\n").find((l) => l.trim() !== "")?.trim() ?? null;
  }
  return null;
}
