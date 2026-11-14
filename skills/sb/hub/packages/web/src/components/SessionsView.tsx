/**
 * Sessions, view 4: one card per live session, workers and your chats, each with a small lot-map style map fed by the
 * hub's trail every 2 s. A card opens a Sheet with the big map and the last 16 actions. Red dot: a failure in the last
 * five minutes. Amber ring: silent for five minutes or more. The drawing is lot-map's (src/vendor/lot-map, MIT).
 */
import { IconMail, IconNotebook, IconRobot, IconUser } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import type * as React from "react";
import type { Trail } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ago, dur, SILENT } from "@/lib/board.ts";
import { useTrail } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { entryOf, FEED_ROWS, KIND_WORDS, KINDS, mapSvg, sessionCards, type KindFilter, type SessionCard } from "@/lib/sessions.ts";
import { cn } from "@/lib/utils";
import { STATIONS } from "@/vendor/lot-map/setup.ts";
import { Checks, Empty } from "./bits.tsx";
import { useBoard } from "./context.tsx";

/** Whether the page is dark now: the html element's class, which the theme toggle and the system both set. */
function useDark(): boolean {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const el = document.documentElement;
    const watch = new MutationObserver(() => {
      setDark(el.classList.contains("dark"));
    });
    watch.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => {
      watch.disconnect();
    };
  }, []);
  return dark;
}

const NAMES: Readonly<Record<string, string>> = Object.fromEntries(STATIONS.map((s) => [s.id, s.id]));

/** A failure that ended in the last five minutes. */
const failedLately = (t: Trail | null | undefined, now: number): boolean => (t?.actions ?? []).some((a) => a.ok === false && now - (a.end ?? a.start) < SILENT);

export function SessionsView(): React.JSX.Element {
  const { state, ix, scope } = useBoard();
  const link = useLink();
  const kind: KindFilter = KINDS.find((k) => k === link.kind) ?? "all";
  const all = sessionCards(state, ix).filter((c) => c.kind === "chat" || c.ticketKey === null || scopeHas(scope, c));
  const cards = all.filter((c) => kind === "all" || c.kind === kind);
  const open = all.find((c) => c.id === link.sess) ?? null;
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <h2 className="sr-only">Sessions</h2>
      <div role="group" aria-label="Show" className="flex items-center gap-1.5">
        {KINDS.map((k) => (
          <Button
            key={k}
            size="xs"
            variant={k === kind ? "default" : "outline"}
            aria-pressed={k === kind}
            onClick={() => {
              setLink({ kind: k === "all" ? "" : k });
            }}
          >
            {KIND_WORDS[k]}
            <span className="tabular-nums opacity-70">{k === "all" ? all.length : all.filter((c) => c.kind === k).length}</span>
          </Button>
        ))}
      </div>
      {cards.length === 0 ? (
        <Empty>No session is live right now.</Empty>
      ) : (
        <ul aria-label="Live sessions" className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {cards.map((c) => (
            <Card key={c.id} c={c} />
          ))}
        </ul>
      )}
      <SessionSheet c={open} />
    </div>
  );
}

/** A worker's ticket belongs to a map: the sidebar's pick narrows to it. */
function scopeHas(scope: { project: string; map: string }, c: SessionCard): boolean {
  if (scope.project === "" && scope.map === "") return true;
  const map = (c.ticketKey ?? "").replace(/#\d+$/, "");
  if (scope.map !== "") return map === scope.map;
  return map.startsWith(`${scope.project}/`) || c.project === scope.project;
}

const EMPTY: Trail = { agent: "", ctx: null, ended: null, actions: [] };

function Map_({ trail, className }: { trail: Trail | null | undefined; className?: string }): React.JSX.Element {
  const { state } = useBoard();
  const dark = useDark();
  return <div role="img" aria-label="What the session is doing, as a map" className={cn("w-full [&>svg]:h-auto [&>svg]:w-full", className)} dangerouslySetInnerHTML={{ __html: mapSvg(trail ?? EMPTY, state.now, dark) }} />;
}

function Dots({ c, bad }: { c: SessionCard; bad: boolean }): React.JSX.Element {
  return (
    <>
      {bad && <span role="img" aria-label="a failure in the last 5 minutes" title="a failure in the last 5 minutes" className="size-2.5 shrink-0 rounded-full bg-destructive" />}
      {c.silent && <span className="text-xs text-warn">{`silent ${dur(c.quiet)}`}</span>}
    </>
  );
}

function Card({ c }: { c: SessionCard }): React.JSX.Element {
  const { state } = useBoard();
  const trail = useTrail(c.id).data;
  const bad = failedLately(trail, state.now);
  const href = c.links?.ticket ?? null;
  return (
    <li
      aria-label={c.title}
      className={cn("group relative flex flex-col gap-2 rounded-xl border bg-card p-3 hover:bg-accent/30", c.silent && "ring-2 ring-warn", c.idle && "opacity-60 grayscale")}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {href === null ? (
              <button
                type="button"
                onClick={() => {
                  setLink({ sess: c.id });
                }}
                className="line-clamp-2 min-w-0 text-left text-sm font-medium after:absolute after:inset-0 after:content-[''] focus-visible:underline focus-visible:outline-none"
              >
                {c.title}
              </button>
            ) : (
              <a href={href} title="Open the ticket in Obsidian" className="relative z-10 line-clamp-2 min-w-0 text-sm font-medium hover:underline">
                {c.title}
              </a>
            )}
            <Dots c={c} bad={bad} />
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {c.project}
            {c.account !== "" && ` · ${c.account}`}
            {` · ${ago(state.now, c.agent.at)}`}
          </p>
        </div>
        <Badge className="shrink-0">
          {c.kind === "worker" ? <IconRobot aria-hidden /> : <IconUser aria-hidden />}
          {c.kind === "worker" ? "worker" : "chat"}
        </Badge>
      </div>
      <button
        type="button"
        title="Open the big map"
        onClick={() => {
          setLink({ sess: c.id });
        }}
        className="relative z-10 rounded-lg focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <Map_ trail={trail} />
      </button>
      {c.now !== "" && (
        <p className="truncate text-xs text-muted-foreground" title={c.now}>
          {c.now}
        </p>
      )}
    </li>
  );
}

function SessionSheet({ c }: { c: SessionCard | null }): React.JSX.Element {
  return (
    <Sheet
      open={c !== null}
      onOpenChange={(o) => {
        if (!o) setLink({ sess: "" });
      }}
    >
      <SheetContent aria-describedby={undefined} className="overflow-y-auto sm:max-w-xl">
        {c !== null && <SessionPanel key={c.id} c={c} />}
      </SheetContent>
    </Sheet>
  );
}

function SessionPanel({ c }: { c: SessionCard }): React.JSX.Element {
  const { state, openMessage, down, ix } = useBoard();
  const trail = useTrail(c.id).data;
  const bad = failedLately(trail, state.now);
  const rows = (trail?.actions ?? []).slice(-FEED_ROWS).reverse();
  const item = state.queue.items.find((i) => i.key === c.id);
  const ticket = c.links?.ticket ?? null;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">
          {c.title}
          <Dots c={c} bad={bad} />
        </SheetTitle>
        <SheetDescription>
          {c.kind === "worker" ? "worker" : "chat session"} · {c.project}
          {c.account !== "" && ` · ${c.account}`}
          {trail?.ctx != null && ` · context ${String(Math.round(trail.ctx))}%`}
        </SheetDescription>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button
            size="xs"
            variant="outline"
            disabled={down}
            onClick={() => {
              openMessage(c.id);
            }}
          >
            <IconMail aria-hidden />
            Message
          </Button>
          {ticket !== null && (
            <Button asChild size="xs" variant="outline">
              <a href={ticket}>
                <IconNotebook aria-hidden />
                Ticket
              </a>
            </Button>
          )}
          {c.ticketKey !== null && ix.byKey.has(c.ticketKey) && (
            <Button
              size="xs"
              variant="outline"
              onClick={() => {
                setLink({ sess: "", t: c.ticketKey ?? "" });
              }}
            >
              Details and Stop
            </Button>
          )}
        </div>
      </SheetHeader>
      <div className="flex flex-col gap-5 px-6 py-4">
        <Map_ trail={trail} />
        {item?.checks !== undefined && <Checks checks={item.checks} />}
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-medium text-muted-foreground">{`Last ${String(FEED_ROWS)} actions`}</h3>
          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing yet.</p>
          ) : (
            <ol aria-label="Last actions" className="flex flex-col divide-y rounded-lg border text-sm">
              {rows.map((a, n) => {
                const e = entryOf(a, n);
                return (
                  <li key={`${String(a.start)}-${String(n)}`} className="flex items-center gap-2 px-3 py-1.5">
                    <span
                      role="img"
                      aria-label={e.status === "err" ? "failed" : e.status === "run" ? "running" : "done"}
                      className={cn("size-2 shrink-0 rounded-full", e.status === "err" ? "bg-destructive" : e.status === "run" ? "bg-brand motion-safe:animate-pulse" : "bg-muted-foreground/40")}
                    />
                    <span className="w-16 shrink-0 text-xs text-muted-foreground">{NAMES[e.station]}</span>
                    <span className="min-w-0 flex-1 truncate" title={`${a.tool}: ${a.label}`}>
                      {a.tool !== "" && <span className="text-muted-foreground">{a.tool} </span>}
                      {a.label}
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{ago(state.now, a.start)}</span>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      </div>
    </>
  );
}
