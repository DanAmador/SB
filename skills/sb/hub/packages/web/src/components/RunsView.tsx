/**
 * Runs, the landing view: one row per worker run on a ticket, the silent ones amber, the blocked ones red. A row
 * opens the ticket panel (Message, Stop); today's ended runs fold into one line. Chat sessions are not here.
 */
import { IconBan, IconCircleCheck, IconMail, IconRobot, IconX } from "@tabler/icons-react";
import type * as React from "react";
import type { QueueItem } from "@sb-hub/contract";
import { ago, dur, endedToday, mapTitle, plainReason, itemProject, itemTitle, plural, runRows, type RunRow, type RunTone } from "@/lib/board.ts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { setLink } from "@/lib/link.ts";
import { cn } from "@/lib/utils";
import { Empty, FileLinks, Fold, ToneIcon, VaultLink } from "./bits.tsx";
import { useBoard } from "./context.tsx";

const DOT: Readonly<Record<RunTone, [string, string]>> = {
  ok: ["bg-ok", "running"],
  quiet: ["bg-warn", "no report for 5 minutes or more"],
  blocked: ["bg-destructive", "blocked"],
};

export function RunsView(): React.JSX.Element {
  const { state, ix, qv } = useBoard();
  const rows = runRows(state, ix);
  const ended = endedToday(state);
  const nextWords = qv.next.length === 0 ? "Nothing is queued." : `${plural(qv.next.length, "item")} up next${state.queue.paused ? ", and the queue is paused" : ""}.`;
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
      <h2 className="sr-only">Runs</h2>
      {rows.length === 0 ? (
        <Empty>{`No worker is running. ${nextWords}`}</Empty>
      ) : (
        <ul aria-label="Running now" className="flex flex-col divide-y rounded-xl border bg-card">
          {rows.map((r) => (
            <RunLine key={r.item.key} r={r} />
          ))}
        </ul>
      )}
      {ended.length > 0 && (
        <Fold summary={<EndedSummary ended={ended} />}>
          <ul aria-label="Ended today" className="mt-1 flex flex-col divide-y rounded-xl border bg-card">
            {ended.map((i) => (
              <EndedLine key={`${i.key}@${String(i.ended)}`} i={i} />
            ))}
          </ul>
        </Fold>
      )}
    </div>
  );
}

function RunLine({ r }: { r: RunRow }): React.JSX.Element {
  const { state, openMessage, down } = useBoard();
  const [dot, word] = DOT[r.tone];
  const open = (): void => {
    setLink({ t: r.item.key });
  };
  return (
    <li className={cn("group relative flex items-start gap-3 px-4 py-3 first:rounded-t-xl last:rounded-b-xl hover:bg-accent/40", r.tone === "blocked" && "bg-destructive/5", r.tone === "quiet" && "bg-warn-soft/50")}>
      <span role="img" aria-label={word} title={word} className={cn("mt-1.5 size-2.5 shrink-0 rounded-full", dot, r.tone === "ok" && "motion-safe:animate-pulse")} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          <button type="button" onClick={open} className="line-clamp-2 min-w-0 text-left text-sm font-medium after:absolute after:inset-0 after:content-[''] focus-visible:outline-none">
            {r.title}
          </button>
          <VaultLink path={r.ticket?.file} what="the ticket" className="relative z-10 -my-1" />
        </div>
        <p className={cn("truncate text-sm", r.tone === "ok" ? "text-muted-foreground" : r.tone === "quiet" ? "text-warn" : "text-destructive")} title={r.last}>
          {r.last}
          <span className="text-muted-foreground"> · {ago(state.now, r.lastAt)}</span>
        </p>
        <div className="relative z-10 mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span title={r.ticket ? mapTitle(r.ticket) : r.map}>{`${r.project} · ${r.mapName}`}</span>
          <span className="inline-flex items-center gap-1">
            <IconRobot className="size-3.5" aria-hidden />
            {r.account}
          </span>
          {r.item.model != null && <Badge>{r.item.model}</Badge>}
          <FileLinks item={r.item} />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <span className="text-sm text-muted-foreground tabular-nums" title={`running for ${dur(r.runFor)}`}>
          {`${String(Math.floor(r.runFor / 60))} min`}
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          disabled={down}
          className="relative z-10"
          aria-label={`Message the worker on ${r.title}`}
          title="Message this worker"
          onClick={() => {
            openMessage(r.item.key);
          }}
        >
          <IconMail aria-hidden />
        </Button>
      </div>
    </li>
  );
}

function EndedSummary({ ended }: { ended: readonly QueueItem[] }): React.JSX.Element {
  const done = ended.filter((i) => i.state === "done").length;
  const bad = ended.length - done;
  return (
    <span className="text-muted-foreground">
      {`${plural(ended.length, "run")} ended today: ${String(done)} done`}
      {bad > 0 && <span className="text-destructive">{`, ${String(bad)} failed or skipped`}</span>}
    </span>
  );
}

const ENDED = {
  done: [IconCircleCheck, "done", "ok"],
  failed: [IconX, "failed", "bad"],
  skipped: [IconBan, "skipped", "warn"],
} as const;

function EndedLine({ i }: { i: QueueItem }): React.JSX.Element {
  const { state, ix } = useBoard();
  const st = i.state === "done" || i.state === "skipped" ? i.state : "failed";
  const [Ic, word, tone] = ENDED[st];
  const t = ix.byKey.get(i.key);
  return (
    <li className="flex items-center gap-3 px-4 py-2 text-sm">
      <ToneIcon icon={Ic} tone={tone} label={word} />
      <button
        type="button"
        className="min-w-0 flex-1 truncate text-left hover:underline"
        onClick={() => {
          setLink({ t: i.key });
        }}
      >
        {itemTitle(i, t)}
        {i.state !== "done" && <span className={i.state === "skipped" ? "text-warn" : "text-destructive"}> · {plainReason(i)}</span>}
      </button>
      <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">{itemProject(i, t)}</span>
      <FileLinks item={i} />
      <span className="w-16 shrink-0 text-right text-xs text-muted-foreground">{ago(state.now, i.ended)}</span>
    </li>
  );
}
