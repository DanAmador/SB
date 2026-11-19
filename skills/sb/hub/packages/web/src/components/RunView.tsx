/**
 * Run, the landing view, in four tabs under the run's head: Flow (the run's graph, or the picked map's), Now (who is
 * on a ticket and the other chats), Maps (one line of counts, then a block per map, a checklist of its tickets in run
 * order) and Queue (the maps that can be queued and the search that finds one ticket to queue).
 */
import { IconAlertTriangle, IconMap, IconTopologyStar3, IconArrowBackUp, IconBan, IconChevronDown, IconChevronRight, IconChevronUp, IconCircleCheck, IconCircleDashed, IconClock, IconGitCommit, IconGripVertical, IconHourglass, IconLoader2, IconMail, IconMessages, IconPlus, IconRobot, IconX, IconZzz } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { QueueItem } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ago, blockerTitles, sessionOf, brokenBuilds, dur, endsAt, firstLine, hm, itemTitle, mapTitle, plainReason, plural, projOf, runRows, tryOf, showOf, type RunRow, type RunTone, itemInScope, ticketInScope } from "@/lib/board.ts";
import { healthOf, liveState, MARK_WORDS, nightBlocks, nightLine, pairNight, type MapPair, type Mark, type NightBlock, type NightRow, type Pairing } from "@/lib/night.ts";
import { helperCards, sessionCards, type SessionCard } from "@/lib/sessions.ts";
import { RUN_TABS, setLink, useLink } from "@/lib/link.ts";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { Empty, FileLinks, Fold, MapName, SectionTitle, TicketTitle, ToneIcon } from "./bits.tsx";
import { ReviewNow, RowMenu, TickBar, TickBox, WaitReason } from "./RunControls.tsx";
import { MapView } from "./MapView.tsx";
import { NightGraph } from "./NightGraph.tsx";
import { TickedBar, TicketTable } from "./TicketTable.tsx";
import { useBoard } from "./context.tsx";

const DOT: Readonly<Record<RunTone, [string, string]>> = {
  ok: ["bg-ok", "running"],
  quiet: ["bg-warn", "no report for 5 minutes or more"],
  blocked: ["bg-destructive", "blocked"],
};


/** The map a block drags: its name. */
const DRAG_MAP = "application/x-sb-map";

export function RunView(): React.JSX.Element {
  const { state, ix, scope, agents } = useBoard();
  const link = useLink();
  // the live run only: nothing from an ended one
  const night = nightBlocks(liveState(state), ix, scope, true);
  const pairing = pairNight(state, night, sessionCards(state, ix, agents), helperCards(state, ix, agents));
  const stop = night.line.stopAt ?? endsAt(state, ix);
  const live = state.queue.night !== null;
  const running = liveState(state).queue.items.filter((i) => i.state === "running" && itemInScope(scope, i)).length;
  const table = !(scope.map !== "" && link.mv === "table");
  const narrow = "mx-auto flex w-full max-w-4xl flex-col gap-6";
  return (
    <Tabs
      value={link.rt}
      onValueChange={(v) => {
        const rt = RUN_TABS.find((x) => x === v);
        if (rt) setLink({ rt });
      }}
      className="flex flex-col gap-4"
    >
      <h2 className="sr-only">Run</h2>
      {brokenBuilds(state.queue.builds, (k) => ix.byKey.get(k)?.title ?? k).map((line) => (
        <p key={line} role="alert" data-testid="build-broken" className="flex items-center gap-2 rounded-xl bg-destructive-soft px-3 py-2 text-sm text-destructive">
          <IconAlertTriangle className="size-4 shrink-0" aria-hidden />
          {line}
        </p>
      ))}
      <TabsList aria-label="Run" className="w-full max-w-full justify-start overflow-x-auto sm:w-auto sm:self-start">
        <TabsTrigger value="flow">
          <IconTopologyStar3 aria-hidden className="size-4" />
          Flow
        </TabsTrigger>
        <TabsTrigger value="now">
          <IconLoader2 aria-hidden className="size-4" />
          Now
          {running > 0 && <span className="text-xs text-muted-foreground tabular-nums">{running}</span>}
        </TabsTrigger>
        <TabsTrigger value="maps">
          <IconMap aria-hidden className="size-4" />
          Maps
          {night.blocks.length > 0 && <span className="text-xs text-muted-foreground tabular-nums">{night.blocks.length}</span>}
        </TabsTrigger>
        <TabsTrigger value="queue">
          <IconPlus aria-hidden className="size-4" />
          Queue
        </TabsTrigger>
      </TabsList>
      <TabsContent value="flow" className="flex flex-col gap-4 outline-none">
        {scope.map !== "" ? <MapView map={scope.map} /> : <NightGraph />}
        {scope.map !== "" && link.mv !== "table" && <TickedBar />}
      </TabsContent>
      <TabsContent value="now" className={cn(narrow, "outline-none")}>
        <RunningNow />
        <OtherChats pairing={pairing} />
      </TabsContent>
      <TabsContent value="maps" className={cn(narrow, "outline-none")}>
        {live ? (
          <>
            <p data-testid="night-line" className="flex flex-wrap items-center gap-x-2 text-sm">
              <span className="font-medium">{nightLine(night)}</span>
              {stop > state.now && (
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <IconClock className="size-3.5" aria-hidden />
                  {night.line.stopAt !== null ? `the queue stops at ${hm(stop)}` : `the queue ends about ${hm(stop)}`}
                </span>
              )}
              {state.queue.paused && <Badge tone="warn">paused</Badge>}
            </p>
            <MapBlocks night={night} pairing={pairing} />
            <ReviewNow />
            <TickBar items={state.queue.items} />
          </>
        ) : (
          <Empty>No run is live: queue a map or a ticket and a run starts by itself.</Empty>
        )}
      </TabsContent>
      <TabsContent value="queue" className={cn(narrow, "outline-none")}>
        <QueueAMap />
        {table && <TicketTable />}
      </TabsContent>
    </Tabs>
  );
}

/** A map with nothing running, checking or still to come: only finished or stopped tickets. */
const idle = (b: NightBlock): boolean => b.counts.running + b.counts.next + b.counts.checking + b.counts.recheck + b.counts.unclean === 0;

/**
 * The night map by map, a fold per project when there are several (open while it has work left). Inside, the maps
 * with work come first; the finished ones fold away under one line.
 */
function MapBlocks({ night, pairing }: { night: ReturnType<typeof nightBlocks>; pairing: Pairing }): React.JSX.Element {
  if (night.blocks.length === 0) {
    return (
      <section aria-label="The night, map by map" data-testid="blocks" className="flex flex-col gap-3">
        <Empty>Nothing is running, queued or ended today.</Empty>
      </section>
    );
  }
  const projects = new Map<string, NightBlock[]>();
  for (const b of night.blocks) {
    const p = b.project || "Jobs";
    projects.set(p, [...(projects.get(p) ?? []), b]);
  }
  const blocks = (bs: readonly NightBlock[]): React.JSX.Element => {
    const busy = bs.filter((b) => !idle(b));
    const done = bs.filter(idle);
    return (
      <div className="flex flex-col gap-3">
        {busy.map((b) => (
          <Block key={b.map || "jobs"} b={b} queued={night.queuedMaps} pair={pairing.maps.get(b.map)} />
        ))}
        {done.length > 0 && (
          <Fold
            defaultOpen={busy.length === 0 && projects.size === 1}
            summary={<span className="text-muted-foreground">{`Finished, nothing left to run (${String(done.length)})`}</span>}
          >
            <div className="mt-2 flex flex-col gap-3">
              {done.map((b) => (
                <Block key={b.map || "jobs"} b={b} queued={night.queuedMaps} pair={pairing.maps.get(b.map)} />
              ))}
            </div>
          </Fold>
        )}
      </div>
    );
  };
  return (
    <section aria-label="The night, map by map" data-testid="blocks" className="flex flex-col gap-3">
      {projects.size === 1
        ? blocks(night.blocks)
        : [...projects].map(([p, bs]) => {
            const left = bs.filter((b) => !idle(b)).length;
            const running = bs.reduce((n, b) => n + b.counts.running, 0);
            const next = bs.reduce((n, b) => n + b.counts.next, 0);
            return (
              <Fold
                key={p}
                defaultOpen={left > 0}
                summary={
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="font-semibold">{p}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {[plural(bs.length, "map"), running > 0 ? `${String(running)} running` : "", next > 0 ? `${String(next)} next` : "", left === 0 ? "all finished" : ""].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                }
              >
                <div className="mt-2 pl-5">{blocks(bs)}</div>
              </Fold>
            );
          })}
    </section>
  );
}

// ---- running now ----

function RunningNow(): React.JSX.Element {
  const { state, ix, scope } = useBoard();
  const live = liveState(state);
  const rows = runRows(live, ix).filter((r) => itemInScope(scope, r.item));
  const between = live.queue.items.filter((i) => (i.state === "landed" || i.state === "review") && itemInScope(scope, i));
  const next = live.queue.items.find((i) => i.state === "queued" && itemInScope(scope, i));
  function whyWaits(i: QueueItem): string {
    if (state.queue.paused) return "the queue is paused";
    const t = ix.byKey.get(i.key);
    const after = t ? blockerTitles(t, ix) : [];
    if (after.length > 0) return `it waits for ${after.join(", ")}`;
    return "it starts when an account is free";
  }
  return (
    <section aria-label="Running now" className="flex flex-col gap-2">
      <SectionTitle>Running now</SectionTitle>
      {rows.length === 0 && between.length === 0 ? (
        <Empty>{next === undefined ? "No worker is running. Nothing is queued." : `No worker is running. Next: ${itemTitle(next, ix.byKey.get(next.key))}, ${whyWaits(next)}.`}</Empty>
      ) : (
        <ul aria-label="Running now" className="flex flex-col divide-y rounded-xl border bg-card">
          {rows.map((r) => (
            <RunLine key={r.item.key} r={r} />
          ))}
          {between.map((i) => (
            <li key={i.key} data-key={i.key} className="flex items-center gap-3 px-4 py-3 text-sm">
              <ToneIcon icon={IconHourglass} tone="brand" label={i.state === "review" ? "second pass" : "checks"} />
              <TicketTitle itemKey={i.key} links={i.links} className="flex-1 truncate">
                {itemTitle(i, ix.byKey.get(i.key))}
              </TicketTitle>
              <Badge>{i.state === "review" ? "second pass" : "in checks"}</Badge>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RunLine({ r }: { r: RunRow }): React.JSX.Element {
  const { state, openMessage, down } = useBoard();
  const [dot, word] = DOT[r.tone];
  return (
    <li className={cn("group relative flex items-start gap-3 px-4 py-3 first:rounded-t-xl last:rounded-b-xl hover:bg-accent/40", r.tone === "blocked" && "bg-destructive/5", r.tone === "quiet" && "bg-warn-soft/50")}>
      <span role="img" aria-label={word} title={word} className={cn("mt-1.5 size-2.5 shrink-0 rounded-full", dot, r.tone === "ok" && "motion-safe:animate-pulse")} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          <TicketTitle itemKey={r.item.key} links={r.item.links} stretch className="line-clamp-2">
            {r.title}
          </TicketTitle>
        </div>
        <p className={cn("truncate text-sm", r.tone === "ok" ? "text-muted-foreground" : r.tone === "quiet" ? "text-warn" : "text-destructive")} title={r.last}>
          {r.last}
          <span className="text-muted-foreground"> · {ago(state.now, r.lastAt)}</span>
        </p>
        <div className="relative z-10 mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span>
            {`${r.project} · `}
            <MapName links={r.item.links} name={r.mapName} {...(r.ticket ? { title: mapTitle(r.ticket) } : {})} />
          </span>
          <span className="inline-flex items-center gap-1">
            <IconRobot className="size-3.5" aria-hidden />
            {r.account}
          </span>
          {r.item.model != null && <Badge>{r.item.model}</Badge>}
          {tryOf(r.item) !== "" && <Badge>{tryOf(r.item)}</Badge>}
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
            openMessage(sessionOf(r.item));
          }}
        >
          <IconMail aria-hidden />
        </Button>
      </div>
    </li>
  );
}


// ---- one map ----

const MARKS: Readonly<Record<Mark, [typeof IconCircleCheck, "ok" | "bad" | "warn" | "brand" | "muted"]>> = {
  done: [IconCircleCheck, "ok"],
  landed: [IconGitCommit, "warn"],
  running: [IconLoader2, "brand"],
  checking: [IconHourglass, "brand"],
  next: [IconCircleDashed, "muted"],
  short: [IconX, "bad"],
  stopped: [IconBan, "warn"],
  recheck: [IconBan, "warn"],
  unclean: [IconHourglass, "warn"],
};

function Block({ b, queued, pair }: { b: NightBlock; queued: readonly string[]; pair: MapPair | undefined }): React.JSX.Element {
  const { state, queueWrite, down, busy } = useBoard();
  const [open, setOpen] = useState(b.open);
  const [over, setOver] = useState(false);
  const can = !down && !busy;
  const isJobs = b.map === "";
  const reorder = (to: number): void => {
    if (to < 0 || to >= queued.length || to === b.at) return;
    void queueWrite("POST /api/queue/move_map", { map: b.map, to, version: state.queue.version }, "Moved the map.");
  };
  const unqueueMap = (): void => {
    const keep = state.queue.items.filter((i) => i.state === "queued" && i.kind === "ticket" && !b.rows.some((r) => r.item.key === i.key)).map((i) => i.key);
    void queueWrite("POST /api/queue/set", { keys: keep, version: state.queue.version }, `Unqueued ${b.title}.`);
  };
  const hasNext = b.counts.next > 0;
  const id = `block-${b.map || "jobs"}`.replace(/[^a-z0-9-]/gi, "-");
  return (
    <section
      aria-label={b.title}
      data-testid="map-block"
      data-map={b.map}
      onDragOver={(ev) => {
        if (b.at < 0 || !ev.dataTransfer.types.includes(DRAG_MAP)) return;
        ev.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => {
        setOver(false);
      }}
      onDrop={(ev) => {
        setOver(false);
        const from = ev.dataTransfer.getData(DRAG_MAP);
        if (b.at < 0 || from === "" || from === b.map) return;
        ev.preventDefault();
        void queueWrite("POST /api/queue/move_map", { map: from, to: b.at, version: state.queue.version }, "Moved the map.");
      }}
      className={cn("min-w-0 rounded-xl border bg-card", over && "outline-2 outline-dashed outline-brand/60")}
    >
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 px-2 py-2">
        {!isJobs && b.at >= 0 ? (
          <span
            draggable={can}
            title="Drag to reorder"
            aria-hidden
            className={cn("flex shrink-0 text-muted-foreground", can && "cursor-grab")}
            onDragStart={(ev) => {
              ev.dataTransfer.setData(DRAG_MAP, b.map);
              ev.dataTransfer.effectAllowed = "move";
            }}
          >
            <IconGripVertical className="size-4" />
          </span>
        ) : (
          <span className="w-4 shrink-0" aria-hidden />
        )}
        <button type="button" className="flex min-w-0 flex-[1_1_12rem] items-center gap-1.5 rounded-md py-1 text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none" aria-expanded={open} aria-controls={id} onClick={() => { setOpen(!open); }}>
          {open ? <IconChevronDown className="size-4 shrink-0" aria-hidden /> : <IconChevronRight className="size-4 shrink-0" aria-hidden />}
          <span className="min-w-0">
            <span className="block truncate font-medium">{b.title}</span>
            <span className="block truncate text-xs text-muted-foreground">
              {b.project !== "" && `${b.project} · `}
              <span data-testid="counts">{b.line}</span>
            </span>
          </span>
        </button>
        <div className="ml-auto flex shrink-0 items-center">
          {!isJobs && b.at >= 0 && (
            <>
              <Button variant="ghost" size="icon-sm" disabled={!can || b.at <= 0} aria-label={`Move ${b.title} up`} onClick={() => { reorder(b.at - 1); }}>
                <IconChevronUp aria-hidden />
              </Button>
              <Button variant="ghost" size="icon-sm" disabled={!can || b.at >= queued.length - 1} aria-label={`Move ${b.title} down`} onClick={() => { reorder(b.at + 1); }}>
                <IconChevronDown aria-hidden />
              </Button>
            </>
          )}
          {!isJobs && hasNext && (
            <Button variant="ghost" size="xs" disabled={!can} aria-label={`Unqueue this map: ${b.title}`} onClick={unqueueMap}>
              <IconArrowBackUp aria-hidden />
              Unqueue this map
            </Button>
          )}
        </div>
        {!isJobs && pair !== undefined && (
          <p data-testid="in-charge" className="basis-full pl-6 text-xs text-muted-foreground">
            {pair.charge === null ? (
              <span className="inline-flex items-center gap-1">
                <IconRobot className="size-3.5" aria-hidden />
                {pair.head}
              </span>
            ) : (
              <SessionButton c={pair.charge} label="Session in charge: ">
                <IconMessages className="size-3.5 shrink-0" aria-hidden />
                <span className="truncate">{pair.head}</span>
                {pair.charge.silent && <IconZzz className="size-3.5 shrink-0 text-warn" aria-hidden />}
              </SessionButton>
            )}
          </p>
        )}
      </header>
      {open && (
        <>
          <ul id={id} className="flex flex-col divide-y border-t">
            {b.rows.map((r) => (
              <Row key={`${r.item.key}@${String(r.item.ended ?? r.item.started ?? "")}${r.mark}`} r={r} worker={pair?.workers.get(r.item.key)} />
            ))}
          </ul>
          {pair !== undefined && pair.helpers.length > 0 && <Helpers list={pair.helpers} />}
        </>
      )}
    </section>
  );
}

function Row({ r, worker }: { r: NightRow; worker: SessionCard | undefined }): React.JSX.Element {
  const { state, ix, openMessage, queueWrite, unqueue, down, busy } = useBoard();
  const i = r.item;
  const t = ix.byKey.get(i.key);
  const title = itemTitle(i, t);
  const [Ic, tone] = MARKS[r.mark];
  const can = !down && !busy;
  const account = i.runner ?? i.agent ?? state.queue.agent ?? "";
  return (
    <li data-key={i.key} data-mark={r.mark} {...(worker ? { "data-worker": healthOf(worker) } : {})} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
      {r.mark === "next" && <TickBox itemKey={i.key} title={title} />}
      <ToneIcon icon={Ic} tone={tone} label={MARK_WORDS[r.mark]} spin={r.mark === "running"} />
      <div className="min-w-0 flex-1 basis-48">
        <TicketTitle itemKey={i.key} links={i.links} className="line-clamp-2">
          {title}
        </TicketTitle>
        {(r.mark === "short" || r.mark === "landed" || r.mark === "stopped" || r.mark === "recheck" || r.mark === "unclean") && <p className={cn("truncate text-xs", r.mark === "short" ? "text-destructive" : "text-warn")}>{plainReason(i)}</p>}
        {r.mark === "next" && <WaitReason item={i} />}
        {r.mark === "running" && worker === undefined && (
          <p className="truncate text-xs text-muted-foreground" title={firstLine(i.note)}>
            {(agentNote(state, i.key) || firstLine(i.note) || "starting")}
          </p>
        )}
      </div>
      <div className="flex max-w-full shrink-0 items-center gap-2 text-xs text-muted-foreground">
        {tryOf(i) !== "" && <span className="text-warn tabular-nums">{tryOf(i)}</span>}
        {worker !== undefined && <WorkerChip c={worker} item={i} title={title} />}
        {r.mark === "running" && (
          <>
            {worker === undefined && <span className="tabular-nums">{`${String(Math.floor((state.now - (i.started ?? state.now)) / 60))} min`}</span>}
            <Button variant="ghost" size="icon-sm" disabled={down} aria-label={`Message the worker on ${title}`} title="Message this worker" onClick={() => { openMessage(sessionOf(i)); }}>
              <IconMail aria-hidden />
            </Button>
          </>
        )}
        {r.mark === "next" && (
          <>
            <span className="tabular-nums" title="its place in the whole line">{`#${String(r.place ?? 0)}`}</span>
            <RowMenu item={i} title={title} />
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={!can}
              aria-label={i.kind === "ticket" ? `Unqueue ${title}` : `Remove the job ${title}`}
              title={i.kind === "ticket" ? "Unqueue" : "Remove the job"}
              onClick={() => {
                if (i.kind === "ticket") void unqueue(i.key);
                else void queueWrite("POST /api/queue/remove_job", { key: i.key, version: state.queue.version }, "Job removed. You can queue it again, corrected.");
              }}
            >
              {i.kind === "ticket" ? <IconArrowBackUp aria-hidden /> : <IconX aria-hidden />}
            </Button>
          </>
        )}
        {(r.mark === "done" || r.mark === "short" || r.mark === "stopped" || r.mark === "recheck" || r.mark === "unclean") && (
          <>
            <span>{MARK_WORDS[r.mark]}</span>
            <FileLinks item={i} />
            {i.ended != null && <span className="tabular-nums">{ago(state.now, i.ended)}</span>}
          </>
        )}
        {r.mark === "checking" && <Badge>{i.state === "review" ? "second pass" : "in checks"}</Badge>}
        {r.mark === "next" && account !== "" && <span className="sr-only">{`on ${account}`}</span>}
      </div>
    </li>
  );
}

/** A button that opens the session panel (?sess=). */
function SessionButton({ c, label, children, className }: { c: SessionCard; label: string; children: React.ReactNode; className?: string }): React.JSX.Element {
  return (
    <button
      type="button"
      title="Open the session"
      onClick={() => {
        setLink({ sess: c.id });
      }}
      className={cn("inline-flex min-w-0 max-w-full items-center gap-1 rounded-md hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", className)}
    >
      <span className="sr-only">{label}</span>
      {children}
    </button>
  );
}

/** The worker on a ticket: account, last step, minutes, and a mark when it is silent or ended. */
function WorkerChip({ c, item, title }: { c: SessionCard; item: NightRow["item"]; title: string }): React.JSX.Element {
  const { state } = useBoard();
  const h = healthOf(c);
  const mins = Math.floor(((item.ended ?? state.now) - (item.started ?? state.now)) / 60);
  const step = c.now || firstLine(item.note);
  return (
    <SessionButton c={c} label={`Open the worker on ${title}: `} className="max-w-48 flex-col items-end gap-0 py-0.5 sm:max-w-72">
      <span className="flex max-w-full items-center gap-1">
        <IconRobot className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{c.account || "worker"}</span>
        <span className="tabular-nums">{`${String(mins)} min`}</span>
        {h === "silent" && (
          <span data-testid="silent" className="inline-flex items-center gap-0.5 text-warn">
            <IconZzz className="size-3.5" aria-hidden />
            {`silent ${dur(c.quiet)}`}
          </span>
        )}
        {h === "ended" && <span>ended</span>}
        {h === "live" && <span className="sr-only">live</span>}
      </span>
      {step !== "" && <span className="max-w-full truncate" title={step}>{step}</span>}
    </SessionButton>
  );
}

/** What the session in charge started that belongs to no ticket. */
function Helpers({ list }: { list: readonly SessionCard[] }): React.JSX.Element {
  return (
    <details data-testid="helpers" className="border-t px-3 py-2 text-sm">
      <summary className="cursor-pointer text-xs text-muted-foreground">{`Helpers (${String(list.length)})`}</summary>
      <HelperList list={list} />
    </details>
  );
}

function HelperList({ list }: { list: readonly SessionCard[] }): React.JSX.Element {
  const { state } = useBoard();
  return (
    <ul className="mt-1 flex flex-col divide-y">
      {list.map((h) => (
        <li key={h.id} data-worker={healthOf(h)} className="flex items-center gap-2 py-1.5 text-xs">
          <SessionButton c={h} label="Open the helper: " className="flex-1 justify-between gap-2">
            <span className="truncate text-sm">{h.title}</span>
            <span className="inline-flex shrink-0 items-center gap-1 text-muted-foreground">
              {healthOf(h) === "silent" && <IconZzz className="size-3.5 text-warn" aria-hidden />}
              {healthOf(h) === "ended" ? "ended" : healthOf(h) === "silent" ? `silent ${dur(h.quiet)}` : ago(state.now, h.agent.at)}
            </span>
          </SessionButton>
        </li>
      ))}
    </ul>
  );
}

/** A chat heard from longer ago than this folds away under "Quiet for over an hour". */
const QUIET_CHAT = 3600;

/** Chats in charge of no map, each with its helpers folded under it; the quiet ones folded away. */
function OtherChats({ pairing }: { pairing: Pairing }): React.JSX.Element | null {
  if (pairing.chats.length === 0) return null;
  const awake = pairing.chats.filter((c) => c.chat.quiet < QUIET_CHAT);
  const quiet = pairing.chats.filter((c) => c.chat.quiet >= QUIET_CHAT);
  return (
    <section aria-label="Joined chats" data-testid="other-chats" className="rounded-xl border bg-card">
      <header className="flex items-center gap-2 px-3 py-2">
        <IconMessages className="size-4 text-muted-foreground" aria-hidden />
        <h3 className="font-medium">Joined chats</h3>
        <span className="text-xs text-muted-foreground">{`${String(pairing.liveChats)} live`}</span>
      </header>
      {awake.length > 0 && <ChatList list={awake} />}
      {quiet.length > 0 && (
        <details data-testid="quiet-chats" className="border-t">
          <summary className="cursor-pointer px-3 py-2 text-xs text-muted-foreground">{`Quiet for over an hour (${String(quiet.length)})`}</summary>
          <ChatList list={quiet} />
        </details>
      )}
    </section>
  );
}

function ChatList({ list }: { list: Pairing["chats"] }): React.JSX.Element {
  return (
    <ul className="flex flex-col divide-y border-t">
      {list.map(({ chat, helpers }) => (
        <li key={chat.id} className="px-3 py-2 text-sm">
          <SessionButton c={chat} label="Open the chat: " className="gap-2">
            <span className="truncate font-medium">{chat.title}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{`${chat.agent.joined?.role ?? "chat"} · ${chat.project !== "" ? `${chat.project} · ` : ""}${chat.agent.state ?? "working"}${chat.silent ? ` · silent ${dur(chat.quiet)}` : ""}`}</span>
          </SessionButton>
          {helpers.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs text-muted-foreground">{`Helpers (${String(helpers.length)})`}</summary>
              <HelperList list={helpers} />
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}

function agentNote(state: { agents: Record<string, { note?: string | undefined } | undefined>; aliases: Record<string, string> }, key: string): string {
  return state.agents[state.aliases[key] ?? key]?.note ?? "";
}

// ---- queue a map ----

function QueueAMap(): React.JSX.Element | null {
  const { state, tickets, ix, scope, queueWrite, down, busy } = useBoard();
  const can = !down && !busy;
  const queuedMaps = new Set(state.queue.maps ?? []);
  const groups = new Map<string, { title: string; add: number }>();
  for (const t of tickets ?? []) {
    if (!ticketInScope(scope, t)) continue;
    const g = groups.get(t.map) ?? { title: mapTitle(t), add: 0 };
    if (showOf(t, ix) === "ready") g.add += 1;
    groups.set(t.map, g);
  }
  const rows = [...groups].filter(([m, g]) => g.add > 0 && !queuedMaps.has(m) && !state.queue.items.some((i) => i.kind === "ticket" && i.key.startsWith(`${m}#`) && (i.state === "queued" || i.state === "running")));
  if (rows.length === 0) return null;
  return (
    <section aria-label="Queue a map" className="flex flex-col gap-2">
      <SectionTitle>Queue a map</SectionTitle>
      <ul className="flex flex-col divide-y rounded-xl border bg-card">
        {rows.map(([map, g]) => (
          <li key={map} data-map={map} className="flex items-center gap-3 px-3 py-2 text-sm">
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{g.title}</p>
              <p className="truncate text-xs text-muted-foreground">{`${projOf(map)} · would add ${plural(g.add, "ticket")}`}</p>
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={!can}
              aria-label={`Queue ${g.title}`}
              onClick={() => {
                void queueWrite("POST /api/queue/map", { map, version: state.queue.version }, (a) => {
                  const left = a.left_out.length;
                  const added = a.queue.items.filter((i) => i.state === "queued" && i.key.startsWith(`${map}#`)).length;
                  return `Queued ${plural(added, "ticket")} of ${g.title}${left > 0 ? `; left out ${String(left)}: ${[...new Set(a.left_out.map((x) => x.reason))].join("; ")}` : ""}.`;
                });
              }}
            >
              <IconPlus aria-hidden />
              Queue
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
