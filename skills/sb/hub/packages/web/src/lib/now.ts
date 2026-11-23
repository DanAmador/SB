/**
 * The Now panel's rules: what the queue works on and what it starts next, whichever run an item belongs to (a
 * close-off job belongs to none), and today's runs as blocks on one day's clock.
 */
import type { QueueItem, Run } from "@sb-hub/contract";

/** A worker has it or the hub is checking what it landed. */
const BUSY: readonly string[] = ["running", "landed", "review", "recheck"];

export interface NowNext {
  readonly running: readonly QueueItem[];
  /** In the order they start, without the waiting close-off job. */
  readonly queued: readonly QueueItem[];
  /**
   * The morning close-off job while it waits for its hour. The hub queues the next one as soon as the last has run,
   * so it is nearly always there: the panel gives it one quiet line, not a place in the queue.
   */
  readonly closeOff: JobItem | null;
}

type JobItem = Extract<QueueItem, { kind: "job" }>;
const waitingCloseOff = (i: QueueItem): i is JobItem => i.state === "queued" && i.kind === "job" && i.close_off === true;

export const nowNext = (items: readonly QueueItem[]): NowNext => ({
  running: items.filter((i) => BUSY.includes(i.state)),
  queued: items.filter((i) => i.state === "queued" && !waitingCloseOff(i)),
  closeOff: items.find(waitingCloseOff) ?? null,
});

export interface DayBlock {
  readonly key: string;
  readonly title: string;
  readonly outcome: Run["outcome"] | "running";
  readonly account: string | null;
  /** Clipped to the day: a run that began yesterday starts at midnight. */
  readonly start: number;
  readonly end: number;
  /** Its column: runs that overlap sit side by side. */
  readonly lane: number;
}

/**
 * Today's ended runs and what runs now, from `from` (midnight) to `to` (now), each in the first lane free at its start.
 * A run still going comes from the queue, not the run list, so it is not drawn twice.
 */
export function dayBlocks(runs: readonly Run[], running: readonly QueueItem[], title: (i: QueueItem) => string, from: number, to: number): { blocks: DayBlock[]; lanes: number } {
  const raw = [
    ...runs.filter((r) => r.ended !== null && r.ended > from).map((r) => ({ key: r.key, title: r.title, outcome: r.outcome, account: r.account, start: r.started ?? r.ended ?? to, end: r.ended ?? to })),
    ...running.map((i) => ({ key: i.key, title: title(i), outcome: "running" as const, account: i.runner ?? i.agent, start: i.started ?? to, end: to })),
  ]
    .map((b) => ({ ...b, start: Math.max(from, Math.min(b.start, to)), end: Math.max(from, Math.min(b.end, to)) }))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const ends: number[] = [];
  const blocks = raw.map((b) => {
    let lane = ends.findIndex((e) => e <= b.start);
    if (lane < 0) lane = ends.push(0) - 1;
    ends[lane] = b.end;
    return { ...b, lane };
  });
  return { blocks, lanes: Math.max(1, ends.length) };
}
