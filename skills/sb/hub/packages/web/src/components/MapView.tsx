/**
 * A map's landing: its tickets as a graph, one box each, an arrow for every "after", the colour for the state. Below
 * 768 px the same tickets show as a plain list. A box opens the ticket panel; a blocker in another map opens that map.
 */
import { IconFocusCentered, IconCircleCheck, IconLayoutList, IconTopologyStar3, IconClock, IconListNumbers, IconLock, IconMessageQuestion, IconPlayerPlay, IconPlayerSkipForward, IconSquareCheck, IconTicket, IconAlertTriangle, IconBan, IconCheck } from "@tabler/icons-react";
import { Background, Controls, Handle, MarkerType, Panel, Position, ReactFlow, SelectionMode, useReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type * as React from "react";
import type { MapTicket } from "@sb-hub/contract";
import { Skeleton } from "@/components/ui/skeleton";
import { useMapRoute } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { dimmed, layoutMap, reachKeys, MAP_STATES, MAP_STATE_WORDS, minutesOf, pickedState, stateCounts, type MapNode, type MapState } from "@/lib/map.ts";
import { cn } from "@/lib/utils";
import { useBoard } from "./context.tsx";
import { clearSelection, selected, tick, useSelection } from "@/lib/select.ts";
import { MapHead } from "./MapHead.tsx";
import { TicketTable } from "./TicketTable.tsx";

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
  done: "border-ok/40 bg-ok/5 text-muted-foreground",
  running: "border-brand bg-brand text-background ring-4 ring-brand/30",
  queued: "border-brand bg-card",
  "can run": "border-dashed border-muted-foreground/70 bg-card",
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
/** The state in words: a running ticket with its minutes so far. A queued one's place is its own badge. */
const stateLine = (n: MapNode, mins: number | null): string => {
  if (n.ticket === null) return n.other;
  return n.state === "running" && mins !== null ? `${MAP_STATE_WORDS[n.state]} · ${String(mins)} min` : MAP_STATE_WORDS[n.state];
};
/** The box's second line. The box has no aria-label: its name is its visible words. */
const footOf = (n: MapNode, mins: number | null): string => (n.ticket === null ? n.other : `${String(n.ticket.num)} · ${stateLine(n, mins)}`);

/** A queued ticket's place in the whole line. */
function Place({ n }: { n: MapNode }): React.JSX.Element | null {
  if (n.state !== "queued" || n.ticket?.place == null) return null;
  return <span className="ml-auto shrink-0 rounded-full bg-brand px-1.5 py-0.5 text-[10px] leading-none font-semibold text-background">next {n.ticket.place}</span>;
}

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
  /** Minutes its run has taken so far; null when it is not running. */
  mins: number | null;
  /** Another state is picked: the box steps back. */
  dim: boolean;
  /** Ticked: the same tick the table's row has. */
  ticked: boolean;
}

function Box({ data }: NodeProps<Node<Data>>): React.JSX.Element {
  const { n, map, mins, dim, ticked } = data;
  const t = n.ticket;
  const open = (ev: React.MouseEvent): void => {
    // Shift-click ticks; a plain click opens the panel
    if (ev.shiftKey) {
      if (t !== null) tick([keyOf(map, t)], !ticked);
      return;
    }
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
          "relative flex size-full flex-col justify-between rounded-lg border-2 px-2.5 py-1.5 text-left text-xs shadow-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
          t === null ? "border-dashed border-border bg-background text-muted-foreground" : TONE[n.state],
          n.state === "running" && "motion-safe:animate-pulse",
          ticked && "ring-4 ring-foreground/40",
          dim && "opacity-25",
        )}
      >
        <span className="flex items-start gap-1.5">
          <TypeGlyph type={t?.type ?? null} />
          <span className="line-clamp-2 leading-snug font-medium">{n.title}</span>
        </span>
        <span className="flex items-center gap-1 text-[10px] leading-none">
          {t !== null && <StateGlyph s={n.state} />}
          <span className={cn("truncate", n.state === "running" && "font-semibold")}>{footOf(n, mins)}</span>
          <Place n={n} />
        </span>
        {ticked && (
          <span className="absolute -top-2 -right-2 flex size-5 items-center justify-center rounded-full bg-foreground text-background">
            <IconCheck className="size-3.5" aria-hidden />
            <span className="sr-only">Ticked</span>
          </span>
        )}
      </button>
      <Handle type="source" position={Position.Bottom} isConnectable={false} className="!pointer-events-none !opacity-0" />
    </>
  );
}
const nodeTypes = { box: Box };

/** The legend is the filter: one chip per state with its count; a pressed chip dims every other box. */
function Legend({ counts, pick }: { counts: Readonly<Record<MapState, number>>; pick: MapState | null }): React.JSX.Element {
  return (
    <ul aria-label="Legend" className="flex flex-wrap items-center gap-1.5 text-xs">
      {MAP_STATES.map((s) => (
        <li key={s}>
          <button
            type="button"
            aria-pressed={pick === s}
            disabled={counts[s] === 0}
            onClick={() => { setLink({ ms: pick === s ? "" : s }); }}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-40",
              pick === s ? "border-foreground bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <span className={cn("size-3 rounded border-2", TONE[s].split(" ").filter((c) => c.startsWith("border") || c.startsWith("bg")).join(" "))} aria-hidden />
            {MAP_STATE_WORDS[s]}
            <span className="tabular-nums font-semibold">{counts[s]}</span>
          </button>
        </li>
      ))}
      <li className="flex items-center gap-1.5 px-1 text-muted-foreground">
        <span className="size-3 rounded border-2 border-dashed border-border" aria-hidden />
        After a ticket in another map
      </li>
    </ul>
  );
}

function List({ map, tickets, states, pick, minsOf }: { map: string; tickets: readonly MapTicket[]; states: ReadonlyMap<number, MapNode>; pick: MapState | null; minsOf: (n: MapNode) => number | null }): React.JSX.Element {
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
              className={cn("flex w-full flex-col gap-0.5 rounded-lg border-2 px-3 py-2 text-left text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", TONE[n.state], dimmed(n, pick) && "opacity-25")}
            >
              <span className="font-medium">{t.num} {t.title}</span>
              <span className="flex items-center gap-1 text-xs">
                <StateGlyph s={n.state} />
                <span className={cn(n.state === "running" && "font-semibold")}>{stateLine(n, minsOf(n))}</span>
                {t.blocked_by.length > 0 && <span> · after {t.blocked_by.map((b) => (b.num === null ? b.title : b.map === map ? String(b.num) : `${b.map}#${String(b.num)}`)).join(", ")}</span>}
                <Place n={n} />
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** A button inside the graph that brings the running boxes into view; nothing when none runs. */
function ShowRunning({ ids }: { ids: readonly string[] }): React.JSX.Element | null {
  const flow = useReactFlow();
  if (ids.length === 0) return null;
  return (
    <Panel position="top-right">
      <button
        type="button"
        onClick={() => { void flow.fitView({ nodes: ids.map((id) => ({ id })), padding: 0.4, maxZoom: 1, duration: 300 }); }}
        className="inline-flex h-7 items-center gap-1.5 rounded-full border bg-card px-3 text-xs text-muted-foreground shadow-sm hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <IconFocusCentered className="size-3.5" aria-hidden />
        Show running
      </button>
    </Panel>
  );
}

/** Graph | Table: which the map shows, kept in the page link. */
function Switch({ table }: { table: boolean }): React.JSX.Element {
  const one = (on: boolean, words: string, Glyph: typeof IconTicket, mv: string): React.JSX.Element => (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      onClick={() => { setLink({ mv }); }}
      className={cn("inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", on ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground")}
    >
      <Glyph className="size-3.5" aria-hidden />
      {words}
    </button>
  );
  return (
    <div role="radiogroup" aria-label="Show the map as" className="ml-auto inline-flex rounded-full border p-0.5">
      {one(!table, "Graph", IconTopologyStar3, "")}
      {one(table, "Table", IconLayoutList, "table")}
    </div>
  );
}

export function MapView({ map }: { map: string }): React.JSX.Element {
  const q = useMapRoute(map);
  const link = useLink();
  const table = link.mv === "table";
  const pick = pickedState(link.ms);
  const wide = useWide();
  const { state } = useBoard();
  const keys = useSelection();
  const boxing = useRef(false);
  const box = useRef<HTMLDivElement>(null);
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  // Escape closes the node menu first, then clears the ticks; a dialog that is open keeps its own Escape
  useEffect(() => {
    const onKey = (ev: KeyboardEvent): void => {
      if (ev.key !== "Escape" || document.querySelector('[role="dialog"]') !== null) return;
      if (menu !== null) setMenu(null);
      else if (selected().size > 0) clearSelection();
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); };
  }, [menu]);
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
  const counts = stateCounts(layout.nodes);
  const minsOf = (n: MapNode): number | null => {
    if (n.state !== "running" || n.ticket === null) return null;
    const key = keyOf(map, n.ticket);
    return minutesOf(state.queue.items.find((i) => i.key === key && i.state === "running")?.started, state.now);
  };
  const running = new Set(layout.nodes.filter((n) => n.state === "running" && n.ticket !== null).map((n) => n.id));
  const nodes: Node<Data>[] = layout.nodes.map((n) => ({
    id: n.id, type: "box", position: { x: n.x, y: n.y }, width: n.w, height: n.h, data: { n, map, mins: minsOf(n), dim: dimmed(n, pick), ticked: keys.has(keyOf(map, n.ticket ?? { num: -1 })) }, selected: n.ticket !== null && keys.has(keyOf(map, n.ticket)), draggable: false, connectable: false, focusable: false, style: { pointerEvents: "all" },
  }));
  // an arrow into or out of a running box takes the accent, so the eye follows what the run feeds
  const edges: Edge[] = layout.edges.map((e) => {
    const hot = running.has(e.from) || running.has(e.to);
    const stroke = hot ? "var(--brand)" : "var(--muted-foreground)";
    const dashed = layout.nodes.find((n) => n.id === e.from)?.ticket === null;
    return {
      id: e.id, source: e.from, target: e.to, focusable: false, markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, ...(hot ? { color: "var(--brand)" } : {}) },
      style: { stroke, strokeWidth: hot ? 2.5 : 1.5, ...(dashed ? { strokeDasharray: "5 4" } : {}), ...(pick !== null && !hot ? { opacity: 0.3 } : {}) },
    };
  });
  return (
    <section aria-label={`Route of ${route.title}`} className="flex flex-col gap-2">
      <MapHead map={map} route={route} counts={counts} />
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <IconClock className="size-4 text-muted-foreground" aria-hidden />
        Route of {route.title}
        <Switch table={table} />
      </h2>
      {!table && <Legend counts={counts} pick={pick} />}
      {table ? (
        <TicketTable />
      ) : wide ? (
        <div ref={box} data-testid="map-graph" className="relative h-[min(70dvh,720px)] min-h-80 w-full rounded-lg border bg-card [&_.react-flow__nodesselection]:hidden">
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
            elementsSelectable
            selectionOnDrag
            selectionMode={SelectionMode.Partial}
            panOnDrag={[1, 2]}
            multiSelectionKeyCode="Shift"
            onSelectionStart={() => { boxing.current = true; }}
            onSelectionEnd={() => { boxing.current = false; }}
            onNodesChange={(changes) => {
              // only a box drawn over the graph ticks; a plain click opens the panel and a Shift-click is the box's own
              if (!boxing.current) return;
              for (const c of changes) if (c.type === "select" && !c.id.startsWith("x:")) tick([keyOf(map, { num: Number(c.id) })], c.selected);
            }}
            onNodeContextMenu={(ev, node) => {
              ev.preventDefault();
              const at = box.current?.getBoundingClientRect();
              setMenu({ id: node.id, x: ev.clientX - (at?.left ?? 0), y: ev.clientY - (at?.top ?? 0) });
            }}
            onPaneClick={() => { setMenu(null); }}
            onMoveStart={() => { setMenu(null); }}
            colorMode={document.documentElement.classList.contains("dark") ? "dark" : "light"}
          >
            <Background gap={24} />
            <Controls showInteractive={false} />
            <ShowRunning ids={[...running]} />
          </ReactFlow>
          {menu !== null && !menu.id.startsWith("x:") && (
            <div role="menu" aria-label="Tick along the arrows" style={{ left: menu.x, top: menu.y }} className="absolute z-10 flex w-72 flex-col rounded-lg border bg-popover p-1 text-xs text-popover-foreground shadow-md">
              {([["before", "Tick everything this comes after"], ["after", "Tick everything that comes after this"]] as const).map(([way, words], i) => (
                <button
                  key={way}
                  type="button"
                  role="menuitem"
                  autoFocus={i === 0}
                  onClick={() => {
                    tick(reachKeys(layout, map, menu.id, way), true);
                    setMenu(null);
                  }}
                  className="flex h-8 items-center gap-2 rounded-md px-2 text-left hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <IconCheck className="size-3.5 shrink-0" aria-hidden />
                  {words}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <List map={map} tickets={route.tickets} states={own} pick={pick} minsOf={minsOf} />
      )}
    </section>
  );
}
