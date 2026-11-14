/**
 * History, view 5: every run from the queue and the vault's run folders, newest first and grouped by day, with search, chips
 * for outcome, pictures, account and model, and a time range. A run opens beside the list (?run=<key>); on a phone it takes the page.
 */
import { IconPhoto, IconRobot } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { Run, RunOutcome } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { hm, plural } from "@/lib/board.ts";
import { choices, DEFAULT_RANGE, filterRuns, groupByDay, minutesOf, outcomeOf, OUTCOMES, RANGES, RANGE_WORDS, rangeOf, sinceOf } from "@/lib/history.ts";
import { useRuns } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { cn } from "@/lib/utils";
import { Empty, ToneIcon } from "./bits.tsx";
import { useBoard } from "./context.tsx";
import { OUTCOME, RunViewer } from "./RunViewer.tsx";

const PAGE = 300;

export function HistoryView(): React.JSX.Element {
  const { state, scope } = useBoard();
  const link = useLink();
  const [limit, setLimit] = useState(PAGE);
  const range = rangeOf(link.range);
  const q = useRuns(sinceOf(range, state.now), limit);
  const all = q.data?.runs ?? [];
  const outcome = outcomeOf(link.out);
  const { accounts, models } = choices(all);
  const shown = filterRuns(all, { q: link.q, outcome, pictures: link.pics === "1", account: link.acct, model: link.model }, scope);
  const days = groupByDay(shown, state.now);
  const open = shown.find((r) => r.key === link.run) ?? all.find((r) => r.key === link.run);
  const total = q.data?.total ?? 0;
  const narrowed = link.q !== "" || outcome !== "" || link.pics === "1" || link.acct !== "" || link.model !== "";
  return (
    <div className="flex flex-col gap-3">
      <h2 className="sr-only">History</h2>
      <div className={cn(open !== undefined && "max-lg:hidden")}>
        <Filters accounts={accounts} models={models} />
      </div>
      <div className={cn("grid gap-4", open !== undefined ? "lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]" : "mx-auto w-full max-w-5xl")}>
        <div className={cn("flex min-w-0 flex-col gap-3", open !== undefined && "max-lg:hidden")}>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {q.isPending ? "Reading the runs…" : q.isError ? "The runs could not be read." : `${plural(shown.length, "run")}${narrowed || shown.length !== all.length ? ` of ${String(all.length)}` : ""} · ${RANGE_WORDS[range].toLowerCase()}`}
          </p>
          {q.data !== undefined && shown.length === 0 && <Empty>{narrowed ? "No run matches. Loosen a filter, or pick a longer time range." : "No run in this time range."}</Empty>}
          {days.map((d) => (
            <section key={d.label} aria-label={d.label} className="flex flex-col gap-1">
              <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{d.label}</h3>
              <ul className="flex flex-col divide-y rounded-xl border bg-card">
                {d.runs.map((r) => (
                  <RunRow key={r.key} r={r} active={r.key === link.run} />
                ))}
              </ul>
            </section>
          ))}
          {q.data !== undefined && total > all.length && (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => {
                setLimit(limit + PAGE);
              }}
            >
              {`Show ${String(Math.min(PAGE, total - all.length))} more of ${String(total - all.length)}`}
            </Button>
          )}
        </div>
        {open !== undefined && <RunViewer key={open.key} run={open} />}
      </div>
    </div>
  );
}

function RunRow({ r, active }: { r: Run; active: boolean }): React.JSX.Element {
  const [Ic, word, tone] = OUTCOME[r.outcome];
  const mins = minutesOf(r);
  return (
    <li className={cn("relative flex items-start gap-3 px-4 py-2.5 first:rounded-t-xl last:rounded-b-xl hover:bg-accent/40", active && "bg-accent/60")}>
      <span className="mt-0.5"><ToneIcon icon={Ic} tone={tone} label={word} /></span>
      <div className="min-w-0 flex-1">
        <button
          type="button"
          aria-current={active ? "true" : undefined}
          onClick={() => { setLink({ run: r.key, pic: "" }); }}
          className="line-clamp-2 text-left text-sm font-medium after:absolute after:inset-0 after:content-[''] hover:underline focus-visible:underline focus-visible:outline-none"
        >
          {r.title}
        </button>
        {r.reason !== "" && <p className={cn("truncate text-sm", r.outcome === "failed" ? "text-destructive" : "text-warn")} title={r.reason}>{r.reason}</p>}
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span>{`${r.project} · ${r.map.includes("/") ? r.map.slice(r.map.indexOf("/") + 1) : r.map}`}</span>
          {r.account !== null && <span className="inline-flex items-center gap-1"><IconRobot className="size-3.5" aria-hidden />{r.account}</span>}
          {r.model !== null && <Badge>{r.model}</Badge>}
          {mins !== null && <span>{`${String(mins)} min`}</span>}
          {r.commit !== null && <code className="font-mono">{r.commit.slice(0, 7)}</code>}
          {r.pictures.length > 0 && <span className="inline-flex items-center gap-1" title={plural(r.pictures.length, "picture")}><IconPhoto className="size-3.5" aria-hidden />{r.pictures.length}</span>}
        </div>
      </div>
      <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{r.ended === null ? "" : hm(r.ended)}</span>
    </li>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }): React.JSX.Element {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn("inline-flex h-7 items-center rounded-full border px-3 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none", on ? "border-transparent bg-foreground text-background" : "bg-card text-muted-foreground hover:bg-accent hover:text-foreground")}
    >
      {children}
    </button>
  );
}

function Filters({ accounts, models }: { accounts: string[]; models: string[] }): React.JSX.Element {
  const link = useLink();
  const outcome = outcomeOf(link.out);
  const range = link.range === "" ? DEFAULT_RANGE : rangeOf(link.range);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="search"
          data-find
          aria-label="Search runs"
          placeholder="Search titles, reasons, commits  ( / )"
          value={link.q}
          onChange={(e) => { setLink({ q: e.target.value }); }}
          className="w-full sm:w-80"
        />
        <div role="group" aria-label="Time range" className="flex gap-1">
          {RANGES.map((r) => (
            <Chip key={r} on={range === r} onClick={() => { setLink({ range: r === DEFAULT_RANGE ? "" : r }); }}>
              {RANGE_WORDS[r]}
            </Chip>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Outcome" className="flex flex-wrap gap-1">
          {OUTCOMES.map((o: RunOutcome) => (
            <Chip key={o} on={outcome === o} onClick={() => { setLink({ out: outcome === o ? "" : o }); }}>
              {OUTCOME[o][1]}
            </Chip>
          ))}
        </div>
        <Chip on={link.pics === "1"} onClick={() => { setLink({ pics: link.pics === "1" ? "" : "1" }); }}>Has pictures</Chip>
        {accounts.length > 0 && (
          <Select aria-label="Account" value={link.acct} onChange={(e) => { setLink({ acct: e.target.value }); }} className="h-7 text-xs">
            <option value="">Any account</option>
            {accounts.map((a) => <option key={a} value={a}>{a}</option>)}
          </Select>
        )}
        {models.length > 0 && (
          <Select aria-label="Model" value={link.model} onChange={(e) => { setLink({ model: e.target.value }); }} className="h-7 text-xs">
            <option value="">Any model</option>
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </Select>
        )}
      </div>
    </div>
  );
}
