/**
 * The head of the live run, above its graph: its name (click to rename), when it started and who started it, one
 * line of counts, the at-once-and-accounts settings, and Stop run, which asks once. While the run stops it says so and names what still runs. With no
 * run live it says so, counts what waits for Start, offers Start (queueing never starts a run), and shows the last
 * run as one line with a link to it.
 */
import { IconCheck, IconPencil, IconPlayerPlay, IconPlayerStop, IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { Night } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { agentOf, hm, itemTitle } from "@/lib/board.ts";
import { useNights } from "@/lib/hub.ts";
import { setLink } from "@/lib/link.ts";
import { nightWords } from "@/lib/history.ts";
import { nowNext } from "@/lib/now.ts";
import { headLine, liveItems, liveRecord, stateWords, stopAsk, stoppingWords } from "@/lib/night.ts";
import { LimitsButton } from "./RunControls.tsx";
import { useBoard } from "./context.tsx";

const when = (sec: number): string => {
  const d = new Date(sec * 1000);
  const day = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${day}, ${hm(sec)}`;
};

export function RunHead(): React.JSX.Element | null {
  const { state } = useBoard();
  const nights = useNights();
  const id = state.queue.night;
  // a hub that knows no runs has no head
  if (id === undefined) return null;
  const list = nights.data?.nights ?? [];
  if (id === null) return <NoRun last={list.find((n) => n.state === "ended") ?? null} />;
  return <Live rec={liveRecord(list, id)} />;
}

function NoRun({ last }: { last: Night | null }): React.JSX.Element {
  const { state, ix, writes, down, busy } = useBoard();
  const waiting = state.queue.items.filter((i) => i.state === "queued" && !i.night && !(i.kind === "job" && (i.close_off === true || i.hub === true))).length;
  // what runs or waits outside any run, a close-off job say, which the count above leaves out: it still runs
  const n = nowNext(state.queue.items);
  const outside = [...n.running, ...n.queued.filter((i) => i.kind === "job" && (i.close_off === true || i.hub === true))];
  return (
    <section aria-label="The live run" data-testid="run-head" data-live="false" className="flex flex-col gap-1 rounded-xl border bg-card px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 className="min-w-0 flex-[1_1_12rem] text-sm font-semibold">No run is live</h2>
        <Button
          size="sm"
          data-testid="run-start"
          disabled={down || busy}
          onClick={() => { void writes.night("POST /api/night/start", {}, "Run started."); }}
        >
          <IconPlayerPlay aria-hidden />
          Start run
        </Button>
      </div>
      <p className="text-sm text-muted-foreground" data-testid="waits-start">
        {waiting === 0 ? "Queue a map or a ticket, then press Start." : `${String(waiting)} queued, waiting for Start. Nothing runs until you press it.`}
      </p>
      {outside.length > 0 && (
        <p data-testid="outside-run" className="text-sm">
          {`Also in the queue: ${outside.map((i) => itemTitle(i, ix.byKey.get(i.key))).join(", ")}.`}
        </p>
      )}
      {last !== null && (
        <p data-testid="last-run" className="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span className="text-muted-foreground">Last run:</span>
          <button
            type="button"
            className="font-medium text-brand underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            onClick={() => { setLink({ view: "history", night: last.id }); }}
          >
            {last.name}
          </button>
          <span className="text-muted-foreground">{`${stateWords(last)} · ${nightWords(last.counts)}`}</span>
        </p>
      )}
    </section>
  );
}

function Live({ rec }: { rec: Night | null }): React.JSX.Element {
  const { state, ix, writes, down, busy, tickets } = useBoard();
  // the counts take the chats' tickets too; Stop asks only about what the hub itself runs
  const items = liveItems(state.queue, state);
  const hubItems = liveItems(state.queue);
  const [asking, setAsking] = useState(false);
  const [naming, setNaming] = useState<string | null>(null);
  const stopping = rec?.state === "stopping";
  const can = !down && !busy;
  const ask = stopAsk(hubItems);
  const by = rec?.by == null ? null : (agentOf(state, rec.by)?.title ?? rec.by);
  const titleOf = (i: (typeof items)[number]): string => itemTitle(i, ix.byKey.get(i.key) ?? (tickets ?? []).find((t) => `${t.map}#${String(t.num)}` === i.key));
  const rename = async (): Promise<void> => {
    const name = (naming ?? "").trim();
    setNaming(null);
    if (name === "" || name === rec?.name) return;
    await writes.night("POST /api/night/rename", { name }, "Renamed the run.");
  };
  return (
    <section aria-label="The live run" data-testid="run-head" data-live="true" data-stopping={stopping ? "true" : "false"} className="flex flex-col gap-2 rounded-xl border bg-card px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {naming === null ? (
          <h2 className="min-w-0 flex-[1_1_12rem] text-base font-semibold">
            <button
              type="button"
              title="Rename the run"
              aria-label={`Rename the run ${rec?.name ?? ""}`}
              disabled={rec === null || !can}
              className="group inline-flex max-w-full items-center gap-1.5 rounded-md text-left hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              onClick={() => { setNaming(rec?.name ?? ""); }}
            >
              <span className="truncate" data-testid="run-name">{rec?.name ?? "This run"}</span>
              <IconPencil className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            </button>
          </h2>
        ) : (
          <form
            className="flex min-w-0 flex-[1_1_12rem] items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              void rename();
            }}
          >
            <Input aria-label="Run name" autoFocus value={naming} onChange={(e) => { setNaming(e.target.value); }} className="h-8 min-w-0 flex-1" />
            <Button type="submit" size="icon-sm" variant="ghost" aria-label="Save the name"><IconCheck aria-hidden /></Button>
            <Button type="button" size="icon-sm" variant="ghost" aria-label="Cancel renaming" onClick={() => { setNaming(null); }}><IconX aria-hidden /></Button>
          </form>
        )}
        <LimitsButton />
        {stopping ? (
          <Badge tone="warn">stopping</Badge>
        ) : (
          !asking && (
            <Button variant="outline" size="sm" disabled={!can || rec === null} onClick={() => { setAsking(true); }}>
              <IconPlayerStop aria-hidden />
              Stop run
            </Button>
          )
        )}
      </div>
      {rec !== null && (
        <p className="text-xs text-muted-foreground" data-testid="run-started">
          {`Started ${when(rec.started)}`}
          {by !== null && ` by ${by}`}
        </p>
      )}
      <p className="text-sm font-medium" data-testid="head-counts">{headLine(items)}</p>
      {stopping && <p role="status" data-testid="stopping" className="text-sm text-warn">{stoppingWords(hubItems, titleOf)}</p>}
      {asking && !stopping && (
        <div role="group" aria-label="Stop the run?" className="flex flex-col gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm">
          <p>{ask.text}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={!can}
              onClick={() => {
                setAsking(false);
                void writes.night("POST /api/night/stop", { mode: "after" }, "Stopping: what runs now will finish.");
              }}
            >
              <IconPlayerStop aria-hidden />
              Stop after what runs
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setAsking(false); }}>Keep it running</Button>
          </div>
        </div>
      )}
    </section>
  );
}
