/**
 * A map's landing: its tickets as a graph, one box each, an arrow for every "after", the colour for the state. Below
 * 768 px the same tickets show as a plain list. A box opens the ticket panel; a blocker in another map opens that map.
 */
import { IconCircleCheck, IconClock, IconListNumbers, IconLock, IconMessageQuestion, IconPlayerPlay, IconPlayerSkipForward, IconSquareCheck, IconTicket, IconAlertTriangle, IconBan } from "@tabler/icons-react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useSyncExternalStore } from "react";
import type * as React from "react";
import type { MapTicket } from "@sb-hub/contract";
import { Skeleton } from "@/components/ui/skeleton";
import { useMapRoute } from "@/lib/hub.ts";
import { setLink } from "@/lib/link.ts";
import { layoutMap, MAP_STATES, MAP_STATE_WORDS, type MapNode, type MapState } from "@/lib/map.ts";
import { cn } from "@/lib/utils";

const WIDE = "(min-width: 768px)";
const subscribe = (fn: () => void): (() => void) => {
  const m = matchMedia(WIDE);
  m.addEventListener("change", fn);
  return () => {
    m.removeEventListener("change", fn);
  };
};
const useWide = (): boolean => useSyncExternalStore(subscribe, () => matchMedia(WIDE).matches, () => true);

const TONE: Readonly<Record<MapState, string>> = {
  done: "border-ok/70 bg-ok/10",
  running: "border-brand bg-brand-soft",
  queued: "border-brand/60 bg-card",
  "can run": "border-foreground/60 bg-card",
  stuck: "border-border bg-muted text-muted-foreground",
  decision: "border-warn bg-warn-soft",
  "no checks": "border-destructive/60 bg-destructive-soft",
  "out of scope": "border-dashed border-border bg-background text-muted-foreground",
};
const STATE_ICON: Readonly<Record<MapState, typeof IconTicket>> = {
  done: IconCircleCheck,
  running: IconPlayerPlay,
  queued: IconListNumbers,
  "can run": IconSquareCheck,
  stuck: IconLock,
  decision: IconMessageQuestion,
  "no checks": IconAlertTriangle,
  "out of scope": IconBan,
};
const TYPE_ICON: Readonly<Record<string, typeof IconTicket>> = { grilling: IconMessageQuestion, task: IconSquareCheck, other: IconPlayerSkipForward };

const keyOf = (map: string, t: { num: number }): string => `${map}#${String(t.num)}`;
const stateLine = (n: MapNode): string => {
  const place = n.state === "queued" && n.ticket?.place != null ? ` ${String(n.ticket.place)}` : "";
  return n.ticket === null ? n.other : `${MAP_STATE_WORDS[n.state]}${place}`;
};
/** The box's second line. The box has no aria-label: its name is its visible words. */
const footOf = (n: MapNode): string => (n.ticket === null ? n.other : `${String(n.ticket.num)} · ${stateLine(n)}`);

function TypeGlyph({ type }: { type: string | null }): React.JSX.Element {
  const Glyph = TYPE_ICON[type ?? "other"] ?? IconTicket;
  return <Glyph className="mt-0.5 size-3.5 shrink-0" aria-hidden />;
}

function StateGlyph({ s }: { s: MapState }): React.JSX.Element {
  const Glyph = STATE_ICON[s];
  return <Glyph className="size-3 shrink-0" aria-hidden />;
}

interface Data extends Record<string, unknown> {
  n: MapNode;
  map: string;
}

function Box({ data }: NodeProps<Node<Data>>): React.JSX.Element {
  const { n, map } = data;
  const t = n.ticket;
  const open = (): void => {
    if (t !== null) setLink({ t: keyOf(map, t) });
    else setLink({ project: n.other.split("/")[0] ?? "", map: n.other });
  };
  return (
    <>
      <Handle type="target" position={Position.Top} isConnectable={false} className="!pointer-events-none !opacity-0" />
      <button
        type="button"
        onClick={open}
        className={cn(
          "flex size-full flex-col justify-between rounded-lg border-2 px-2.5 py-1.5 text-left text-xs shadow-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
          t === null ? "border-dashed border-border bg-background text-muted-foreground" : TONE[n.state],
          n.state === "running" && "motion-safe:animate-pulse",
        )}
      >
        <span className="flex items-start gap-1.5">
          <TypeGlyph type={t?.type ?? null} />
          <span className="line-clamp-2 leading-snug font-medium">{n.title}</span>
        </span>
        <span className="flex items-center gap-1 text-[10px] leading-none">
          {t !== null && <StateGlyph s={n.state} />}
          <span className="truncate">{footOf(n)}</span>
        </span>
      </button>
      <Handle type="source" position={Position.Bottom} isConnectable={false} className="!pointer-events-none !opacity-0" />
    </>
  );
}
const nodeTypes = { box: Box };

function Legend(): React.JSX.Element {
  return (
    <ul aria-label="Legend" className="flex flex-wrap gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
      {MAP_STATES.map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <span className={cn("size-3 rounded border-2", TONE[s].split(" ").filter((c) => c.startsWith("border") || c.startsWith("bg")).join(" "))} aria-hidden />
          {MAP_STATE_WORDS[s]}
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span className="size-3 rounded border-2 border-dashed border-border" aria-hidden />
        After a ticket in another map
      </li>
    </ul>
  );
}

function List({ map, tickets, states }: { map: string; tickets: readonly MapTicket[]; states: ReadonlyMap<number, MapNode> }): React.JSX.Element {
  return (
    <ol aria-label="Tickets of the map" className="flex flex-col gap-1.5">
      {tickets.map((t) => {
        const n = states.get(t.num);
        if (!n) return null;
        return (
          <li key={t.num}>
            <button
              type="button"
              onClick={() => { setLink({ t: keyOf(map, t) }); }}
              className={cn("flex w-full flex-col gap-0.5 rounded-lg border-2 px-3 py-2 text-left text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", TONE[n.state])}
            >
              <span className="font-medium">{t.num} {t.title}</span>
              <span className="flex items-center gap-1 text-xs">
                <StateGlyph s={n.state} />
                {stateLine(n)}
                {t.blocked_by.length > 0 && <span> · after {t.blocked_by.map((b) => (b.num === null ? b.title : b.map === map ? String(b.num) : `${b.map}#${String(b.num)}`)).join(", ")}</span>}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function MapView({ map }: { map: string }): React.JSX.Element {
  const q = useMapRoute(map);
  const wide = useWide();
  const route = q.data;
  if (route === undefined) {
    return q.isError ? (
      <p role="alert" className="text-sm text-muted-foreground">The map could not be read: {q.error.message}</p>
    ) : (
      <Skeleton className="h-64 w-full" aria-label="Loading the map" />
    );
  }
  const layout = layoutMap(route);
  const own = new Map(layout.nodes.filter((n) => n.ticket !== null).map((n) => [n.ticket?.num ?? 0, n]));
  const nodes: Node<Data>[] = layout.nodes.map((n) => ({
    id: n.id, type: "box", position: { x: n.x, y: n.y }, width: n.w, height: n.h, data: { n, map }, draggable: false, connectable: false, focusable: false, style: { pointerEvents: "all" },
  }));
  const edges: Edge[] = layout.edges.map((e) => ({
    id: e.id, source: e.from, target: e.to, focusable: false, markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    style: { stroke: "var(--muted-foreground)", strokeWidth: 1.5 }, ...(layout.nodes.find((n) => n.id === e.from)?.ticket === null ? { style: { stroke: "var(--muted-foreground)", strokeWidth: 1.5, strokeDasharray: "5 4" } } : {}),
  }));
  return (
    <section aria-label={`Route of ${route.title}`} className="flex flex-col gap-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <IconClock className="size-4 text-muted-foreground" aria-hidden />
        Route of {route.title}
      </h2>
      {wide ? (
        <div data-testid="map-graph" className="h-[min(70dvh,720px)] min-h-80 w-full rounded-lg border bg-card">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.1 }}
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
        <List map={map} tickets={route.tickets} states={own} />
      )}
      <Legend />
    </section>
  );
}
