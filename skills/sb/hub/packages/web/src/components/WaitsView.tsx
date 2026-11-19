/**
 * Waits for you: questions first, then landed, failed and done runs (a few lines each, a fold per project when there
 * are several), then tickets that wait for a decision, then accounts and widgets in trouble.
 */
import { IconAlertTriangle, IconBan, IconCheck, IconChecks, IconCircleCheck, IconExternalLink, IconGitCommit, IconLock, IconRefresh, IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { QueueItem, TicketRow } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { IN_WIDGET, READONLY } from "@/lib/api.ts";
import { ago, canTickAgain, folder, hm, itemProject, itemTitle, landedShort, mapTitle, plainReason, projOf, seenKey, tkey, type Waits } from "@/lib/board.ts";
import { cn } from "@/lib/utils";
import { setLink } from "@/lib/link.ts";
import { say } from "@/lib/notice.ts";
import { Markdown } from "./Markdown.tsx";
import { QuestionCard } from "./QuestionCard.tsx";
import { Checks, Empty, FileLinks, Fold, MapName, Pictures, ProjectChips, SectionTitle, TicketTitle, ToneIcon } from "./bits.tsx";
import { useBoard } from "./context.tsx";

export function WaitsView({ w, projects }: { w: Waits; projects: readonly [string, number][] }): React.JSX.Element {
  const { writes, down } = useBoard();
  const runs = [...w.failed, ...w.done];
  const nothing = w.questions.length + runs.length + w.tickets.length + w.signedOut.length + w.badWidgets.length === 0;
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <ProjectChips counts={projects} label="Projects with something waiting" />
        </div>
        {runs.length > 0 && (
          <Button
            variant="outline"
            size="xs"
            disabled={down}
            title="Moves every run listed here to History; nothing in the queue or the vault changes"
            onClick={() => {
              void writes.seen(runs.map(seenKey)).then(say);
            }}
          >
            <IconChecks aria-hidden />
            Mark all seen
          </Button>
        )}
      </div>
      {nothing && <Empty>Nothing waits for you.</Empty>}
      {w.questions.length > 0 && (
        <Part id="questions" title="Questions">
          <div className="grid gap-3 md:grid-cols-2">
            {w.questions.map(([id, q]) => (
              <QuestionCard key={id} id={id} q={q} />
            ))}
          </div>
        </Part>
      )}
      <Ended title="Landed, needs your look" id="landed" runs={w.failed.filter(landedShort)} />
      <Ended title="Failed" id="failed" runs={w.failed.filter((i) => !landedShort(i))} />
      <Ended title="Done" id="done" runs={w.done} />
      {w.tickets.length > 0 && (
        <Part id="decide" title="Tickets that need a decision" aside={<span className="text-xs text-muted-foreground">{String(w.tickets.length)}</span>}>
          <p className="text-xs text-muted-foreground">Design questions no worker can settle. They wait days, not minutes, so the tab does not count them.</p>
          <div className="flex flex-col divide-y rounded-xl border bg-card">
            {groupBy(w.tickets, (t) => projOf(t.map)).map(([p, ts]) => (
              <Fold key={p} className="px-4 py-1" summary={<><span className="font-medium">{p}</span><span className="text-muted-foreground">{String(ts.length)}</span></>}>
                <ul className="flex flex-col divide-y pb-1">
                  {ts.map((t) => (
                    <DecideLine key={tkey(t)} t={t} />
                  ))}
                </ul>
              </Fold>
            ))}
          </div>
        </Part>
      )}
      {w.signedOut.length + w.badWidgets.length > 0 && (
        <Part id="trouble" title="Accounts and projects">
          <ul className="flex flex-col divide-y rounded-xl border bg-card">
            {w.signedOut.map((n) => (
              <li key={`out-${n}`} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <ToneIcon icon={IconLock} tone="bad" label="signed out" />
                <span className="font-medium">{n}</span>
                <span className="text-muted-foreground">is signed out: sign in again; until then it runs nothing.</span>
              </li>
            ))}
            {w.badWidgets.map((b) => (
              <li key={`w-${b.project}-${b.panel}-${b.label}`} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <ToneIcon icon={IconAlertTriangle} tone="bad" label="failing" />
                <span className="shrink-0 font-medium">{`${folder(b.project)} · ${b.label}`}</span>
                <span className="truncate text-muted-foreground">{b.value.slice(0, 160)}</span>
              </li>
            ))}
          </ul>
        </Part>
      )}
    </div>
  );
}

function Part({ id, title, children, aside }: { id: string; title: string; children: React.ReactNode; aside?: React.ReactNode }): React.JSX.Element {
  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-2">
      <SectionTitle aside={aside}>
        <span id={`${id}-title`}>{title}</span>
      </SectionTitle>
      {children}
    </section>
  );
}

const ENDED = {
  done: [IconCircleCheck, "done", "ok"],
  landed: [IconGitCommit, "landed, needs your look", "warn"],
  failed: [IconX, "failed", "bad"],
  skipped: [IconBan, "skipped", "warn"],
} as const;

/** A section folds its projects shut once it holds more runs than this. */
const OPEN_UP_TO = 4;

/**
 * Landed, Failed or Done: the runs not yet looked at, a row each. With more than one project they sit in a fold per
 * project, the busiest first; the folds start shut once the section is long. Mark seen moves the section to History.
 */
function Ended({ title, id, runs }: { title: string; id: string; runs: readonly QueueItem[] }): React.JSX.Element | null {
  const { ix, writes, down } = useBoard();
  if (runs.length === 0) return null;
  // a job names its folder as typed, a ticket its project in lower case: one group for both
  const groups = groupBy(runs, (i) => itemProject(i, ix.byKey.get(i.key)).toLowerCase());
  const list = (rs: readonly QueueItem[], project: boolean, className?: string): React.JSX.Element => (
    <ul className={cn("flex flex-col divide-y", className)}>
      {rs.map((i) => (
        <RunLine key={seenKey(i)} i={i} project={project} />
      ))}
    </ul>
  );
  return (
    <Part
      id={id}
      title={title}
      aside={
        <>
          <span className="text-xs text-muted-foreground tabular-nums">{String(runs.length)}</span>
          <Button
            variant="ghost"
            size="xs"
            disabled={down}
            title={`Moves these ${String(runs.length)} runs to History; nothing in the queue or the vault changes`}
            aria-label={`Mark seen: the ${title} runs`}
            onClick={() => {
              void writes.seen(runs.map(seenKey)).then(say);
            }}
          >
            <IconChecks aria-hidden />
            Mark seen
          </Button>
        </>
      }
    >
      <div className="flex flex-col divide-y rounded-xl border bg-card">
        {groups.length === 1
          ? list(runs, true)
          : groups.map(([p, rs]) => (
              <Fold
                key={p}
                className="px-4 py-1"
                defaultOpen={runs.length <= OPEN_UP_TO}
                summary={
                  <>
                    <span className="font-medium">{p}</span>
                    <span className="text-muted-foreground tabular-nums">{String(rs.length)}</span>
                  </>
                }
              >
                {list(rs, false, "-mx-4 border-t")}
              </Fold>
            ))}
      </div>
    </Part>
  );
}

/**
 * An ended run in a few lines: its title and age; its project, commit and reason on one line (the full reason folds
 * open under it); its checks as one line; its buttons, with its pictures as one link.
 */
function RunLine({ i, project }: { i: QueueItem; project: boolean }): React.JSX.Element {
  const { state, ix, enqueue, down, busy, writes } = useBoard();
  const st = i.state === "done" || i.state === "skipped" ? i.state : landedShort(i) ? "landed" : "failed";
  const [Ic, word, tone] = ENDED[st];
  const t = ix.byKey.get(i.key);
  const title = itemTitle(i, t);
  const done = i.state === "done";
  const again = canTickAgain(i, ix);
  const reason = done ? "" : plainReason(i);
  const reasonCls = cn("min-w-0 truncate break-words", i.state === "skipped" || st === "landed" ? "text-warn" : "text-destructive");
  const meta = (
    <span className="shrink-0 text-muted-foreground">
      {project && itemProject(i, t)}
      {i.commit !== null && (
        <>
          {project && " · "}
          <IconGitCommit className="inline size-3.5 align-[-2px]" aria-hidden /> <code className="font-mono">{i.commit.slice(0, 9)}</code>
        </>
      )}
    </span>
  );
  const hasMeta = project || i.commit !== null;
  return (
    <li className="flex gap-3 px-4 py-2.5">
      <div className="pt-0.5">
        <ToneIcon icon={Ic} tone={tone} label={word} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-baseline gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1">
            <TicketTitle itemKey={i.key} links={i.links} className="truncate">
              {title}
            </TicketTitle>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground" title={`${word} at ${hm(i.ended ?? 0)}`}>
            {ago(state.now, i.ended)}
          </span>
        </div>
        {reason !== "" && i.note.trim() !== "" ? (
          <Fold
            className="text-xs [&>summary]:min-h-5"
            summary={
              <span className="flex min-w-0 items-baseline gap-1.5" title={reason}>
                {hasMeta && meta}
                {hasMeta && <span className="text-muted-foreground">·</span>}
                <span className={reasonCls}>{reason}</span>
              </span>
            }
          >
            <pre className="mt-1 max-h-60 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">{i.note}</pre>
          </Fold>
        ) : (
          (hasMeta || reason !== "") && (
            <p className="flex min-w-0 items-baseline gap-1.5 text-xs" title={reason || undefined}>
              {hasMeta && meta}
              {hasMeta && reason !== "" && <span className="text-muted-foreground">·</span>}
              {reason !== "" && <span className={reasonCls}>{reason}</span>}
            </p>
          )
        )}
        <Checks checks={i.checks ?? []} />
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            size="xs"
            variant="outline"
            onClick={() => {
              void writes.seen([seenKey(i)]);
              setLink({ view: "history", run: i.key, pic: "" });
            }}
          >
            <IconExternalLink aria-hidden />
            Open the run
          </Button>
          {done && (
            <Button
              size="xs"
              variant="ghost"
              onClick={() => {
                void writes.seen([seenKey(i)]);
              }}
            >
              <IconCheck aria-hidden />
              Looks good
            </Button>
          )}
          {st === "landed" && (
            <Button
              size="xs"
              variant="brand"
              disabled={down || busy}
              title="Closes the ticket with the commit that landed; what the review found missing stays in its comments"
              onClick={() => {
                void writes
                  .ticket("done", { key: i.key, text: "Good enough: its work landed and the owner closed it; the review's open items are in its comments.", commit: i.commit ?? undefined }, "Closed: its work stays as it landed.")
                  .then((o) => {
                    say(o);
                    if (o.ok) void writes.seen([seenKey(i)]);
                  });
              }}
            >
              <IconCheck aria-hidden />
              Good enough, close it
            </Button>
          )}
          {landAgain(i) && (
            <Button
              size="xs"
              variant="brand"
              disabled={down || busy}
              title="Its work is kept: rebase it, run its checks, land it and review it, without running the worker again"
              onClick={() => {
                void writes.ticket("recheck", { key: i.key }, "It lands again: its checks run now.").then(say);
              }}
            >
              <IconGitCommit aria-hidden />
              Land again
            </Button>
          )}
          {!done && again && (
            <Button
              size="xs"
              variant={landAgain(i) || st === "landed" ? "outline" : "brand"}
              disabled={down || busy}
              onClick={() => {
                void enqueue(i.key);
              }}
            >
              <IconRefresh aria-hidden />
              Run again
            </Button>
          )}
          {!done && (
            <Button
              size="xs"
              variant="ghost"
              title="Moves it to History without opening it"
              onClick={() => {
                void writes.seen([seenKey(i)]);
              }}
            >
              Set aside
            </Button>
          )}
          <Pictures item={i} compact />
          <FileLinks item={i} />
        </div>
      </div>
    </li>
  );
}

/** A failed run whose commit waits in its kept worktree (the hub checks the worktree is there): it could not land, or a check broke. */
const landAgain = (i: QueueItem): boolean => i.kind === "ticket" && i.state === "failed" && !landedShort(i) && Boolean(i.tree) && Boolean(i.commit);

/** Rows per group, the group with the most first. */
function groupBy<T>(rows: readonly T[], keyOf: (r: T) => string): [string, T[]][] {
  const by = new Map<string, T[]>();
  for (const r of rows) by.set(keyOf(r), [...(by.get(keyOf(r)) ?? []), r]);
  return [...by].sort(([a, x], [b, y]) => y.length - x.length || a.localeCompare(b));
}

/** One decision ticket: its question, its options as buttons (the recommended one filled), and a line for the owner's own answer. */
function DecideLine({ t }: { t: TicketRow }): React.JSX.Element {
  const { writes, down } = useBoard();
  const [sending, setSending] = useState<string | null>(null);
  const [own, setOwn] = useState("");
  const options = t.options ?? [];
  const off = down || sending !== null || (READONLY && !IN_WIDGET);
  const rule = async (text: string): Promise<void> => {
    setSending(text);
    const out = await writes.ticket("rule", { key: tkey(t), text }, "Answer saved on the ticket.");
    setSending(null);
    say(out);
    if (out.ok) setOwn("");
  };
  return (
    <li className="flex flex-col gap-2 py-2.5 pl-5">
      <div className="min-w-0">
        <div className="flex items-center gap-1">
          <TicketTitle itemKey={tkey(t)} links={t.links} className="truncate">
            {t.title}
          </TicketTitle>
        </div>
        <p className="truncate text-xs text-muted-foreground">
          <MapName links={t.links} name={t.map.split("/").pop() ?? ""} title={mapTitle(t)} />
          {` · ${t.type}`}
        </p>
      </div>
      {options.length > 0 && (
        <>
          {t.question !== "" && <Markdown text={t.question} className="text-sm text-muted-foreground" />}
          <div role="group" aria-label="Options" className="flex flex-col gap-1.5">
            {options.map((o) => (
              <Button
                key={o.text}
                size="xs"
                variant={o.recommended ? "default" : "outline"}
                disabled={off}
                className="h-auto min-h-7 justify-start py-1 text-left whitespace-normal"
                onClick={() => {
                  void rule(o.text);
                }}
              >
                {sending === o.text ? "Saving…" : o.text}
                {o.recommended && <span className="shrink-0 font-normal opacity-70">· recommended</span>}
              </Button>
            ))}
          </div>
          <form
            className="flex gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              if (own.trim()) void rule(own.trim());
            }}
          >
            <Input
              value={own}
              onChange={(e) => {
                setOwn(e.target.value);
              }}
              placeholder="Or answer in your own words"
              aria-label={`Your own answer to: ${t.title}`}
              disabled={off}
              className="h-7 min-w-0 flex-1 text-sm"
            />
            <Button type="submit" size="xs" variant="outline" disabled={off || !own.trim()}>
              {sending === own.trim() && own.trim() ? "Saving…" : "Answer"}
            </Button>
          </form>
        </>
      )}
    </li>
  );
}
