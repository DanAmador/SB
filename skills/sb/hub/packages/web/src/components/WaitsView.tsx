/**
 * Waits for you: questions first, then failed runs (reason, checks, pictures, Run again), then done runs (checks,
 * pictures, Looks good), then tickets that wait for a decision, then accounts and widgets in trouble.
 */
import { IconAlertTriangle, IconBan, IconCheck, IconChecks, IconCircleCheck, IconExternalLink, IconGitCommit, IconLock, IconRefresh, IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { QueueItem, TicketRow } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { IN_WIDGET, READONLY } from "@/lib/api.ts";
import { ago, canTickAgain, folder, hm, itemProject, itemTitle, mapTitle, plainReason, projOf, seenKey, tkey, type Waits } from "@/lib/board.ts";
import { cn } from "@/lib/utils";
import { setLink } from "@/lib/link.ts";
import { say } from "@/lib/notice.ts";
import { Markdown } from "./Markdown.tsx";
import { QuestionCard } from "./QuestionCard.tsx";
import { Checks, Empty, FileLinks, Fold, MapName, Pictures, SectionTitle, TicketTitle, ToneIcon } from "./bits.tsx";
import { useBoard } from "./context.tsx";

export function WaitsView({ w }: { w: Waits }): React.JSX.Element {
  const { writes, down } = useBoard();
  const runs = [...w.failed, ...w.done];
  const nothing = w.questions.length + runs.length + w.tickets.length + w.signedOut.length + w.badWidgets.length === 0;
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
      {nothing && <Empty>Nothing waits for you.</Empty>}
      {runs.length > 0 && (
        <div className="flex justify-end">
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
        </div>
      )}
      {w.questions.length > 0 && (
        <Part id="questions" title="Questions">
          <div className="grid gap-3 md:grid-cols-2">
            {w.questions.map(([id, q]) => (
              <QuestionCard key={id} id={id} q={q} />
            ))}
          </div>
        </Part>
      )}
      <Ended title="Failed" id="failed" runs={w.failed} />
      <Ended title="Done" id="done" runs={w.done} />
      {w.tickets.length > 0 && (
        <Part id="decide" title="Tickets that need a decision">
          <ul className="flex flex-col divide-y rounded-xl border bg-card">
            {w.tickets.map((t) => (
              <DecideLine key={tkey(t)} t={t} />
            ))}
          </ul>
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
  failed: [IconX, "failed", "bad"],
  skipped: [IconBan, "skipped", "warn"],
} as const;

/** Failed or Done: the runs not yet looked at. */
function Ended({ title, id, runs }: { title: string; id: string; runs: readonly QueueItem[] }): React.JSX.Element | null {
  if (runs.length === 0) return null;
  return (
    <Part id={id} title={title}>
      <ul className="flex flex-col divide-y rounded-xl border bg-card">
        {runs.map((i) => (
          <RunLine key={seenKey(i)} i={i} />
        ))}
      </ul>
    </Part>
  );
}

/** An ended run: its reason in plain words, its checks and pictures, and what to do about it. */
function RunLine({ i }: { i: QueueItem }): React.JSX.Element {
  const { state, ix, enqueue, down, busy, writes } = useBoard();
  const st = i.state === "done" || i.state === "skipped" ? i.state : "failed";
  const [Ic, word, tone] = ENDED[st];
  const t = ix.byKey.get(i.key);
  const title = itemTitle(i, t);
  const done = i.state === "done";
  const again = canTickAgain(i, ix);
  return (
    <li className="flex gap-3 px-4 py-3">
      <div className="pt-0.5">
        <ToneIcon icon={Ic} tone={tone} label={word} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1">
              <TicketTitle itemKey={i.key} links={i.links} className="line-clamp-2">
                {title}
              </TicketTitle>
            </div>
            <p className="text-xs text-muted-foreground">
              {itemProject(i, t)}
              {i.commit !== null && (
                <>
                  {" · "}
                  <IconGitCommit className="inline size-3.5 align-[-2px]" aria-hidden /> <code className="font-mono">{i.commit.slice(0, 9)}</code>
                </>
              )}
            </p>
          </div>
          <span className="shrink-0 text-xs text-muted-foreground" title={`${word} at ${hm(i.ended ?? 0)}`}>
            {ago(state.now, i.ended)}
          </span>
        </div>
        {!done && <p className={cn("text-sm", i.state === "skipped" ? "text-warn" : "text-destructive")}>{plainReason(i)}</p>}
        <Checks checks={i.checks ?? []} />
        <Pictures item={i} />
        <div className="flex flex-wrap items-center gap-2">
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
              variant={landAgain(i) ? "outline" : "brand"}
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
          <FileLinks item={i} />
        </div>
        {!done && i.note.trim() !== "" && (
          <Fold summary={<span className="text-xs text-muted-foreground">The full reason</span>}>
            <pre className="mt-1 max-h-60 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">{i.note}</pre>
          </Fold>
        )}
      </div>
    </li>
  );
}

/** A failed run whose commit waits in its kept worktree (the hub checks the worktree is there): it could not land, or a check broke. */
const landAgain = (i: QueueItem): boolean => i.kind === "ticket" && i.state === "failed" && Boolean(i.tree) && Boolean(i.commit);

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
    <li className="flex flex-col gap-2 px-4 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-1">
          <TicketTitle itemKey={tkey(t)} links={t.links} className="truncate">
            {t.title}
          </TicketTitle>
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {`${projOf(t.map)} · `}
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
