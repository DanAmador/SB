/** A run beside the History list: what it was, then Pictures, Checks, Report and Log, and the three things to do next. */
import { IconArrowLeft, IconBan, IconCircleCheck, IconHelpCircle, IconNotebook, IconPlayerPlay, IconTicket, IconX } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import type * as React from "react";
import type { Run, RunDetail, RunOutcome } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { mediaUrl } from "@/lib/api.ts";
import { hm, plural, seenKey } from "@/lib/board.ts";
import { minutesOf, searchLog } from "@/lib/history.ts";
import { useRun } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { cn } from "@/lib/utils";
import { Empty, ToneIcon } from "./bits.tsx";
import { useBoard } from "./context.tsx";
import { Markdown } from "./Markdown.tsx";
import { isClip, PictureViewer } from "./PictureViewer.tsx";

export const OUTCOME = {
  done: [IconCircleCheck, "done", "ok", "ok"],
  failed: [IconX, "failed", "bad", "bad"],
  skipped: [IconBan, "skipped", "warn", "warn"],
  unknown: [IconHelpCircle, "unknown", "muted", "neutral"],
} as const satisfies Record<RunOutcome, readonly [unknown, string, string, string]>;

export function RunViewer({ run }: { run: Run }): React.JSX.Element {
  const { ix, enqueue, down, writes, state } = useBoard();
  const link = useLink();
  const mark = run.ended === null || state.seen.includes(seenKey(run)) ? null : seenKey(run);
  // opening a run is looking at it: it leaves Waits for you and stays in History
  useEffect(() => {
    if (mark !== null) void writes.seen([mark]);
  }, [mark, writes]);
  const q = useRun(run.key);
  const detail: RunDetail | undefined = q.data;
  const shown = detail?.run ?? run;
  const [Ic, word, tone, badge] = OUTCOME[shown.outcome];
  const mins = minutesOf(shown);
  const again = ix.byKey.has(run.key) && !ix.live.has(run.key) && !ix.doneKeys.has(run.key);
  const pictures = shown.pictures;
  return (
    <section aria-label="Run" className="flex min-w-0 flex-col gap-3 rounded-xl border bg-card p-4 lg:sticky lg:top-16 lg:max-h-[calc(100dvh-5rem)] lg:overflow-auto">
      <div className="flex items-start gap-2">
        <Button variant="ghost" size="icon-sm" aria-label="Back to the list" title="Back to the list" className="-ml-1 lg:hidden" onClick={() => { setLink({ run: "", pic: "" }); }}>
          <IconArrowLeft aria-hidden />
        </Button>
        <h2 className="min-w-0 flex-1 text-base leading-snug font-semibold">{shown.title}</h2>
        <Button variant="ghost" size="icon-sm" aria-label="Close the run" title="Close the run" className="max-lg:hidden" onClick={() => { setLink({ run: "", pic: "" }); }}>
          <IconX aria-hidden />
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
        <Badge tone={badge} className="gap-1 text-sm">
          <ToneIcon icon={Ic} tone={tone} label={word} />
          {word}
        </Badge>
        {shown.reason !== "" && <span className={shown.outcome === "failed" ? "text-destructive" : "text-warn"}>{shown.reason}</span>}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
        {(
          [
            ["Account", shown.account ?? "—"],
            ["Model", shown.model ?? "—"],
            ["Minutes", mins === null ? "—" : String(mins)],
            ["Tries", String(shown.tries)],
            ["Commit", shown.commit === null ? "—" : shown.commit.slice(0, 9)],
            ["Ended", shown.ended === null ? "—" : `${new Date(shown.ended * 1000).toLocaleDateString([], { day: "numeric", month: "short" })} ${hm(shown.ended)}`],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="truncate font-medium" title={v}>{v}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="brand" disabled={down || !again} title={again ? "Queue this ticket again" : "Its ticket is not open any more"} onClick={() => { void enqueue(run.key); }}>
          <IconPlayerPlay aria-hidden />
          Run again
        </Button>
        {shown.links.report !== null && (
          <Button size="sm" variant="outline" asChild>
            <a href={shown.links.report}><IconNotebook aria-hidden />Report in Obsidian</a>
          </Button>
        )}
        {shown.links.ticket !== null && (
          <Button size="sm" variant="outline" asChild>
            <a href={shown.links.ticket}><IconTicket aria-hidden />Ticket</a>
          </Button>
        )}
      </div>
      <Tabs defaultValue={pictures.length > 0 ? "pictures" : "checks"} key={run.key}>
        <TabsList aria-label="Run details" className="w-full">
          <TabsTrigger value="pictures">{`Pictures${pictures.length > 0 ? ` ${String(pictures.length)}` : ""}`}</TabsTrigger>
          <TabsTrigger value="checks">{`Checks${detail && detail.checks.length > 0 ? ` ${String(detail.checks.length)}` : ""}`}</TabsTrigger>
          <TabsTrigger value="report">Report</TabsTrigger>
          <TabsTrigger value="log">Log</TabsTrigger>
        </TabsList>
        <TabsContent value="pictures" className="mt-3 outline-none">
          {pictures.length === 0 ? <Empty>This run left no pictures.</Empty> : <PictureGrid runKey={run.key} names={pictures} />}
        </TabsContent>
        <TabsContent value="checks" className="mt-3 outline-none">
          {detail === undefined ? <Empty>{q.isError ? "The run could not be read." : "Reading the run…"}</Empty> : <CheckList checks={detail.checks} />}
        </TabsContent>
        <TabsContent value="report" className="mt-3 outline-none">
          {detail === undefined ? <Empty>{q.isError ? "The run could not be read." : "Reading the run…"}</Empty> : detail.report === null ? <Empty>This run has no report.</Empty> : <Markdown text={detail.report} />}
        </TabsContent>
        <TabsContent value="log" className="mt-3 outline-none">
          {detail === undefined ? <Empty>{q.isError ? "The run could not be read." : "Reading the run…"}</Empty> : detail.log === null ? <Empty>This run has no log.</Empty> : <LogTail text={detail.log} />}
        </TabsContent>
      </Tabs>
      {link.pic !== "" && pictures.length > 0 && (
        <PictureViewer runKey={run.key} names={pictures} name={link.pic} onPick={(n) => { setLink({ pic: n }); }} onClose={() => { setLink({ pic: "" }); }} />
      )}
    </section>
  );
}

function PictureGrid({ runKey, names }: { runKey: string; names: readonly string[] }): React.JSX.Element {
  return (
    <ul aria-label="Pictures" className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {names.map((n) => (
        <li key={n}>
          <button type="button" aria-label={`Open ${n}`} title={n} onClick={() => { setLink({ pic: n }); }} className="block aspect-[3/2] w-full overflow-hidden rounded-md border bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
            {isClip(n) ? <video src={`${mediaUrl(runKey, n)}#t=0.1`} preload="metadata" muted playsInline className="size-full object-cover" /> : <img src={mediaUrl(runKey, n)} alt={n} loading="lazy" className="size-full object-cover" />}
          </button>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">{n}</p>
        </li>
      ))}
    </ul>
  );
}

function CheckList({ checks }: { checks: RunDetail["checks"] }): React.JSX.Element {
  if (checks.length === 0) return <Empty>No check ran for this run.</Empty>;
  return (
    <ul aria-label="Checks" className="flex flex-col gap-3">
      {checks.map((c, n) => (
        <li key={`${c.cmd}-${String(n)}`} className="flex flex-col gap-1 text-xs">
          <div className="flex flex-wrap items-center gap-1.5">
            {c.code === 0 ? <ToneIcon icon={IconCircleCheck} tone="ok" label="passed" /> : <ToneIcon icon={IconX} tone="bad" label="failed" />}
            <code className="font-mono break-all">{c.cmd}</code>
          </div>
          <p className="text-muted-foreground">{`${c.code === null ? "timed out" : `exit code ${String(c.code)}`} · ${String(Math.round(c.secs))} s`}</p>
          {c.tail !== "" && <pre className="max-h-48 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap text-muted-foreground">{c.tail}</pre>}
        </li>
      ))}
    </ul>
  );
}

function LogTail({ text }: { text: string }): React.JSX.Element {
  const [q, setQ] = useState("");
  const { lines, found } = searchLog(text, q);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Input type="search" value={q} aria-label="Search the log" placeholder="Search the log" className="flex-1" onChange={(e) => { setQ(e.target.value); }} />
        {q.trim() !== "" && <span className="text-xs text-muted-foreground" aria-live="polite">{plural(found, "line")}</span>}
      </div>
      <pre aria-label="Log" className={cn("max-h-96 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] leading-snug whitespace-pre-wrap")}>
        {lines.length === 0 || (lines.length === 1 && lines[0] === "") ? "Nothing in the log matches." : lines.join("\n")}
      </pre>
    </div>
  );
}
