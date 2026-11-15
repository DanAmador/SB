/**
 * A map's head, above its graph and table: the title, the first sentence of its plain words, one line of counts, the
 * checks (folded, or one warning when there are none) and the button that queues the whole map.
 */
import { IconAlertTriangle, IconChevronRight, IconExternalLink, IconListNumbers, IconPencil, IconTerminal2 } from "@tabler/icons-react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type * as React from "react";
import type { MapRoute } from "@sb-hub/contract";
import { plural } from "@/lib/board.ts";
import { say } from "@/lib/notice.ts";
import { countsLine, queueable, ranToday, type MapState } from "@/lib/map.ts";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { useBoard } from "./context.tsx";

const obsidian = (u: string | null | undefined): string | null => (u?.startsWith("obsidian://") === true ? u : null);

function ChecksEditor({ map, route, onDone }: { map: string; route: MapRoute; onDone: () => void }): React.JSX.Element {
  const { writes, down } = useBoard();
  const qc = useQueryClient();
  const [text, setText] = useState(route.checks.join("; "));
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // the hub keeps the checks on the map: any open ticket of it carries the action
  const carrier = route.tickets.find((t) => t.status === "open") ?? route.tickets[0];
  const save = async (): Promise<void> => {
    if (carrier === undefined) return;
    if (!text.trim()) {
      setErr("Type the checks first, separated by ;");
      return;
    }
    setWorking(true);
    const out = await writes.ticket("checks", { key: `${map}#${String(carrier.num)}`, text: text.trim() }, "Done: set the map's checks.");
    setWorking(false);
    say(out);
    if (!out.ok) {
      setErr(out.words);
      return;
    }
    await qc.invalidateQueries({ queryKey: ["map", map] });
    onDone();
  };
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(ev) => {
        ev.preventDefault();
        void save();
      }}
    >
      <Label>
        Checks of this map, separated by ;
        <Input value={text} maxLength={2000} placeholder="e.g. pnpm typecheck; pnpm test" onChange={(ev) => { setText(ev.currentTarget.value); setErr(null); }} />
      </Label>
      {err !== null && <p role="alert" className="text-sm text-destructive">{err}</p>}
      <div className="flex gap-2">
        <Button type="submit" size="xs" disabled={working || down}>{working ? "Working…" : "Save checks"}</Button>
        <Button type="button" size="xs" variant="ghost" disabled={working} onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

export function MapHead({ map, route, counts }: { map: string; route: MapRoute; counts: Readonly<Record<MapState, number>> }): React.JSX.Element {
  const { state, queueWrite, down, busy } = useBoard();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const noChecks = route.checks.length === 0;
  const can = queueable(counts);
  const today = ranToday(route.tickets, state.now);
  const board = obsidian(route.tickets.find((t) => obsidian(t.links.board) !== null)?.links.board);
  const mapUri = obsidian(route.uri);
  const queueThis = (): void => {
    const before = new Set(state.queue.items.filter((i) => i.state === "queued").map((i) => i.key));
    void queueWrite("POST /api/queue/map", { map, version: state.queue.version }, (a) => {
      const added = a.queue.items.filter((i) => i.state === "queued" && i.key.startsWith(`${map}#`) && !before.has(i.key)).length;
      const reasons = [...new Set(a.left_out.map((x) => x.reason))];
      const words = `Queued ${plural(added, "ticket")}${a.left_out.length > 0 ? `; left ${plural(a.left_out.length, "ticket")}: ${reasons.join("; ")}` : ""}.`;
      setResult(words);
      void qc.invalidateQueries({ queryKey: ["map", map] });
      return words;
    });
  };
  return (
    <header aria-label={`Head of ${route.title}`} data-testid="map-head" className="flex flex-col gap-2 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <h2 className="min-w-0 flex-[1_1_14rem] text-base font-semibold break-words">{route.title}</h2>
        <nav aria-label="Map links" className="flex flex-wrap items-center gap-3 text-xs">
          {mapUri !== null && (
            <a href={mapUri} className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              <IconExternalLink className="size-3.5" aria-hidden />
              The map in Obsidian
            </a>
          )}
          {board !== null && (
            <a href={board} className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              <IconExternalLink className="size-3.5" aria-hidden />
              Tonight's run board
            </a>
          )}
        </nav>
      </div>
      {route.words !== "" && <p className="text-sm text-muted-foreground break-words">{route.words}</p>}
      <p data-testid="map-counts" className="text-sm font-medium tabular-nums">{countsLine(counts)}</p>
      {today !== null && (
        <p data-testid="map-today" className="text-xs text-muted-foreground">
          {`Ran today: ${String(today.done)} ended done${today.short > 0 ? `, ${String(today.short)} fell short` : ""}.`}
        </p>
      )}
      {noChecks && !editing ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md bg-warn-soft p-2.5 text-sm">
          <IconAlertTriangle className="size-4 shrink-0 text-warn" aria-hidden />
          <span className="min-w-0 flex-1">No checks: nothing here can be queued</span>
          <Button size="xs" variant="outline" disabled={down} onClick={() => { setEditing(true); }}>Set them</Button>
        </div>
      ) : editing ? (
        <ChecksEditor map={map} route={route} onDone={() => { setEditing(false); }} />
      ) : (
        <details className="group text-sm">
          <summary className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
            <IconChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden />
            <IconTerminal2 className="size-3.5" aria-hidden />
            {`Checks (${String(route.checks.length)})`}
          </summary>
          <ul className="mt-1.5 flex flex-col gap-1">
            {route.checks.map((c) => (
              <li key={c} className="rounded bg-muted px-2 py-1 font-mono text-xs break-all">{c}</li>
            ))}
          </ul>
          <Button size="xs" variant="outline" className="mt-2" disabled={down} onClick={() => { setEditing(true); }}>
            <IconPencil aria-hidden />
            Edit
          </Button>
        </details>
      )}
      {!noChecks && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={down || busy || can === 0} onClick={queueThis}>
            <IconListNumbers aria-hidden />
            Queue this map
          </Button>
          {can === 0 && <span className="text-xs text-muted-foreground">Nothing is left to queue.</span>}
        </div>
      )}
      {result !== null && <p role="status" data-testid="map-queued" className="text-xs text-muted-foreground">{result}</p>}
    </header>
  );
}
