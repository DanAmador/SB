/**
 * History: one row per run (a night), newest first, each with its name, when, how it ended and its counts. A run
 * opens (?night=<id>) to its graph, the tickets it did with outcome, report, review and log links, and the
 * tickets its stop never reached, which can be queued again. The ticket filters work inside the open run.
 */
import { IconArrowLeft, IconBan, IconCircleCheck, IconCircleDashed, IconGitCommit, IconLoader2, IconPhoto, IconRobot, IconX } from "@tabler/icons-react";
import type * as React from "react";
import type { Night, QueueItem, RunOutcome } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { itemInScope, itemTitle, mapInScope, plural, projOf, withBlockers } from "@/lib/board.ts";
import { filterItems, itemOutcome, nightWords, OUTCOMES, outcomeOf, sortNights, type ItemOutcome } from "@/lib/history.ts";
import { useNight, useNights, useRuns } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { chatItems, stateWords, withChats } from "@/lib/night.ts";
import { cn } from "@/lib/utils";
import { Empty, ToneIcon } from "./bits.tsx";
import { useBoard } from "./context.tsx";
import { NightGraph } from "./NightGraph.tsx";
import { OUTCOME, RunViewer } from "./RunViewer.tsx";

const stamp = (sec: number): string => {
  const d = new Date(sec * 1000);
  return `${d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}, ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
};

export function HistoryView(): React.JSX.Element {
  const link = useLink();
  const nights = useNights();
  const list = sortNights(nights.data?.nights ?? []);
  const open = list.find((n) => n.id === link.night);
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-3">
      <h2 className="sr-only">History</h2>
      {open !== undefined ? (
        <NightDetail key={open.id} night={open} />
      ) : (
        <>
          <p className="text-xs text-muted-foreground" aria-live="polite">
            {nights.isPending ? "Reading the runs…" : nights.isError ? "The runs could not be read." : plural(list.length, "run")}
          </p>
          {nights.data !== undefined && list.length === 0 && <Empty>No run yet. Queue a map and one starts.</Empty>}
          {list.length > 0 && (
            <ul aria-label="Runs" className="flex flex-col divide-y rounded-xl border bg-card">
              {list.map((n) => (
                <NightRow key={n.id} n={n} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function NightRow({ n }: { n: Night }): React.JSX.Element {
  const live = n.state !== "ended";
  return (
    <li data-night={n.id} className="relative flex flex-col gap-0.5 px-4 py-3 first:rounded-t-xl last:rounded-b-xl hover:bg-accent/40">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <button
          type="button"
          onClick={() => { setLink({ night: n.id }); }}
          className="min-w-0 text-left text-sm font-medium after:absolute after:inset-0 after:content-[''] hover:underline focus-visible:underline focus-visible:outline-none"
        >
          {n.name}
        </button>
        <Badge tone={live ? "brand" : "neutral"}>{stateWords(n)}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">{`${stamp(n.started)} · ${nightWords(n.counts)}`}</p>
    </li>
  );
}

const MARK: Readonly<Record<ItemOutcome, [typeof IconCircleCheck, "ok" | "bad" | "warn" | "brand" | "muted"]>> = {
  done: [IconCircleCheck, "ok"],
  landed: [IconGitCommit, "warn"],
  "fell short": [IconX, "bad"],
  stopped: [IconBan, "warn"],
  running: [IconLoader2, "brand"],
  next: [IconCircleDashed, "muted"],
};

function NightDetail({ night }: { night: Night }): React.JSX.Element {
  const { scope, ix, tickets, queueWrite, state, down, busy } = useBoard();
  const link = useLink();
  const detail = useNight(night.id);
  const runs = useRuns(0, 300);
  // the chats' work on this run is kept beside the queue's items
  const all = withChats(detail.data?.night.items ?? [], chatItems(state, night.id));
  const inScope = all.filter((i) => itemInScope(scope, i));
  const titleOf = (i: QueueItem): string => itemTitle(i, ix.byKey.get(i.key) ?? (tickets ?? []).find((t) => `${t.map}#${String(t.num)}` === i.key));
  const outcome = outcomeOf(link.out);
  const shown = filterItems(inScope, { q: link.q, outcome, pictures: link.pics === "1", account: link.acct, model: link.model }, titleOf);
  const accounts = [...new Set(inScope.map((i) => i.runner ?? i.agent).filter((x): x is string => x != null && x !== ""))].sort();
  const models = [...new Set(inScope.map((i) => i.model).filter((x): x is string => x != null && x !== ""))].sort();
  const unreached = night.not_reached.filter((r) => mapInScope(scope, r.key.replace(/#\d+$/, "")));
  // the ones still open and not in the line: the others were done another way meanwhile
  const again = unreached.filter((r) => ix.byKey.has(r.key) && !ix.live.has(r.key) && !ix.doneKeys.has(r.key)).map((r) => r.key);
  const narrowed = link.q !== "" || outcome !== "" || link.pics === "1" || link.acct !== "" || link.model !== "";
  const record = runs.data?.runs.find((r) => r.key === link.run);
  const can = !down && !busy;
  const queueAgain = (): void => {
    const keys: string[] = [...state.queue.items.filter((i) => i.state === "queued" && i.kind === "ticket").map((i) => i.key)];
    for (const k of again) for (const b of withBlockers(k, ix)) if (!keys.includes(b)) keys.push(b);
    void queueWrite("POST /api/queue/set", { keys, version: state.queue.version }, `Queued ${plural(again.length, "ticket")} again.`).then((o) => {
      if (o.ok) setLink({ view: "run", night: "" });
    });
  };
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-1 rounded-xl border bg-card px-4 py-3" data-testid="night-detail">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" size="icon-sm" aria-label="Back to the runs" title="Back to the runs" className="-ml-2" onClick={() => { setLink({ night: "", run: "" }); }}>
            <IconArrowLeft aria-hidden />
          </Button>
          <h3 className="min-w-0 flex-1 text-base font-semibold">{night.name}</h3>
          <Badge tone={night.state !== "ended" ? "brand" : "neutral"}>{stateWords(night)}</Badge>
        </div>
        <p className="text-xs text-muted-foreground">{`${stamp(night.started)}${night.ended !== null ? ` to ${stamp(night.ended)}` : ""} · ${nightWords(night.counts)}`}</p>
        {night.state !== "ended" && (
          <Button variant="ghost" size="sm" className="w-fit px-0 text-brand" onClick={() => { setLink({ view: "run", night: "" }); }}>
            This run is live: open it on the Run tab
          </Button>
        )}
      </div>
      {detail.data !== undefined && <NightGraph items={all} title="The run's graph" {...(night.state === "ended" && { frozen: night })} />}
      {unreached.length > 0 && (
        <section aria-label="Not reached" data-testid="not-reached" className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold">{`Not reached (${String(unreached.length)})`}</h3>
            <Button size="sm" variant="outline" disabled={!can || again.length === 0} onClick={queueAgain}>
              Queue these again
            </Button>
          </div>
          <ul className="flex flex-col divide-y rounded-xl border bg-card">
            {unreached.map((r) => (
              <li key={r.key} data-key={r.key} data-mark="not reached" className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <ToneIcon icon={IconCircleDashed} tone="muted" label="not reached" />
                <button type="button" className="min-w-0 flex-1 basis-48 text-left hover:underline" onClick={() => { setLink({ t: r.key }); }}>
                  {r.title}
                </button>
                <span className="text-xs text-muted-foreground">{again.includes(r.key) ? "not reached, still open" : "not reached, not open now"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-label="Tickets of the run" className="flex flex-col gap-2">
        <Filters accounts={accounts} models={models} />
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {detail.isPending ? "Reading the run…" : `${plural(shown.length, "ticket")}${narrowed || shown.length !== all.length ? ` of ${String(all.length)}` : ""}`}
        </p>
        {detail.data !== undefined && shown.length === 0 && <Empty>{narrowed ? "No ticket matches. Loosen a filter." : "No ticket ran in this run."}</Empty>}
        {shown.length > 0 && (
          <ul aria-label="Tickets of the run" className="flex flex-col divide-y rounded-xl border bg-card">
            {shown.map((i) => (
              <ItemRow key={i.key} i={i} title={titleOf(i)} hasRun={runs.data?.runs.some((r) => r.key === i.key) === true} />
            ))}
          </ul>
        )}
      </section>
      {record !== undefined && <RunViewer key={record.key} run={record} />}
    </div>
  );
}

function ItemRow({ i, title, hasRun }: { i: QueueItem; title: string; hasRun: boolean }): React.JSX.Element {
  const o = itemOutcome(i);
  const [Ic, tone] = MARK[o];
  const links: [string, string | null][] = [["Report", i.links.report], ["Review", i.links.review ?? null], ["Log", i.links.log]];
  return (
    <li data-key={i.key} data-mark={o} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
      <ToneIcon icon={Ic} tone={tone} label={o} spin={o === "running"} />
      <div className="min-w-0 flex-1 basis-48">
        <button type="button" className="line-clamp-2 text-left font-medium hover:underline" onClick={() => { setLink({ t: i.key }); }}>
          {title}
        </button>
        <p className="truncate text-xs text-muted-foreground">
          {`${projOf(i.key.replace(/#\d+$/, ""))} · ${o}`}
          {i.commit !== null && <code className="ml-1 font-mono">{i.commit.slice(0, 7)}</code>}
        </p>
      </div>
      <div className="flex max-w-full flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {(i.runner ?? i.agent) != null && <span className="inline-flex items-center gap-1"><IconRobot className="size-3.5" aria-hidden />{i.runner ?? i.agent}</span>}
        {(i.media ?? []).length > 0 && <span className="inline-flex items-center gap-1" title={plural((i.media ?? []).length, "picture")}><IconPhoto className="size-3.5" aria-hidden />{(i.media ?? []).length}</span>}
        {links.filter((l): l is [string, string] => l[1] !== null).map(([w, href]) => (
          <a key={w} href={href} className="text-brand underline-offset-2 hover:underline" title={`Open the ${w.toLowerCase()} in Obsidian`}>{w}</a>
        ))}
        {hasRun && (
          <Button variant="ghost" size="xs" onClick={() => { setLink({ run: i.key, pic: "" }); }}>
            Details
          </Button>
        )}
      </div>
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
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="search"
          data-find
          aria-label="Search tickets"
          placeholder="Search tickets  ( / )"
          value={link.q}
          onChange={(e) => { setLink({ q: e.target.value }); }}
          className="w-full sm:w-80"
        />
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
