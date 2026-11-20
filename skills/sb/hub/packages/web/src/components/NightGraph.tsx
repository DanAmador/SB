/**
 * The run's graph, what Everything (or a project) shows where a map's own graph would: 15-minute columns running left
 * to right, a band per project, a bar per ticket as wide as the columns it takes, arrows from a bar's right end to the
 * next one's left end, the now line upright, and one Done box. The clocks along the top stay while you scroll down and
 * the project names stay while you scroll across; the view opens with the now line a third from the left. Map chips
 * above it show or hide each map. Below 768 px it is a list grouped by map. It reads the queue the page already polls,
 * so a bar changes in place when its ticket does. The layout math is nightGraph.ts's chunkGraph.
 */
import { IconArrowUpRight, IconFlag, IconFocus2, IconNotebook, IconTopologyStar3 } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import type * as React from "react";
import type { Night, QueueItem } from "@sb-hub/contract";
import { useMapRoutes } from "@/lib/hub.ts";
import { setLink } from "@/lib/link.ts";
import { liveItems } from "@/lib/night.ts";
import { NODE_H, NODE_W } from "@/lib/map.ts";
import { atOnceOf, BAR_GAP, BAR_H, chunkGraph, CLOCK_H, DONE_ID, frozenInfo, infoOf, LEFT, pathsOf, type ChunkBar, type ChunkGraph, type ChunkMemo, type NightFrame } from "@/lib/nightGraph.ts";
import { cn } from "@/lib/utils";
import { itemProject } from "@/lib/board.ts";
import { ProjectChips, ScrollRow, tally } from "./bits.tsx";
import { StateGlyph, TONE, useWide } from "./MapView.tsx";
import { useNow } from "./QuestionCard.tsx";
import { useBoard } from "./context.tsx";

/** One chip per map (spans, not list rows, so j and k skip them): pressed shows it, unpressed hides it with its arrows; the arrow opens the map's own graph. */
function Chips({ frames, hide, fit }: { frames: readonly NightFrame[]; hide: (map: string) => void; fit?: (project: string) => void }): React.JSX.Element {
  // grouped by project, each group led by the project's name
  const projectOf = (f: NightFrame): string => (f.map === "" ? "" : (f.map.split("/")[0] ?? ""));
  const order = [...new Set(frames.map(projectOf))];
  const sorted = order.flatMap((p) => frames.filter((f) => projectOf(f) === p));
  return (
    <ScrollRow label="Maps" className="text-xs">
      {sorted.map((f, n) => (
        <span key={f.id} className="inline-flex shrink-0 items-center gap-1.5">
          {projectOf(f) !== "" && (n === 0 || projectOf(sorted[n - 1] ?? f) !== projectOf(f)) && (
            <span className={cn("inline-flex shrink-0 items-center", n > 0 && "ml-2 border-l pl-2")}>
              {fit === undefined ? (
                <span className="px-1 font-semibold text-muted-foreground">{projectOf(f)}</span>
              ) : (
                <button
                  type="button"
                  title={`Fit ${projectOf(f)} in view`}
                  onClick={() => { fit(projectOf(f)); }}
                  className="inline-flex h-7 items-center gap-1 rounded-md px-1 font-semibold text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <IconFocus2 className="size-3.5" aria-hidden />
                  {projectOf(f)}
                </button>
              )}
            </span>
          )}
        <span className="inline-flex shrink-0 items-center rounded-full border bg-card">
          <button
            type="button"
            aria-pressed={!f.hidden}
            title={`${f.title}: ${f.line}. ${f.hidden ? "Show" : "Hide"} this map`}
            onClick={() => { hide(f.map); }}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-full pr-1.5 pl-2.5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              f.hidden ? "text-muted-foreground line-through" : "text-foreground",
            )}
          >
            <span className={cn("size-2.5 rounded-full", f.hidden && "opacity-40")} style={{ backgroundColor: f.hue }} aria-hidden />
            <span className="max-w-56 truncate">{f.title}</span>
            <span className="text-muted-foreground tabular-nums">{f.boxes.length}</span>
          </button>
          {f.map !== "" && (
            <button
              type="button"
              aria-label={`Open the map ${f.title}`}
              title="Show this map's own graph"
              onClick={() => { setLink({ project: f.map.split("/")[0] ?? "", map: f.map }); }}
              className="inline-flex size-7 items-center justify-center rounded-full text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <IconArrowUpRight className="size-3.5" aria-hidden />
            </button>
          )}
        </span>
        </span>
      ))}
    </ScrollRow>
  );
}

function List({ frames }: { frames: readonly NightFrame[] }): React.JSX.Element {
  return (
    <div data-testid="night-list" className="flex flex-col gap-4">
      {frames.filter((f) => !f.hidden).map((f) => (
        <section key={f.id} aria-label={f.title} className="flex flex-col gap-1.5">
          <h3 className="flex flex-wrap items-baseline gap-x-2 text-sm font-semibold">
            {f.map === "" ? (
              f.title
            ) : (
              <button type="button" className="text-left hover:underline" onClick={() => { setLink({ project: f.map.split("/")[0] ?? "", map: f.map }); }}>
                {f.title}
              </button>
            )}
            <span className="text-xs font-normal text-muted-foreground">{f.line}</span>
          </h3>
          <ol className="flex flex-col gap-1.5">
            {f.boxes.map((b) => (
              <li key={b.id} className="relative">
                <button
                  type="button"
                  onClick={() => { setLink({ t: b.id }); }}
                  className={cn("flex w-full flex-col gap-0.5 rounded-lg border-2 px-3 py-2 text-left text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", TONE[b.state])}
                >
                  <span className="font-medium">{b.title}</span>
                  <span className="flex items-center gap-1 text-xs">
                    <StateGlyph s={b.state} />
                    {b.foot}
                  </span>
                </button>
                {b.report !== null && (
                  <a href={b.report} className="absolute right-3 bottom-2 text-xs text-brand underline-offset-2 hover:underline">
                    Report
                  </a>
                )}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

/** The narrowest a running bar is drawn, when it began in the column the now line is in. */
const MIN_RUNNING_W = 40;
/** A bar as drawn: a running one ends at the now line, whatever its column's end. */
interface Drawn { x: number; w: number }
const drawnOf = (b: ChunkBar, nowX: number | null): Drawn => ({ x: b.x, w: b.item.state === "running" && nowX !== null ? Math.max(MIN_RUNNING_W, nowX - b.x) : b.w });

function Bar({ b, d, flash }: { b: ChunkBar; d: Drawn; flash: boolean }): React.JSX.Element {
  return (
    <div data-testid="night-bar" data-key={b.id} title={b.title} className="absolute" style={{ left: d.x, top: b.y, width: d.w, height: BAR_H }}>
      <button
        type="button"
        onClick={() => { setLink({ t: b.id }); }}
        className={cn(
          "flex size-full flex-col justify-between overflow-hidden rounded-lg border-2 px-2 py-1 text-left text-xs shadow-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
          TONE[b.state],
          b.item.state === "running" && "motion-safe:animate-pulse",
          flash && "motion-safe:animate-[flash_1.2s_ease-out_1]",
          b.phase === "next" && "border-dashed",
        )}
        style={{ borderLeftColor: b.hue, borderLeftWidth: 6, borderLeftStyle: "solid" }}
      >
        <span className="block w-full truncate leading-snug font-medium">{b.title}</span>
        <span className="flex w-full items-center gap-1 text-[10px] leading-none">
          <StateGlyph s={b.state} />
          <span className={cn("truncate", b.item.state === "running" && "font-semibold")}>{b.foot}</span>
        </span>
      </button>
      {b.report !== null && (
        <a href={b.report} aria-label="Report" title="Open the report in Obsidian" className="absolute right-1.5 bottom-1 inline-flex items-center gap-0.5 rounded bg-card/80 px-1 text-[10px] text-brand underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
          <IconNotebook className="size-3" aria-hidden />
          {d.w > 150 && "Report"}
        </a>
      )}
    </div>
  );
}

/** An arrow leaves a bar's right end and enters the next one's left end; it only ever points right. */
function Arrows({ g, drawn }: { g: ChunkGraph; drawn: ReadonlyMap<string, Drawn> }): React.JSX.Element {
  const bars = new Map(g.bars.map((b) => [b.id, b]));
  return (
    <svg className="pointer-events-none absolute top-0 left-0" width={g.right + 16} height={g.bottom + 16} aria-hidden>
      <defs>
        <marker id="night-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
        </marker>
      </defs>
      {g.edges.map((e) => {
        const from = bars.get(e.from);
        const df = drawn.get(e.from);
        const to = e.to === DONE_ID ? g.done : bars.get(e.to);
        if (from === undefined || df === undefined || to === null || to === undefined) return null;
        const sx = df.x + df.w;
        const sy = from.y + BAR_H / 2;
        const tx = to.x;
        const ty = e.to === DONE_ID ? to.y + NODE_H / 2 : to.y + BAR_H / 2;
        const k = Math.max(0, Math.min(40, (tx - sx) / 2));
        return (
          <path
            key={e.id}
            data-testid="night-arrow"
            data-from={e.from}
            data-to={e.to}
            d={`M${String(sx)} ${String(sy)} C${String(sx + k)} ${String(sy)} ${String(tx - k)} ${String(ty)} ${String(tx)} ${String(ty)}`}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeDasharray={e.across ? "5 4" : undefined}
            markerEnd="url(#night-arrow)"
            className={e.to === DONE_ID ? "text-border" : "text-muted-foreground"}
          />
        );
      })}
    </svg>
  );
}

/** The graph itself: one scrolling frame, clocks sticky on top, project names sticky at the left. */
function Chunks({ g, changed }: { g: ChunkGraph; changed: ReadonlySet<string> }): React.JSX.Element {
  const drawn = new Map(g.bars.map((b) => [b.id, drawnOf(b, g.nowX)] as const));
  const [opened] = useState(() => new WeakSet<HTMLElement>());
  // opens with the now line a third from the left
  const open = (el: HTMLDivElement | null): void => {
    if (el === null || opened.has(el)) return;
    opened.add(el);
    el.scrollLeft = g.nowX === null ? 0 : Math.max(0, g.nowX - el.clientWidth / 3);
  };
  return (
    <div ref={open} data-testid="night-graph" className="h-[calc(100dvh-17rem)] min-h-96 w-full overflow-auto rounded-lg border bg-card">
      <div className="relative" style={{ width: g.right + 16, height: g.bottom + 16 }}>
        <div className="sticky top-0 z-20 border-b bg-card" style={{ height: CLOCK_H, width: g.right + 16 }}>
          {g.columns.map((c) => (
            <span
              key={c.chunk}
              data-testid="night-clock"
              data-at={c.at}
              className={cn("absolute top-0 flex h-full items-center border-l pl-1.5 text-xs whitespace-nowrap tabular-nums", c.phase === "now" ? "font-semibold text-brand" : "text-muted-foreground")}
              style={{ left: c.x }}
            >
              {c.clock}
            </span>
          ))}
        </div>
        {g.columns.map((c) => (
          <div key={c.chunk} className="pointer-events-none absolute border-l border-dashed border-border/60" style={{ left: c.x, top: CLOCK_H, height: g.bottom - CLOCK_H }} aria-hidden />
        ))}
        {g.bands.map((b) => (
          <div key={b.project} data-testid="night-band" className="absolute left-0 rounded-xl border border-dashed border-muted-foreground/30 bg-muted/25" style={{ top: b.y, height: b.h, width: g.right + 8 }}>
            <div className="sticky left-0 z-10 flex w-fit items-center gap-2 rounded-xl bg-card/90 px-3 py-1 text-sm backdrop-blur" style={{ maxWidth: LEFT - 8 }}>
              <span className="truncate font-semibold">{b.project}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{g.bars.filter((x) => x.project === b.project).length}</span>
            </div>
          </div>
        ))}
        <Arrows g={g} drawn={drawn} />
        {g.bars.map((b) => <Bar key={b.id} b={b} d={drawn.get(b.id) ?? { x: b.x, w: b.w }} flash={changed.has(b.id)} />)}
        {g.notes.map((n) => (
          <span key={`${n.project}:${String(n.chunk)}`} data-testid="night-note" title={n.text} className="absolute truncate text-[10px] leading-3 text-warn" style={{ left: n.x + 4, top: n.y, width: 120 - BAR_GAP }}>
            {n.text}
          </span>
        ))}
        {g.nowX !== null && <div data-testid="night-now" className="pointer-events-none absolute z-10 w-0 border-l-2 border-brand" style={{ left: g.nowX, top: CLOCK_H, height: g.bottom - CLOCK_H }} aria-hidden />}
        {g.done !== null && (
          <div data-testid="night-done" className="absolute flex flex-col justify-center gap-0.5 rounded-lg border-2 border-foreground bg-card px-3 text-sm" style={{ left: g.done.x, top: g.done.y, width: NODE_W, height: NODE_H }}>
            <span className="flex items-center gap-1.5 font-semibold">
              <IconFlag className="size-4" aria-hidden />
              Done
            </span>
            <span className="text-xs text-muted-foreground tabular-nums">{g.done.line}</span>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * The live run's graph, or the graph of the run it is given (History's). An ended run is `frozen`: it draws from what
 * it kept (its maps' order, its repos' limits, its end time and each ticket's arrows), never from today's queue.
 * Either narrows to the sidebar's pick.
 */
export function NightGraph({ items: given, title, frozen }: { items?: readonly QueueItem[]; title?: string; frozen?: Pick<Night, "maps" | "repos" | "ended"> }): React.JSX.Element | null {
  const { state, tickets, scope, ix } = useBoard();
  const wide = useWide();
  const live = liveItems(state.queue, state);
  const items = given ?? live;
  const order = frozen === undefined ? state.queue.maps : frozen.maps;
  const maps = useMemo(() => [...new Set([...(order ?? []), ...items.filter((i) => i.kind === "ticket").map((i) => i.key.replace(/#\d+$/, ""))])], [order, items]);
  // a frozen run reads today's map routes only for the tickets that kept nothing (runs from before ticket 169)
  const needRoutes = frozen === undefined || items.some((i) => i.kind === "ticket" && i.after === undefined);
  const routes = useMapRoutes(needRoutes ? maps : []);
  const data = routes.map((r) => r.data);
  const info = useMemo(() => (frozen === undefined ? infoOf(data, tickets ?? []) : frozenInfo(items, infoOf(data, tickets ?? []))), [frozen, items, data, tickets]);
  const repos = frozen === undefined ? state.queue.repos : frozen.repos;
  const atOnce = useMemo(() => atOnceOf(repos), [repos]);
  const paths = useMemo(() => pathsOf(tickets ?? []), [tickets]);
  // the clock of the columns to come moves once a minute; an ended run's stands at its end
  const ticking = Math.floor(useNow() / 60) * 60;
  const minute = frozen?.ended ?? ticking;
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const hide = (map: string): void => {
    setHidden((h) => {
      const n = new Set(h);
      if (!n.delete(map)) n.add(map);
      return n;
    });
  };
  // the bands keep their order, so an update moves nothing that stays
  const [memo] = useState(() => new Map<"v", ChunkMemo>());
  const g = useMemo(() => chunkGraph({ items, maps: order ?? [], info, scope, hidden, atOnce, paths, now: minute, prev: memo.get("v") }), [items, order, info, scope, hidden, atOnce, paths, minute, memo]);
  useEffect(() => {
    memo.set("v", g.memo);
  }, [g, memo]);
  // a bar flashes when its state changes after the graph has shown
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => { setSettled(true); }, 600);
    return () => { clearTimeout(t); };
  }, []);
  const [last] = useState(() => new Map<string, string>());
  const changed = new Set<string>();
  if (settled) for (const b of g.bars) if (last.has(b.id) && last.get(b.id) !== b.item.state) changed.add(b.id);
  useEffect(() => {
    for (const b of g.bars) last.set(b.id, b.item.state);
  }, [g, last]);

  // every project of the run, whatever the page is narrowed to, so another one is a click away
  const projects = tally(items.map((i) => itemProject(i, ix.byKey.get(i.key))));
  const chips = <ProjectChips counts={projects} label="Projects in the run" />;
  if (g.frames.length === 0) return scope.project !== "" && projects.length > 0 ? chips : null;
  // a project's name scrolls the graph to that project's band
  const fit = (project: string): void => {
    const band = g.bands.find((b) => b.project === project);
    const frame = document.querySelector<HTMLElement>("[data-testid='night-graph']");
    if (band !== undefined && frame !== null) frame.scrollTo({ top: Math.max(0, band.y - CLOCK_H), behavior: "smooth" });
  };
  return (
    <section aria-label="The run" className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <IconTopologyStar3 className="size-4 text-muted-foreground" aria-hidden />
        {title ?? "The run"}
        <span className="text-xs font-normal text-muted-foreground" data-testid="run-counts">{g.line}</span>
      </h2>
      {chips}
      <Chips frames={g.frames} hide={hide} {...(wide && { fit })} />
      {wide ? <Chunks g={g} changed={changed} /> : <List frames={g.frames} />}
    </section>
  );
}
