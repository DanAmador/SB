/**
 * A table of tickets: every ticket of the picked map (finished ones too), or of the project or Everything. Filter by
 * state, type and priority with chips that carry counts, search, sort by a column, tick rows (Space, Shift-click, the
 * header box) and act on the ticked with the bar. More than 200 rows are paged.
 */
import { IconArrowDown, IconArrowUp, IconSearch } from "@tabler/icons-react";
import type * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { chipCounts, filterRows, liveOf, nextSort, NO_PRIORITY, pageOf, parseSort, plural, rowOfMapTicket, rowOfTicket, ROW_STATES, SORTS, sortRows, ticketInScope, type Facet, type RowState, type Sort, type TableFilter, type TableRow } from "@/lib/board.ts";
import { useMapRoute } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { clickRow, tick, useSelection } from "@/lib/select.ts";
import { cn } from "@/lib/utils";
import { Empty, MapName, TicketTitle } from "./bits.tsx";
import { useBoard } from "./context.tsx";
import { SelectionBar } from "./SelectionBar.tsx";

/** Dragging a row to Up next: the Queue passes it in. */
export interface RowDrag {
  readonly key: string | undefined;
  readonly start: (key: string) => void;
  readonly end: () => void;
}
export const DRAG_TYPE = "application/x-sb-ticket";

/** The dot before a state word; the word itself stays in the text colour, which reads on every background. */
const DOT: Readonly<Record<RowState, string>> = {
  "can run now": "bg-ok",
  "can run after another": "bg-muted-foreground",
  queued: "bg-brand",
  running: "bg-brand",
  "needs a decision": "bg-warn",
  "no checks": "bg-destructive",
  claimed: "bg-brand",
  "stuck behind another": "bg-muted-foreground",
  done: "bg-ok",
  "out of scope": "bg-muted-foreground",
};
const COLUMNS: readonly [Sort, string][] = [["title", "Title"], ["map", "Map"], ["type", "Type"], ["state", "State"], ["priority", "Priority"], ["tier", "Tier"]];
const stateWords = (r: Pick<TableRow, "state" | "place">): string => (r.state === "queued" && r.place !== null ? `queued, number ${String(r.place)}` : r.state);

/** The rows this page is about: the picked map's route (the open tickets of the map if it cannot be read), else the open tickets of the project or of everything. */
/** The bar for what is ticked, on its own: the map graph's box-select ticks rows while the table sits in another tab. */
export function TickedBar(): React.JSX.Element | null {
  const all = useRows();
  return all === null ? null : <SelectionBar rows={all} />;
}

function useRows(): TableRow[] | null {
  const { tickets, ix, state, scope } = useBoard();
  const q = useMapRoute(scope.map);
  const live = liveOf(state);
  if (scope.map !== "" && !(q.isError && q.data?.map !== scope.map)) {
    const route = q.data;
    if (route?.map !== scope.map) return null;
    return route.tickets.map((t) => rowOfMapTicket(route.map, route.title, route.checks.length > 0, t, ix, live));
  }
  if (tickets === null) return null;
  return tickets.filter((t) => ticketInScope(scope, t)).map((t) => rowOfTicket(t, ix, live));
}

function StateBadge({ r }: { r: TableRow }): React.JSX.Element {
  return (
    <Badge className="text-foreground">
      <span className={cn("size-1.5 rounded-full", DOT[r.state])} aria-hidden />
      {stateWords(r)}
    </Badge>
  );
}

function Chips({ facet, label, values, counts, now }: { facet: Facet; label: string; values: readonly string[]; counts: ReadonlyMap<string, number>; now: string }): React.JSX.Element | null {
  const shown = values.filter((v) => (counts.get(v) ?? 0) > 0 || v === now);
  if (shown.length === 0) return null;
  const key = facet === "state" ? "ts" : facet === "type" ? "tt" : "tp";
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      {shown.map((v) => {
        const on = now === v;
        return (
          <button
            key={v}
            type="button"
            aria-pressed={on}
            onClick={() => {
              setLink({ [key]: on ? "" : v, page: "" });
            }}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
              on ? "border-foreground bg-foreground text-background" : "text-muted-foreground hover:border-foreground/40 hover:text-foreground",
            )}
          >
            {v}
            <span className="tabular-nums">{counts.get(v) ?? 0}</span>
          </button>
        );
      })}
    </div>
  );
}

export function TicketTable({ drag }: { drag?: RowDrag }): React.JSX.Element {
  const link = useLink();
  const { scope, down, busy } = useBoard();
  const all = useRows();
  const keys = useSelection();
  if (all === null) return <Skeleton className="h-64 w-full" aria-label="Loading the tickets" />;

  const f: TableFilter = { q: link.q, state: link.ts, type: link.tt, priority: link.tp };
  const counts = chipCounts(all, f);
  const sorted = sortRows(filterRows(all, f), link.sort);
  const page = pageOf(sorted, Number(link.page) || 1);
  const order = page.rows.map((r) => r.key);
  const ticked = page.rows.filter((r) => keys.has(r.key)).length;
  const sort = parseSort(link.sort);
  const showMap = scope.map === "";
  const types = [...new Set(all.map((r) => r.type))].sort();
  const priorities = [...new Set(all.map((r) => r.priority ?? NO_PRIORITY))].sort();
  const filtered = f.q !== "" || f.state !== "" || f.type !== "" || f.priority !== "";

  return (
    <section aria-label="Tickets" className="flex min-w-0 flex-col gap-3">
      <div className="relative min-w-0">
        <IconSearch className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          type="search"
          data-find
          className="h-9 w-full pl-9"
          placeholder="Search by title, map or number"
          aria-label="Search the tickets"
          maxLength={200}
          defaultValue={link.q}
          onChange={(ev) => {
            setLink({ q: ev.currentTarget.value.trim(), page: "" });
          }}
        />
      </div>
      <Chips facet="state" label="State" values={ROW_STATES} counts={counts.state} now={link.ts} />
      <Chips facet="type" label="Type" values={types} counts={counts.type} now={link.tt} />
      <Chips facet="priority" label="Priority" values={priorities} counts={counts.priority} now={link.tp} />
      <label className="flex items-center gap-2 text-xs text-muted-foreground sm:hidden">
        Sort by
        <select
          aria-label="Sort by"
          value={link.sort}
          onChange={(e) => {
            setLink({ sort: e.currentTarget.value, page: "" });
          }}
          className="h-8 rounded-md border bg-background px-2 text-sm text-foreground"
        >
          <option value="">Map order</option>
          {SORTS.flatMap((s) => [<option key={s} value={s}>{s}</option>, <option key={`-${s}`} value={`-${s}`}>{`${s}, descending`}</option>])}
        </select>
      </label>
      {sorted.length === 0 ? (
        <Empty>{filtered ? "No ticket here matches." : "No tickets here."}</Empty>
      ) : (
        <table data-testid="ticket-table" aria-label="Tickets" className="block w-full min-w-0 rounded-xl border bg-card text-sm sm:table sm:border-separate sm:border-spacing-0">
          <thead className="block sm:table-header-group">
            <tr className="flex items-center gap-2 border-b px-3 py-2 sm:table-row">
              <th scope="col" className="w-8 text-left font-normal sm:px-3 sm:py-2">
                <input
                  type="checkbox"
                  aria-label="Tick every ticket shown"
                  className="size-4 accent-[var(--brand)]"
                  checked={ticked > 0 && ticked === page.rows.length}
                  ref={(el) => {
                    if (el) el.indeterminate = ticked > 0 && ticked < page.rows.length;
                  }}
                  onChange={(e) => {
                    tick(order, e.currentTarget.checked);
                  }}
                />
              </th>
              {COLUMNS.map(([by, words]) => {
                if (by === "map" && !showMap) return null;
                const on = sort?.by === by;
                return (
                  <th key={by} scope="col" aria-sort={on ? (sort.desc ? "descending" : "ascending") : "none"} className={cn("px-3 py-2 text-left text-xs font-medium text-muted-foreground", by === "title" ? "flex-1" : "hidden sm:table-cell")}>
                    <button
                      type="button"
                      onClick={() => {
                        setLink({ sort: nextSort(link.sort, by), page: "" });
                      }}
                      className="inline-flex items-center gap-1 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      {words}
                      {on && (sort.desc ? <IconArrowDown className="size-3" aria-hidden /> : <IconArrowUp className="size-3" aria-hidden />)}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="block sm:table-row-group" data-testid="ticket-rows">
            {page.rows.map((r, n) => {
              const on = keys.has(r.key);
              const draggable = drag !== undefined && (r.state === "can run now" || r.state === "can run after another") && !down && !busy;
              return (
                <tr
                  key={r.key}
                  data-key={r.key}
                  tabIndex={n === 0 ? 0 : -1}
                  aria-selected={on}
                  draggable={draggable}
                  onDragStart={(ev) => {
                    ev.dataTransfer.setData(DRAG_TYPE, r.key);
                    ev.dataTransfer.setData("text/plain", r.key);
                    ev.dataTransfer.effectAllowed = "move";
                    drag?.start(r.key);
                  }}
                  onDragEnd={() => {
                    drag?.end();
                  }}
                  onKeyDown={(ev) => {
                    if (ev.target !== ev.currentTarget) return;
                    if (ev.key === " ") {
                      ev.preventDefault();
                      clickRow(order, r.key, ev.shiftKey);
                    } else if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
                      ev.preventDefault();
                      const to = ev.key === "ArrowDown" ? ev.currentTarget.nextElementSibling : ev.currentTarget.previousElementSibling;
                      if (to instanceof HTMLElement) to.focus();
                    }
                  }}
                  className={cn("relative flex items-start gap-2 border-b px-3 py-2.5 last:border-b-0 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset sm:table-row", on && "bg-brand-soft/50", draggable && "cursor-grab", drag?.key === r.key && "opacity-40")}
                >
                  <td className="w-8 pt-0.5 sm:table-cell sm:border-b sm:px-3 sm:py-2.5 sm:align-top">
                    <input
                      type="checkbox"
                      aria-label={`Tick ${r.title}`}
                      className="size-4 accent-[var(--brand)]"
                      checked={on}
                      onChange={() => undefined}
                      onClick={(e) => {
                        clickRow(order, r.key, e.shiftKey);
                      }}
                    />
                  </td>
                  <td className="min-w-0 flex-1 sm:table-cell sm:border-b sm:px-3 sm:py-2.5 sm:align-top">
                    <div className="flex items-center gap-1">
                      <TicketTitle itemKey={r.key} links={r.links} className="line-clamp-2">
                        {r.title}
                      </TicketTitle>
                    </div>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground sm:hidden">
                      <StateBadge r={r} />
                      {showMap && <MapName links={r.links} name={r.map.split("/").pop() ?? ""} title={r.mapTitle} />}
                      <span>{r.type}</span>
                      {r.priority !== null && <span>{`priority ${r.priority}`}</span>}
                      <span>{r.tier}</span>
                    </p>
                  </td>
                  {showMap && (
                    <td className="hidden max-w-48 truncate text-xs text-muted-foreground sm:table-cell sm:border-b sm:px-3 sm:py-2.5 sm:align-top">
                      <MapName links={r.links} name={r.mapTitle} title={r.map} />
                    </td>
                  )}
                  <td className="hidden text-xs text-muted-foreground sm:table-cell sm:border-b sm:px-3 sm:py-2.5 sm:align-top">{r.type}</td>
                  <td className="hidden sm:table-cell sm:border-b sm:px-3 sm:py-2.5 sm:align-top">
                    <StateBadge r={r} />
                  </td>
                  <td className="hidden text-xs text-muted-foreground sm:table-cell sm:border-b sm:px-3 sm:py-2.5 sm:align-top">{r.priority ?? ""}</td>
                  <td className="hidden text-xs text-muted-foreground sm:table-cell sm:border-b sm:px-3 sm:py-2.5 sm:align-top">{r.tier}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
        <span>{`${String(sorted.length)} of ${plural(all.length, "ticket")}`}</span>
        {page.pages > 1 && (
          <>
            <Button size="xs" variant="outline" disabled={page.page <= 1} onClick={() => { setLink({ page: String(page.page - 1) }); }}>
              Previous
            </Button>
            <span>{`Page ${String(page.page)} of ${String(page.pages)}`}</span>
            <Button size="xs" variant="outline" disabled={page.page >= page.pages} onClick={() => { setLink({ page: String(page.page + 1) }); }}>
              Next
            </Button>
          </>
        )}
      </div>
      <SelectionBar rows={all} />
    </section>
  );
}
