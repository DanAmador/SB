/**
 * The run's graph, what Everything (or a project) shows where a map's own graph would: a timeline, a column per
 * project and a row per step, oldest at the top; the now line; the rows still to come drawn dashed; one Done box.
 * Map chips above it show or hide each map. Below 768 px it is a list grouped by map. It reads the queue the page
 * already polls, so a box changes in place when its ticket does.
 */
import { IconArrowUpRight, IconFlag, IconFocus2, IconTopologyStar3 } from "@tabler/icons-react";
import { Background, Controls, Handle, MarkerType, MiniMap, Panel, Position, ReactFlow, useReactFlow, type Edge, type Node, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState } from "react";
import type * as React from "react";
import type { MapTicket, QueueItem } from "@sb-hub/contract";
import { useMapRoutes } from "@/lib/hub.ts";
import { setLink } from "@/lib/link.ts";
import { liveItems } from "@/lib/night.ts";
import { NODE_H, NODE_W, type MapNode } from "@/lib/map.ts";
import { atOnceOf, CLOCK_W, DONE_ID, focusOf, HEAD, infoOf, nightGraph, type NightBox, type NightDone, type NightFrame, type NightMemo } from "@/lib/nightGraph.ts";
import { cn } from "@/lib/utils";
import { itemProject } from "@/lib/board.ts";
import { ProjectChips, ScrollRow, tally } from "./bits.tsx";
import { Box, StateGlyph, TONE, useWide, type Data } from "./MapView.tsx";
import { useNow } from "./QuestionCard.tsx";
import { useBoard } from "./context.tsx";

/** The queue item as the map graph's node: the same box, drawn by the same code. */
function nodeOf(b: NightBox): MapNode {
  const item = b.item;
  const num = Number(/#(\d+)$/.exec(b.id)?.[1] ?? 0);
  const ticket: MapTicket = {
    num, title: b.title, type: item.kind === "job" ? "other" : "task", status: "open", state: "ready", why: "", priority: null, tier: "", place: b.place,
    last_run: null, blocked_by: [], file: "", links: item.links,
  };
  return { id: b.id, ticket, title: b.title, state: b.state, other: b.map, x: 0, y: 0, w: NODE_W, h: NODE_H };
}

interface TextData extends Record<string, unknown> {
  text: string;
  now?: boolean;
}
/** A row's clock time, at its left. */
function Clock({ data }: NodeProps<Node<TextData>>): React.JSX.Element {
  return (
    <div className={cn("flex size-full items-center text-xs tabular-nums", data.now === true ? "font-semibold text-brand" : "text-muted-foreground")}>{data.text}</div>
  );
}
interface FrameData extends Record<string, unknown> {
  text: string;
  ids: string[];
}
/**
 * A project's column as one framed group behind its boxes: its name and box count on top, and a button that fits the
 * view to just that column. The frame lets clicks through to the boxes; only its label takes them.
 */
function Head({ data }: NodeProps<Node<FrameData>>): React.JSX.Element {
  const rf = useReactFlow();
  return (
    <div className="size-full rounded-xl border border-dashed border-muted-foreground/30 bg-muted/25">
      <div className="pointer-events-auto flex h-9 items-center gap-2 px-3 text-sm">
        <span className="truncate font-semibold">{data.text}</span>
        <span className="text-xs text-muted-foreground tabular-nums">{data.ids.length}</span>
        <button
          type="button"
          aria-label={`Fit ${data.text} in view`}
          title="Fit this project in view"
          onClick={() => { void rf.fitView({ nodes: data.ids.map((id) => ({ id })), padding: 0.15, duration: 300 }); }}
          className="ml-auto inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <IconFocus2 className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}
/** The now line, across every column. */
function Now(): React.JSX.Element {
  return (
    <div className="relative size-full" aria-hidden>
      <div className="absolute inset-x-0 top-1/2 border-t-2 border-brand" />
    </div>
  );
}
interface DoneData extends Record<string, unknown> {
  d: NightDone;
}
/** Where every project's last ticket points: finished out of the night's total. */
function Done({ data }: NodeProps<Node<DoneData>>): React.JSX.Element {
  return (
    <>
      <Handle type="target" position={Position.Top} isConnectable={false} className="!pointer-events-none !opacity-0" />
      <div data-testid="night-done" className="flex size-full flex-col justify-center gap-0.5 rounded-lg border-2 border-foreground bg-card px-3 text-sm">
        <span className="flex items-center gap-1.5 font-semibold">
          <IconFlag className="size-4" aria-hidden />
          Done
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">{data.d.line}</span>
      </div>
    </>
  );
}
const nodeTypes = { box: Box, clock: Clock, head: Head, now: Now, done: Done };

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

/** The map chips inside the graph: a project's name fits the view to that project's boxes. */
function FlowChips({ frames, hide, boxes }: { frames: readonly NightFrame[]; hide: (map: string) => void; boxes: readonly NightBox[] }): React.JSX.Element {
  const rf = useReactFlow();
  const fit = (project: string): void => {
    const ids = boxes.filter((b) => b.map.split("/")[0] === project).map((b) => ({ id: b.id }));
    if (ids.length > 0) void rf.fitView({ nodes: ids, padding: 0.15, maxZoom: 1, duration: 300 });
  };
  return <Chips frames={frames} hide={hide} fit={fit} />;
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

const ARROW = { type: MarkerType.ArrowClosed, width: 16, height: 16 } as const;
/** The room a project's frame leaves around its boxes. */
const FRAME_PAD = 12;

/** The live run's graph, or the graph of the run it is given (History's). Either narrows to the sidebar's pick. */
export function NightGraph({ items: given, title }: { items?: readonly QueueItem[]; title?: string }): React.JSX.Element | null {
  const { state, tickets, scope, ix } = useBoard();
  const wide = useWide();
  const live = liveItems(state.queue, state);
  const items = given ?? live;
  const maps = useMemo(() => [...new Set([...(state.queue.maps ?? []), ...items.filter((i) => i.kind === "ticket").map((i) => i.key.replace(/#\d+$/, ""))])], [state.queue.maps, items]);
  const routes = useMapRoutes(maps);
  const data = routes.map((r) => r.data);
  const info = useMemo(() => infoOf(data, tickets ?? []), [data, tickets]);
  const atOnce = useMemo(() => atOnceOf(state.queue.repos), [state.queue.repos]);
  // the clock of the rows to come moves once a minute
  const minute = Math.floor(useNow() / 60) * 60;
  const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set());
  const hide = (map: string): void => {
    setHidden((h) => {
      const n = new Set(h);
      if (!n.delete(map)) n.add(map);
      return n;
    });
  };
  // the columns keep their order and width, so an update moves nothing that stays
  const [memo] = useState(() => new Map<"v", NightMemo>());
  const g = useMemo(
    () => nightGraph({ items, maps: state.queue.maps ?? [], info, scope, hidden, atOnce, now: minute, prev: memo.get("v") }),
    [items, state.queue.maps, info, scope, hidden, atOnce, minute, memo],
  );
  useEffect(() => {
    memo.set("v", g.memo);
  }, [g, memo]);
  // a box flashes when its state changes after the graph has shown
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => { setSettled(true); }, 600);
    return () => { clearTimeout(t); };
  }, []);
  const [last] = useState(() => new Map<string, string>());
  const changed = new Set<string>();
  if (settled) for (const b of g.boxes) if (last.has(b.id) && last.get(b.id) !== b.item.state) changed.add(b.id);
  useEffect(() => {
    for (const b of g.boxes) last.set(b.id, b.item.state);
  }, [g, last]);

  // every project of the run, whatever the page is narrowed to, so another one is a click away
  const projects = tally(items.map((i) => itemProject(i, ix.byKey.get(i.key))));
  const chips = <ProjectChips counts={projects} label="Projects in the run" />;
  if (g.frames.length === 0) return scope.project !== "" && projects.length > 0 ? chips : null;
  const right = Math.max(CLOCK_W + NODE_W, ...g.columns.map((c) => c.x + c.w));
  const fixed = { draggable: false, connectable: false, selectable: false, focusable: false } as const;
  const nodes: Node[] = [
    ...g.columns.map((c): Node => {
      const its = g.boxes.filter((b) => b.project === c.project);
      const bottom = Math.max(HEAD, ...its.map((b) => b.y + b.h)) + FRAME_PAD;
      return {
        id: `head:${c.project}`, type: "head", position: { x: c.x - FRAME_PAD, y: 0 }, width: c.w + 2 * FRAME_PAD, height: bottom,
        data: { text: c.project, ids: its.map((b) => b.id) }, zIndex: -1, style: { pointerEvents: "none" }, ...fixed,
      };
    }),
    ...g.rows.map((r): Node => ({ id: `clock:${String(r.row)}`, type: "clock", position: { x: 0, y: r.y }, width: CLOCK_W - 12, height: NODE_H, data: { text: r.clock, now: r.phase === "now" }, ...fixed })),
    ...(g.nowY !== null ? [{ id: "now", type: "now", position: { x: 0, y: g.nowY - 6 }, width: right, height: 12, data: {}, zIndex: -1, ...fixed } satisfies Node] : []),
    ...g.boxes.map((b): Node<Data> => ({
      id: b.id, type: "box", position: { x: b.x, y: b.y }, width: NODE_W, height: b.h, draggable: false, connectable: false, focusable: false, style: { pointerEvents: "all" },
      data: { n: nodeOf(b), map: b.map, ...(b.place === null && { foot: b.foot }), key: b.id, report: b.report, flash: changed.has(b.id), hue: b.hue, dashed: b.phase === "next" },
    })),
    ...(g.done !== null ? [{ id: DONE_ID, type: "done", position: { x: g.done.x, y: g.done.y }, width: NODE_W, height: NODE_H, data: { d: g.done }, ...fixed } satisfies Node] : []),
  ];
  const edges: Edge[] = g.edges.map((e) => ({
    id: e.id, source: e.from, target: e.to, focusable: false, markerEnd: ARROW,
    style: e.to === DONE_ID
      ? { stroke: "var(--border)", strokeWidth: 1.5 }
      : { stroke: "var(--muted-foreground)", strokeWidth: 1.5, ...(e.across ? { strokeDasharray: "5 4" } : {}) },
  }));
  const centre = (rf: ReactFlowInstance): void => {
    const at = focusOf(g);
    if (at === null) {
      void rf.fitView();
      return;
    }
    void rf.setCenter(at.x, at.y, { zoom: 0.85 });
  };
  return (
    <section aria-label="The run" className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <IconTopologyStar3 className="size-4 text-muted-foreground" aria-hidden />
        {title ?? "The run"}
        <span className="text-xs font-normal text-muted-foreground" data-testid="run-counts">{g.line}</span>
      </h2>
      {wide ? (
        <div data-testid="night-graph" className="flex h-[calc(100dvh-17rem)] min-h-96 w-full flex-col overflow-hidden rounded-lg border bg-card">
          <div className="min-h-0 flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onInit={centre}
            minZoom={0.1}
            maxZoom={1.5}
            nodesDraggable={false}
            nodesConnectable={false}
            nodesFocusable={false}
            edgesFocusable={false}
            elementsSelectable={false}
            colorMode={document.documentElement.classList.contains("dark") ? "dark" : "light"}
          >
            <Background gap={24} />
            <Panel position="top-left" className="!m-2 flex max-w-[calc(100%-1rem)] flex-col gap-1.5 rounded-lg border bg-card/90 p-1.5 shadow-sm backdrop-blur">
              {chips}
              <FlowChips frames={g.frames} hide={hide} boxes={g.boxes} />
            </Panel>
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              ariaLabel="Overview of the run"
              className="!bg-card"
              maskColor="color-mix(in oklab, var(--background) 70%, transparent)"
              nodeColor={(n) => (n.type === "box" ? ((n.data as { hue?: string }).hue ?? "var(--muted-foreground)") : n.type === "head" ? "var(--muted)" : "transparent")}
              nodeStrokeWidth={0}
            />
          </ReactFlow>
          </div>
        </div>
      ) : (
        <>
          {chips}
          <Chips frames={g.frames} hide={hide} />
          <List frames={g.frames} />
        </>
      )}
    </section>
  );
}
