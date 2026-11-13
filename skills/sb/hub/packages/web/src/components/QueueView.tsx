/**
 * Queue: a search on top that finds open tickets by project, map or title and queues them in one click (or a drag
 * into Up next); below it Up next in order, dragged to reorder, each with its account and a remove button.
 */
import { IconArrowBackUp, IconChevronDown, IconChevronUp, IconClock, IconGripVertical, IconSearch, IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { QueueItem, TicketRow } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { addable, blockerTitles, filterOptions, firstLine, hm, itemProject, itemTitle, mapTitle, plural, projOf, searchTickets, showCounts, tkey, type Show } from "@/lib/board.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { cn } from "@/lib/utils";
import { Empty, MapName, SectionTitle, TicketTitle } from "./bits.tsx";
import { AccountPicker, QueueButton } from "./AccountPicker.tsx";
import { useBoard } from "./context.tsx";

/** What is being dragged: a found ticket to add, or a queued one to move. */
type Drag = { kind: "add" | "move"; key: string } | null;
const DRAG_TYPE = "application/x-sb-ticket";
/** The search shows this many tickets, fewer before anything is typed so Up next stays in view; more means narrow it. */
const SHOWN = 12;
const SHOWN_IDLE = 5;
/** Up next shows this many; the rest fold. */
const NEXT = 10;

export function QueueView(): React.JSX.Element {
  const [drag, setDrag] = useState<Drag>(null);
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
      <Search drag={drag} setDrag={setDrag} />
      <UpNext drag={drag} setDrag={setDrag} />
    </div>
  );
}

// ---- the search ----

const SHOW_WORDS: readonly [Show, string][] = [
  ["ready", "Can run"],
  ["waits", "Needs a decision"],
  ["later", "Not yet"],
];

function Search({ drag, setDrag }: { drag: Drag; setDrag: (d: Drag) => void }): React.JSX.Element {
  const link = useLink();
  const { tickets, ix } = useBoard();
  const all = tickets ?? [];
  const hits = searchTickets(all, ix, link);
  const counts = showCounts(all, ix, link);
  const { projects, maps } = filterOptions(all, link);
  const filtered = Boolean(link.q || link.p || link.m);
  const shown = hits.slice(0, filtered ? SHOWN : SHOWN_IDLE);
  return (
    <section aria-labelledby="find-title" className="flex flex-col gap-3">
      <h2 id="find-title" className="sr-only">
        Find a ticket to queue
      </h2>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="relative min-w-0 flex-1">
          <IconSearch className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            data-find
            className="h-9 w-full pl-9"
            placeholder="Find an open ticket by project, map or title"
            aria-label="Find an open ticket by project, map or title"
            maxLength={200}
            defaultValue={link.q}
            onChange={(ev) => {
              setLink({ q: ev.currentTarget.value.trim() });
            }}
          />
        </div>
        <div className="flex gap-2">
          <Select
            aria-label="Project"
            className="h-9 min-w-0 flex-1 sm:w-40"
            value={link.p}
            onChange={(ev) => {
              setLink({ p: ev.currentTarget.value });
            }}
          >
            <option value="">Every project</option>
            {projects.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Map"
            className="h-9 min-w-0 flex-1 sm:w-48"
            value={link.m}
            onChange={(ev) => {
              setLink({ m: ev.currentTarget.value });
            }}
          >
            <option value="">Every map</option>
            {maps.map(([m, title]) => (
              <option key={m} value={m}>
                {title}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <div role="radiogroup" aria-label="Which open tickets" className="flex flex-wrap gap-1.5">
        {SHOW_WORDS.map(([v, words]) => (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={link.s === v}
            onClick={() => {
              setLink({ s: v });
            }}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              link.s === v ? "border-foreground bg-foreground text-background" : "text-muted-foreground hover:border-foreground/40 hover:text-foreground",
            )}
          >
            {words}
            <span className="tabular-nums opacity-70">{counts[v]}</span>
          </button>
        ))}
      </div>
      {tickets === null ? (
        <Skeleton className="h-11 w-full" />
      ) : hits.length === 0 ? (
        <Empty>{filtered ? "No open ticket here matches." : link.s === "ready" ? "Nothing can run yet: every open ticket waits on something." : "None."}</Empty>
      ) : (
        <ul aria-label="Found tickets" data-testid="found" className="flex flex-col divide-y rounded-xl border bg-card">
          {shown.map((t) => (
            <Found key={tkey(t)} t={t} drag={drag} setDrag={setDrag} />
          ))}
          {hits.length > shown.length && <li className="px-4 py-2 text-xs text-muted-foreground">{`${plural(hits.length - shown.length, "more ticket")}: type, or pick a project or map, to narrow it.`}</li>}
        </ul>
      )}
    </section>
  );
}

function Found({ t, drag, setDrag }: { t: TicketRow; drag: Drag; setDrag: (d: Drag) => void }): React.JSX.Element {
  const { ix, qv, state, down, busy } = useBoard();
  const key = tkey(t);
  const item = state.queue.items.find((i) => i.key === key && (i.state === "queued" || i.state === "running"));
  const can = item === undefined && addable(t, ix);
  const after = blockerTitles(t, ix);
  const why = item?.state === "running" ? "running now" : item ? `number ${String(qv.queuedKeys.indexOf(key) + 1)} in line` : after.length > 0 ? `after ${after.join(", ")}` : t.state === "waits for you" ? t.type : can ? "" : t.reason;
  const draggable = can && !down && !busy;
  return (
    <li
      draggable={draggable}
      data-key={key}
      onDragStart={(ev) => {
        ev.dataTransfer.setData(DRAG_TYPE, key);
        ev.dataTransfer.setData("text/plain", key);
        ev.dataTransfer.effectAllowed = "move";
        setDrag({ kind: "add", key });
      }}
      onDragEnd={() => {
        setDrag(null);
      }}
      className={cn("flex items-center gap-3 px-4 py-2.5 first:rounded-t-xl last:rounded-b-xl", draggable && "cursor-grab", drag?.key === key && "opacity-40")}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          <TicketTitle itemKey={key} links={t.links} className="line-clamp-2">
            {t.title}
          </TicketTitle>
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {`${projOf(t.map)} · `}
          <MapName links={t.links} name={t.map.split("/").pop() ?? ""} title={mapTitle(t)} />
          {why && ` · ${why}`}
        </p>
      </div>
      {can && <QueueButton itemKey={key} title={t.title} />}
    </li>
  );
}

// ---- up next ----

function UpNext({ drag, setDrag }: { drag: Drag; setDrag: (d: Drag) => void }): React.JSX.Element {
  const { state, qv, enqueue, move, unqueue, queueWrite, down, busy } = useBoard();
  const [over, setOver] = useState<number | "end" | null>(null);
  const [all, setAll] = useState(false);
  const can = !down && !busy;
  const list = all ? qv.next : qv.next.slice(0, NEXT);
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
      {qv.next.length === 0 ? (
        <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          Nothing queued. Find a ticket above and queue it, or drag it here.
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
      {qv.next.length > NEXT && (
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
          {all ? `Show the first ${String(NEXT)}` : `${String(qv.next.length - NEXT)} more after these`}
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

