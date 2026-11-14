/**
 * Queue: a table of tickets on top, filtered, sorted and ticked, with a bar that queues or acts on the ticked (a row
 * also drags into Up next); below it Up next in order, dragged to reorder, each with its account and a remove button.
 */
import { IconArrowBackUp, IconChevronDown, IconChevronUp, IconClock, IconGripVertical, IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { QueueItem } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { blockerTitles, isScoped, scopeItems, firstLine, hm, itemProject, itemTitle } from "@/lib/board.ts";
import { cn } from "@/lib/utils";
import { SectionTitle, TicketTitle } from "./bits.tsx";
import { AccountPicker } from "./AccountPicker.tsx";
import { DRAG_TYPE, TicketTable } from "./TicketTable.tsx";
import { useBoard } from "./context.tsx";

/** What is being dragged: a found ticket to add, or a queued one to move. */
type Drag = { kind: "add" | "move"; key: string } | null;
/** Up next shows this many; the rest fold. */
const NEXT = 10;

export function QueueView(): React.JSX.Element {
  const [drag, setDrag] = useState<Drag>(null);
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
      <TicketTable drag={{ key: drag?.key, start: (key) => { setDrag({ kind: "add", key }); }, end: () => { setDrag(null); } }} />
      <UpNext drag={drag} setDrag={setDrag} />
    </div>
  );
}

// ---- up next ----

function UpNext({ drag, setDrag }: { drag: Drag; setDrag: (d: Drag) => void }): React.JSX.Element {
  const { state, qv, scope, enqueue, move, unqueue, queueWrite, down, busy } = useBoard();
  const [over, setOver] = useState<number | "end" | null>(null);
  const [all, setAll] = useState(false);
  const can = !down && !busy;
  const next = scopeItems(scope, qv.next);
  const list = all ? next : next.slice(0, NEXT);
  const drop = (at: number | null): void => {
    setOver(null);
    const d = drag;
    setDrag(null);
    if (d === null) return;
    if (d.kind === "add") void enqueue(d.key, at ?? undefined);
    else {
      const from = qv.queuedKeys.indexOf(d.key);
      const to = at ?? qv.queuedKeys.length - 1;
      if (from >= 0 && to !== from) void move(d.key, to);
    }
  };
  return (
    <section
      aria-labelledby="next-title"
      className={cn("min-w-0 rounded-xl transition-colors", drag && "bg-brand-soft/40 outline-2 outline-dashed outline-brand/50 outline-offset-4")}
      data-testid="up-next"
      onDragOver={(ev) => {
        if (drag === null) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = "move";
        if (ev.target === ev.currentTarget) setOver("end");
      }}
      onDragLeave={(ev) => {
        if (!ev.currentTarget.contains(ev.relatedTarget as Node | null)) setOver(null);
      }}
      onDrop={(ev) => {
        ev.preventDefault();
        drop(null);
      }}
    >
      <SectionTitle
        aside={
          state.queue.paused ? (
            <Badge tone="warn">paused</Badge>
          ) : undefined
        }
      >
        <span id="next-title">Up next</span>
      </SectionTitle>
      {next.length === 0 ? (
        <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          {isScoped(scope) && qv.next.length > 0 ? "Nothing queued here. " : "Nothing queued. "} Tick tickets above and queue them, or drag one here.
        </div>
      ) : (
        <ol className="flex flex-col divide-y rounded-lg border bg-card">
          {list.map((i, n) => {
            const at = i.kind === "ticket" ? qv.queuedKeys.indexOf(i.key) : -1;
            return (
              <NextLine
                key={i.key}
                i={i}
                n={n + 1}
                at={at}
                last={at === qv.queuedKeys.length - 1}
                can={can}
                over={over === at && at >= 0}
                dragging={drag?.key === i.key}
                onDragStart={() => {
                  setDrag({ kind: "move", key: i.key });
                }}
                onDragEnd={() => {
                  setDrag(null);
                  setOver(null);
                }}
                onOver={() => {
                  if (at >= 0) setOver(at);
                }}
                onDrop={() => {
                  drop(at >= 0 ? at : null);
                }}
                onMove={(to) => {
                  void move(i.key, to);
                }}
                onUnqueue={() => {
                  if (i.kind === "ticket") void unqueue(i.key);
                  else void queueWrite("POST /api/queue/remove_job", { key: i.key, version: state.queue.version }, "Job removed. You can queue it again, corrected.");
                }}
              />
            );
          })}
        </ol>
      )}
      {next.length > NEXT && (
        <Button
          variant="ghost"
          size="xs"
          className="mt-1 text-muted-foreground"
          aria-expanded={all}
          onClick={() => {
            setAll(!all);
          }}
        >
          {all ? <IconChevronUp aria-hidden /> : <IconChevronDown aria-hidden />}
          {all ? `Show the first ${String(NEXT)}` : `${String(next.length - NEXT)} more after these`}
        </Button>
      )}
    </section>
  );
}

function NextLine(props: {
  i: QueueItem;
  n: number;
  at: number;
  last: boolean;
  can: boolean;
  over: boolean;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onOver: () => void;
  onDrop: () => void;
  onMove: (to: number) => void;
  onUnqueue: () => void;
}): React.JSX.Element {
  const { i, n, at, last, can, over, dragging } = props;
  const { state, ix } = useBoard();
  const t = ix.byKey.get(i.key);
  const title = itemTitle(i, t);
  const isT = i.kind === "ticket";
  const after = t ? blockerTitles(t, ix) : [];
  const tier = i.model ?? t?.tier;
  return (
    <li
      draggable={can && isT}
      data-key={i.key}
      onDragStart={(ev) => {
        ev.dataTransfer.setData(DRAG_TYPE, i.key);
        ev.dataTransfer.setData("text/plain", i.key);
        ev.dataTransfer.effectAllowed = "move";
        props.onDragStart();
      }}
      onDragEnd={props.onDragEnd}
      onDragOver={(ev) => {
        ev.preventDefault();
        props.onOver();
      }}
      onDrop={(ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        props.onDrop();
      }}
      className={cn(
        "group relative flex items-center gap-2 px-2 py-2 first:rounded-t-lg last:rounded-b-lg",
        dragging && "opacity-40",
        over && "before:absolute before:inset-x-2 before:-top-px before:h-0.5 before:rounded-full before:bg-brand",
      )}
    >
      <span className={cn("flex w-8 shrink-0 items-center justify-end gap-0.5 text-xs text-muted-foreground tabular-nums", isT && can && "cursor-grab")}>
        {isT && can && <IconGripVertical className="size-3.5 opacity-0 group-hover:opacity-100" aria-hidden />}
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          <TicketTitle itemKey={i.key} links={i.links} className="line-clamp-2">
            {title}
          </TicketTitle>
        </div>
        <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <span className="shrink-0">{itemProject(i, t)}</span>
          {i.kind === "job" && <span className="truncate">{firstLine(i.prompt)}</span>}
          {after.length > 0 && <span className="truncate">after {after.join(", ")}</span>}
          {tier != null && tier !== "sonnet" && <Badge>{tier}</Badge>}
          {i.tries > 0 && <Badge tone="warn">second try</Badge>}
          {i.kind === "job" && i.not_before !== undefined && i.not_before > state.now && (
            <Badge>
              <IconClock aria-hidden />
              at {hm(i.not_before)}
            </Badge>
          )}
        </div>
      </div>
      <AccountPicker itemKey={i.key} chosen={i.agent} title={title} />
      <div className="flex shrink-0 items-center opacity-100 sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
        {isT && (
          <>
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={!can || at <= 0}
              aria-label={`Move ${title} up`}
              onClick={() => {
                props.onMove(at - 1);
              }}
            >
              <IconChevronUp aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={!can || at < 0 || last}
              aria-label={`Move ${title} down`}
              onClick={() => {
                props.onMove(at + 1);
              }}
            >
              <IconChevronDown aria-hidden />
            </Button>
          </>
        )}
        <Button variant="ghost" size="icon-sm" disabled={!can} aria-label={isT ? `Unqueue ${title}` : `Remove the job ${title}`} title={isT ? "Unqueue" : "Remove the job"} onClick={props.onUnqueue}>
          {isT ? <IconArrowBackUp aria-hidden /> : <IconX aria-hidden />}
        </Button>
      </div>
    </li>
  );
}

