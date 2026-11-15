/**
 * The run's graph, what Everything (or a project) shows where a map's own graph would: a frame per map with its
 * counts, the same boxes as the map graph, an arrow for each "after". Below 768 px it is a list grouped by map.
 * It reads the queue the page already polls, so a box changes in place when its ticket does.
 */
import { IconTopologyStar3 } from "@tabler/icons-react";
import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node, type NodeProps, type ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useState } from "react";
import type * as React from "react";
import type { MapTicket } from "@sb-hub/contract";
import { useMapRoutes } from "@/lib/hub.ts";
import { setLink } from "@/lib/link.ts";
import { NODE_H, NODE_W, type MapNode } from "@/lib/map.ts";
import { focusOf, infoOf, nightGraph, type NightBox, type NightFrame, type Slot } from "@/lib/nightGraph.ts";
import { cn } from "@/lib/utils";
import { Box, StateGlyph, TONE, useWide, type Data } from "./MapView.tsx";
import { useBoard } from "./context.tsx";

/** The queue item as the map graph's node: the same box, drawn by the same code. */
function nodeOf(b: NightBox, map: string): MapNode {
  const item = b.item;
  const num = Number(/#(\d+)$/.exec(b.id)?.[1] ?? 0);
  const ticket: MapTicket = {
    num, title: b.title, type: item.kind === "job" ? "other" : "task", status: "open", state: "ready", why: "", priority: null, tier: "", place: b.place,
    last_run: null, blocked_by: [], file: "", links: item.links,
  };
  return { id: b.id, ticket, title: b.title, state: b.state, other: map, x: 0, y: 0, w: NODE_W, h: NODE_H };
}

interface FrameData extends Record<string, unknown> {
  f: NightFrame;
}
function Frame({ data }: NodeProps<Node<FrameData>>): React.JSX.Element {
  const { f } = data;
  const title = (
    <span className="truncate text-sm font-semibold">{f.title}</span>
  );
  return (
    <div className="size-full rounded-xl border bg-muted/30">
      <div className="flex flex-col gap-0.5 px-4 pt-2.5">
        {f.map === "" ? (
          title
        ) : (
          <button
            type="button"
            title="Show this map's own graph"
            onClick={() => { setLink({ project: f.map.split("/")[0] ?? "", map: f.map }); }}
            className="pointer-events-auto w-fit max-w-full rounded text-left hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {title}
          </button>
        )}
        <span className="truncate text-xs text-muted-foreground">{f.line}</span>
      </div>
    </div>
  );
}
const nodeTypes = { box: Box, frame: Frame };

function List({ frames }: { frames: readonly NightFrame[] }): React.JSX.Element {
  return (
    <div data-testid="night-list" className="flex flex-col gap-4">
      {frames.map((f) => (
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

export function NightGraph(): React.JSX.Element | null {
  const { state, tickets, scope } = useBoard();
  const wide = useWide();
  const items = state.queue.items;
  const maps = useMemo(() => [...new Set([...(state.queue.maps ?? []), ...items.filter((i) => i.kind === "ticket").map((i) => i.key.replace(/#\d+$/, ""))])], [state.queue.maps, items]);
  const routes = useMapRoutes(maps);
  const data = routes.map((r) => r.data);
  const info = useMemo(() => infoOf(data, tickets ?? []), [data, tickets]);
  // each box keeps the place it first got, so an update moves nothing that stays
  const [slots] = useState(() => new Map<string, Slot>());
  const g = useMemo(() => nightGraph({ items, maps: state.queue.maps ?? [], info, scope, prev: slots }), [items, state.queue.maps, info, scope, slots]);
  useEffect(() => {
    for (const [k, v] of g.slots) slots.set(k, v);
  }, [g, slots]);
  // a box flashes when its state changes after the graph has shown
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => { setSettled(true); }, 600);
    return () => { clearTimeout(t); };
  }, []);
  const [last] = useState(() => new Map<string, string>());
  const changed = new Set<string>();
  if (settled) for (const f of g.frames) for (const b of f.boxes) if (last.has(b.id) && last.get(b.id) !== b.item.state) changed.add(b.id);
  useEffect(() => {
    for (const f of g.frames) for (const b of f.boxes) last.set(b.id, b.item.state);
  }, [g, last]);

  if (g.frames.length === 0) return null;
  const nodes: Node[] = g.frames.flatMap((f) => [
    { id: f.id, type: "frame", position: { x: f.x, y: f.y }, width: f.w, height: f.h, data: { f }, draggable: false, connectable: false, selectable: false, focusable: false, zIndex: -1, style: { pointerEvents: "none" } },
    ...f.boxes.map((b): Node<Data> => ({
      id: b.id, type: "box", parentId: f.id, position: { x: b.x, y: b.y }, width: NODE_W, height: NODE_H, draggable: false, connectable: false, focusable: false, style: { pointerEvents: "all" },
      data: { n: nodeOf(b, f.map), map: f.map, ...(b.place === null && { foot: b.foot }), key: b.id, report: b.report, flash: changed.has(b.id) },
    })),
  ]);
  const edges: Edge[] = g.edges.map((e) => ({
    id: e.id, source: e.from, target: e.to, focusable: false, markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    style: { stroke: "var(--muted-foreground)", strokeWidth: 1.5, ...(e.across ? { strokeDasharray: "5 4" } : {}) },
  }));
  const centre = (rf: ReactFlowInstance): void => {
    const at = focusOf(g);
    if (at === null) { void rf.fitView({ padding: 0.1 }); return; }
    void rf.setCenter(at.x, at.y, { zoom: 0.85 });
  };
  return (
    <section aria-label="The run" className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <IconTopologyStar3 className="size-4 text-muted-foreground" aria-hidden />
        The run
        <span className="text-xs font-normal text-muted-foreground" data-testid="run-counts">{g.line}</span>
      </h2>
      {wide ? (
        <div data-testid="night-graph" className="h-[min(70dvh,720px)] min-h-80 w-full rounded-lg border bg-card">
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
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      ) : (
        <List frames={g.frames} />
      )}
    </section>
  );
}
