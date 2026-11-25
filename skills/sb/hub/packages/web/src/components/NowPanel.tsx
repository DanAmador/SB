/**
 * The Now panel, beside every view: what runs, what is queued and why it waits, and today as one day's clock with a
 * block per run. It reads the whole queue, so a job or ticket outside the live run (a close-off job, anything queued
 * while no run is live) shows too. Wide screens get a column on the right that folds to a strip; narrow ones a fold
 * above the view. The fold is remembered per browser.
 */
import { IconChevronRight, IconLayoutSidebarRightCollapse, IconLayoutSidebarRightExpand } from "@tabler/icons-react";
import { useSyncExternalStore } from "react";
import type * as React from "react";
import type { QueueItem } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { dayStart, hm, itemTitle, mapTitle, plural } from "@/lib/board.ts";
import { useRuns } from "@/lib/hub.ts";
import { setLink } from "@/lib/link.ts";
import { dayBlocks, nowNext, type DayBlock } from "@/lib/now.ts";
import { StuckFlag } from "./StuckFlag.tsx";
import { waitWords } from "@/lib/night.ts";
import { Store } from "@/lib/store.ts";
import { cn } from "@/lib/utils";
import { TicketTitle } from "./bits.tsx";
import { useBoard } from "./context.tsx";

const KEY = "sbhub.nowPanel";
const read = (): boolean => {
  try {
    return localStorage.getItem(KEY) !== "closed";
  } catch {
    return true;
  }
};
const openStore = new Store<boolean>(typeof window === "undefined" ? true : read());
function setOpen(open: boolean): void {
  openStore.set(open);
  try {
    localStorage.setItem(KEY, open ? "open" : "closed");
  } catch {
    // a private window: the fold lasts until reload
  }
}

const WIDE = "(min-width: 64rem)";
const wideNow = (): boolean => typeof matchMedia === "function" && matchMedia(WIDE).matches;
const onWide = (fn: () => void): (() => void) => {
  if (typeof matchMedia !== "function") return () => undefined;
  const m = matchMedia(WIDE);
  m.addEventListener("change", fn);
  return () => {
    m.removeEventListener("change", fn);
  };
};

/** The panel's one-line count: "2 running · 3 queued". */
const countWords = (running: number, queued: number): string => (running + queued === 0 ? "nothing running or queued" : [running > 0 ? `${String(running)} running` : "", queued > 0 ? `${String(queued)} queued` : ""].filter(Boolean).join(" · "));

/** `side` renders on wide screens only, `top` on narrow ones only: the board places both. */
export function NowPanel({ at }: { at: "side" | "top" }): React.JSX.Element | null {
  const { state } = useBoard();
  const open = useSyncExternalStore(openStore.subscribe, openStore.get, () => true);
  const wide = useSyncExternalStore(onWide, wideNow, () => true);
  const n = nowNext(state.queue.items);
  const count = countWords(n.running.length, n.queued.length);
  if (wide !== (at === "side")) return null;
  if (!wide) {
    return (
      <details
        open={open}
        onToggle={(ev) => {
          setOpen(ev.currentTarget.open);
        }}
        data-testid="now-panel"
        className="group rounded-xl border bg-card"
      >
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm [&::-webkit-details-marker]:hidden">
          <IconChevronRight className="size-4 shrink-0 transition-transform group-open:rotate-90" aria-hidden />
          <span className="font-semibold">Now</span>
          <span className="truncate text-muted-foreground">{count}</span>
        </summary>
        <div className="border-t px-3 py-3">
          <Body />
        </div>
      </details>
    );
  }
  if (!open) {
    return (
      <aside aria-label="Now and next" data-testid="now-panel" className="sticky top-[57px] flex h-[calc(100dvh-57px)] w-10 shrink-0 flex-col items-center gap-3 border-l py-3">
        <Button variant="ghost" size="icon-sm" aria-label={`Show Now: ${count}`} title="Show what runs, what is queued and today" onClick={() => { setOpen(true); }}>
          <IconLayoutSidebarRightExpand aria-hidden />
        </Button>
        {n.running.length > 0 && <span className="size-2.5 rounded-full bg-ok motion-safe:animate-pulse" role="img" aria-label={`${String(n.running.length)} running`} />}
        {n.queued.length > 0 && <span className="text-xs text-muted-foreground tabular-nums" title={`${String(n.queued.length)} queued`}>{n.queued.length}</span>}
      </aside>
    );
  }
  return (
    <aside aria-label="Now and next" data-testid="now-panel" className="sticky top-[57px] flex h-[calc(100dvh-57px)] w-80 shrink-0 flex-col gap-4 overflow-y-auto border-l px-4 py-5">
      <header className="flex items-center gap-2">
        <h2 className="text-sm font-semibold">Now</h2>
        <span className="truncate text-xs text-muted-foreground">{count}</span>
        <Button variant="ghost" size="icon-sm" className="ml-auto" aria-label="Hide Now" title="Hide this panel" onClick={() => { setOpen(false); }}>
          <IconLayoutSidebarRightCollapse aria-hidden />
        </Button>
      </header>
      <Body />
    </aside>
  );
}

function Body(): React.JSX.Element {
  const { state, ix, tickets } = useBoard();
  const n = nowNext(state.queue.items);
  const titleOf = (i: QueueItem): string => itemTitle(i, ix.byKey.get(i.key));
  const name = (k: string): string => {
    const t = ix.byKey.get(k);
    if (t) return t.title;
    const inMap = tickets?.find((x) => x.map === k);
    return inMap ? mapTitle(inMap) : k;
  };
  // a run starts only on Start: with none live, a queued ticket waits for it (a close-off or hub job does not)
  const forStart = (i: QueueItem): boolean => state.queue.night === null && !i.night && !(i.kind === "job" && (i.close_off === true || i.hub === true));
  const why = (i: QueueItem): string =>
    i.waits !== undefined ? waitWords(i.waits, name) : forStart(i) ? "waits for Start" : state.queue.paused ? "the queue is paused" : "starts when an account is free";
  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Running" className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-muted-foreground uppercase">{`Running (${String(n.running.length)})`}</h3>
        {n.running.length === 0 ? (
          <p className="text-sm text-muted-foreground">No worker is running.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {n.running.map((i) => (
              <li key={i.key} className="flex items-start gap-2 text-sm">
                <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", i.state === "running" ? "bg-ok motion-safe:animate-pulse" : "bg-brand")} aria-hidden />
                <span className="min-w-0 flex-1">
                  <TicketTitle itemKey={i.key} links={i.links} className="line-clamp-2">
                    {titleOf(i)}
                  </TicketTitle>
                  <span className="block truncate text-xs text-muted-foreground">
                    {[i.kind === "job" ? "job" : "", i.state === "running" ? (i.runner ?? i.agent ?? "") : i.state === "review" ? "second pass" : "in checks", i.started != null ? `${String(Math.floor((state.now - i.started) / 60))} min` : ""].filter(Boolean).join(" · ")}
                  </span>
                  <StuckFlag item={i} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-label="Queued" className="flex flex-col gap-1">
        <h3 className="text-xs font-medium text-muted-foreground uppercase">{`Queued (${String(n.queued.length)})`}</h3>
        {n.queued.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing is queued.</p>
        ) : (
          <ol className="flex flex-col gap-1.5">
            {n.queued.map((i, at) => (
              <li key={i.key} className="flex items-start gap-2 text-sm">
                <span className="w-5 shrink-0 text-right text-xs text-muted-foreground tabular-nums">{at + 1}</span>
                <span className="min-w-0 flex-1">
                  <TicketTitle itemKey={i.key} links={i.links} className="line-clamp-2">
                    {titleOf(i)}
                  </TicketTitle>
                  <span className="block truncate text-xs text-muted-foreground" title={why(i)}>
                    {`${i.kind === "job" ? "job · " : ""}${why(i)}`}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        )}
        {n.closeOff !== null && (
          <p data-testid="close-off-next" className="text-xs text-muted-foreground">
            {n.closeOff.not_before != null ? `Morning note at ${hm(n.closeOff.not_before)}` : "Morning note next"}
          </p>
        )}
      </section>
      <Today running={n.running} titleOf={titleOf} />
    </div>
  );
}

const HOUR_PX = 44;
/** An hour mark in the reader's own clock: "10 AM" or "10". */
const hourWord = (sec: number): string => new Date(sec * 1000).toLocaleTimeString([], { hour: "numeric" });
const TONES: Readonly<Record<DayBlock["outcome"], string>> = {
  done: "border-ok bg-ok/15",
  failed: "border-destructive bg-destructive-soft",
  skipped: "border-warn bg-warn-soft",
  unknown: "border-muted-foreground bg-muted",
  running: "border-brand bg-brand-soft",
};

/** Today on one clock: from the hour the first run began (or the last hour) to now, a block per run. */
function Today({ running, titleOf }: { running: readonly QueueItem[]; titleOf: (i: QueueItem) => string }): React.JSX.Element {
  const { state } = useBoard();
  const from = dayStart(state.now);
  const runs = useRuns(from, 200);
  const { blocks, lanes } = dayBlocks(runs.data?.runs ?? [], running, titleOf, from, state.now);
  const done = blocks.filter((b) => b.outcome === "done").length;
  const short = blocks.filter((b) => b.outcome === "failed" || b.outcome === "skipped").length;
  const hourOf = (t: number): number => Math.floor((t - from) / 3600);
  const first = Math.min(hourOf(state.now) - 1, ...blocks.map((b) => hourOf(b.start)));
  const top = from + Math.max(0, first) * 3600;
  const hours = Math.max(1, Math.ceil((state.now - top) / 3600));
  const y = (t: number): number => ((t - top) / 3600) * HOUR_PX;
  return (
    <section aria-label="Today" className="flex flex-col gap-1">
      <h3 className="text-xs font-medium text-muted-foreground uppercase">
        Today
        <span className="ml-2 normal-case">{[plural(done, "done", "done"), short > 0 ? `${String(short)} fell short` : ""].filter(Boolean).join(" · ")}</span>
      </h3>
      <div className="relative mt-3 ml-11 border-l" style={{ height: hours * HOUR_PX }} data-testid="today-clock">
        {Array.from({ length: hours + 1 }, (_, h) => (
          <div key={h} className="absolute inset-x-0 border-t border-dashed border-border/70" style={{ top: h * HOUR_PX }}>
            <span className="absolute -top-2 -left-11 w-9 text-right text-[10px] whitespace-nowrap text-muted-foreground tabular-nums">{hourWord(top + h * 3600)}</span>
          </div>
        ))}
        <div className="absolute inset-x-0 border-t border-brand" style={{ top: y(state.now) }} aria-hidden />
        {blocks.map((b) => (
          <button
            key={`${b.key}@${String(b.start)}`}
            type="button"
            data-outcome={b.outcome}
            title={`${b.title}\n${hm(b.start)}–${b.outcome === "running" ? "now" : hm(b.end)} · ${b.outcome}${b.account !== null ? ` · ${b.account}` : ""}`}
            aria-label={`${b.title}, ${b.outcome}, ${hm(b.start)} to ${b.outcome === "running" ? "now" : hm(b.end)}`}
            onClick={() => {
              setLink(b.outcome === "running" ? { t: b.key } : { view: "history", run: b.key, pic: "" });
            }}
            className={cn("absolute overflow-hidden rounded-sm border-l-2 px-1 text-left text-[10px] leading-tight text-foreground hover:ring-2 hover:ring-ring focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", TONES[b.outcome])}
            style={{ top: y(b.start), height: Math.max(4, y(b.end) - y(b.start)), left: `calc(${String((b.lane / lanes) * 100)}% + 2px)`, width: `calc(${String(100 / lanes)}% - 4px)` }}
          >
            {y(b.end) - y(b.start) >= 14 && <span className="line-clamp-2">{b.title}</span>}
          </button>
        ))}
      </div>
    </section>
  );
}
