/**
 * Waits for you: questions first, then failed runs (reason, checks, pictures, Run again), then done runs (checks,
 * pictures, Looks good), then tickets that wait for a decision, then accounts and widgets in trouble.
 */
import { IconAlertTriangle, IconBan, IconCheck, IconCircleCheck, IconGitCommit, IconLock, IconRefresh, IconX } from "@tabler/icons-react";
import type * as React from "react";
import type { QueueItem, TicketRow } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { scopeItems, ago, canTickAgain, folder, hm, itemProject, itemTitle, mapTitle, plainReason, plural, projOf, seenKey, tkey, type Waits } from "@/lib/board.ts";
import { cn } from "@/lib/utils";
import { markSeen } from "@/lib/seen.ts";
import { QuestionCard } from "./QuestionCard.tsx";
import { Checks, Empty, FileLinks, Fold, MapName, Pictures, SectionTitle, TicketTitle, ToneIcon } from "./bits.tsx";
import { useBoard } from "./context.tsx";

export function WaitsView({ w }: { w: Waits }): React.JSX.Element {
  const { state, qv, scope, queueWrite, down, busy } = useBoard();
  const clear =
    qv.done.length + qv.failed.length > 0 ? (
      <Button
        variant="ghost"
        size="xs"
        disabled={down || busy}
        title="Takes done, failed and skipped runs off the queue's list; they stay in the vault"
        onClick={() => {
          void queueWrite("POST /api/queue/clear-finished", { version: state.queue.version }, "Ended runs cleared from the list; they stay in the vault.");
        }}
      >
        Clear finished
      </Button>
    ) : undefined;
  const nothing = w.questions.length + w.failed.length + w.done.length + w.tickets.length + w.signedOut.length + w.badWidgets.length === 0;
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
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
      <Ended title="Failed" id="failed" now={w.failed} old={scopeItems(scope, qv.failedCleared)} clear={clear} />
      <Ended title="Done" id="done" now={w.done} old={scopeItems(scope, qv.doneCleared)} clear={w.failed.length === 0 ? clear : undefined} />
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

/** Failed or Done: the runs to look at, then the ones cleared from the list, folded. */
function Ended({ title, id, now, old, clear }: { title: string; id: string; now: readonly QueueItem[]; old: readonly QueueItem[]; clear: React.ReactNode }): React.JSX.Element | null {
  if (now.length === 0 && old.length === 0) return null;
  return (
    <Part id={id} title={title} aside={now.length > 0 ? clear : undefined}>
      {now.length > 0 && (
        <ul className="flex flex-col divide-y rounded-xl border bg-card">
          {now.map((i) => (
            <RunLine key={seenKey(i)} i={i} />
          ))}
        </ul>
      )}
      {old.length > 0 && (
        <Fold summary={<span className="text-muted-foreground">{`${plural(old.length, "earlier one")}, cleared from the list`}</span>}>
          <ul className="mt-1 flex flex-col divide-y rounded-xl border bg-card">
            {old.map((i) => (
              <RunLine key={`old-${seenKey(i)}`} i={i} cleared />
            ))}
          </ul>
        </Fold>
      )}
    </Part>
  );
}

/** An ended run: its reason in plain words, its checks and pictures, and what to do about it. */
function RunLine({ i, cleared }: { i: QueueItem; cleared?: boolean }): React.JSX.Element {
  const { state, ix, enqueue, down, busy } = useBoard();
  const st = i.state === "done" || i.state === "skipped" ? i.state : "failed";
  const [Ic, word, tone] = ENDED[st];
  const t = ix.byKey.get(i.key);
  const title = itemTitle(i, t);
  const done = i.state === "done";
  const again = canTickAgain(i, ix);
  const old = cleared === true;
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
        {!old && <Checks checks={i.checks ?? []} />}
        {!old && <Pictures item={i} />}
        <div className="flex flex-wrap items-center gap-2">
          {done && !old && (
            <Button
              size="xs"
              variant="outline"
              onClick={() => {
                markSeen(seenKey(i));
              }}
            >
              <IconCheck aria-hidden />
              Looks good
            </Button>
          )}
          {!done && again && (
            <Button
              size="xs"
              variant="brand"
              disabled={down || busy}
              onClick={() => {
                void enqueue(i.key);
              }}
            >
              <IconRefresh aria-hidden />
              Run again
            </Button>
          )}
          {!done && !old && (
            <Button
              size="xs"
              variant="ghost"
              title="Take it off this list in this browser; the queue and the vault keep it"
              onClick={() => {
                markSeen(seenKey(i));
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

function DecideLine({ t }: { t: TicketRow }): React.JSX.Element {
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <div className="min-w-0 flex-1">
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
    </li>
  );
}
