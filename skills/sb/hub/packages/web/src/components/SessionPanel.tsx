/**
 * The panel a session or a worker opens from the Run tab: the big map and the last 16 actions. Red dot: a failure in
 * the last five minutes; "silent": no report for five minutes or more. The drawing is lot-map's (src/vendor/lot-map, MIT).
 */
import { IconMail, IconNotebook } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import type * as React from "react";
import type { Trail } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ago, dur, SILENT } from "@/lib/board.ts";
import { useTrail } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { entryOf, FEED_ROWS, helperCards, mapSvg, sessionCards, type SessionCard } from "@/lib/sessions.ts";
import { cn } from "@/lib/utils";
import { STATIONS } from "@/vendor/lot-map/setup.ts";
import { Checks } from "./bits.tsx";
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

const EMPTY: Trail = { agent: "", ctx: null, ended: null, actions: [] };

function Map_({ trail, className }: { trail: Trail | null | undefined; className?: string }): React.JSX.Element {
  const { state } = useBoard();
  const dark = useDark();
  return <div role="img" aria-label="What the session is doing, as a map" className={cn("w-full [&>svg]:h-auto [&>svg]:w-full", className)} dangerouslySetInnerHTML={{ __html: mapSvg(trail ?? EMPTY, state.now, dark) }} />;
}

export function Dots({ c, bad }: { c: SessionCard; bad: boolean }): React.JSX.Element {
  return (
    <>
      {bad && <span role="img" aria-label="a failure in the last 5 minutes" title="a failure in the last 5 minutes" className="size-2.5 shrink-0 rounded-full bg-destructive" />}
      {c.silentSince !== null ? (
        <span className="text-xs text-muted-foreground">{`silent since ${c.silentSince}`}</span>
      ) : (
        c.silent && <span className="text-xs text-warn">{`silent ${dur(c.quiet)}`}</span>
      )}
    </>
  );
}

/** The panel of the session `?sess=` names, over whichever view is on screen. */
export function SessionSheet(): React.JSX.Element {
  const { state, ix, agents } = useBoard();
  const link = useLink();
  const c = [...sessionCards(state, ix, agents), ...[...helperCards(state, ix, agents).values()].flat()].find((x) => x.id === link.sess) ?? null;
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
