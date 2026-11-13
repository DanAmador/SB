/**
 * The side panel, a shadcn Sheet: a ticket's place in the queue and what its worker left, then the same actions as
 * the old panel. What the vault already shows (comments, handoffs) opens in Obsidian instead of being copied here.
 */
import { IconArrowBackUp, IconChevronDown, IconChevronUp, IconListNumbers, IconMail, IconNotebook, IconPlayerStop } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import type { TicketAction } from "@sb-hub/contract";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { addable, agentOf, ago, blockerTitles, dur, firstLine, folder, itemMap, itemProject, itemTitle, mapNote, mapTitle, projOf, vaultUri } from "@/lib/board.ts";
import { useTicketDetail } from "@/lib/hub.ts";
import { setLink, useLink } from "@/lib/link.ts";
import { say } from "@/lib/notice.ts";
import { cn } from "@/lib/utils";
import { Checks, FileLinks, Pictures, SelfChecks, StateIcon } from "./bits.tsx";
import { AccountPicker } from "./AccountPicker.tsx";
import { useBoard } from "./context.tsx";

export function DetailSheet(): React.JSX.Element {
  const { t } = useLink();
  const open = t !== "";
  return (
    <Sheet
      open={open}
      onOpenChange={(o) => {
        if (!o) setLink({ t: "" });
      }}
    >
      <SheetContent aria-describedby={undefined} className="overflow-y-auto">
        {t.startsWith("p:") ? <ProjectPanel path={t.slice(2)} /> : open ? <TicketPanel key={t} itemKey={t} /> : null}
      </SheetContent>
    </Sheet>
  );
}

const obsidian = (u: string | undefined): string | null => (u?.startsWith("obsidian://") === true ? u : null);

function ObsidianButton({ href, words, main }: { href: string; words: string; main?: boolean }): React.JSX.Element {
  return (
    <Button asChild size="xs" variant={main === true ? "outline" : "ghost"}>
      <a href={href} title={`Open in Obsidian: ${words.toLowerCase()}`}>
        <IconNotebook aria-hidden />
        {words}
      </a>
    </Button>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function TicketPanel({ itemKey }: { itemKey: string }): React.JSX.Element {
  const { state, ix, qv } = useBoard();
  const detail = useTicketDetail(itemKey);
  const t = ix.byKey.get(itemKey) ?? null;
  const i = state.queue.items.find((x) => x.key === itemKey) ?? (state.queue.cleared ?? []).filter((x) => x.key === itemKey).pop() ?? null;
  const d = detail.data;
  const title = t?.title ?? (i ? itemTitle(i, null) : (d?.title ?? "Ticket"));
  const where = t ? `${projOf(t.map)} · ${mapTitle(t)}` : i ? itemProject(i, null) : "";
  const word = t ? t.state : d?.open === false ? "closed" : "";
  const isJob = i?.kind === "job";
  const after = t ? blockerTitles(t, ix) : [];
  let status = "";
  if (i) {
    if (i.state === "running") {
      const step = agentOf(state, i.key)?.note ?? firstLine(i.note);
      status = `Running on ${i.runner ?? i.agent ?? ""} for ${dur(state.now - (i.started ?? state.now))}${step ? `: ${step}` : ""}`;
    } else if (i.state === "queued") {
      const n = qv.queuedKeys.indexOf(i.key) + 1;
      status = `Queued, number ${n > 0 ? String(n) : "–"} in line${i.agent !== null ? `, on ${i.agent}` : ""}`;
    } else status = `${i.state[0]?.toUpperCase() ?? ""}${i.state.slice(1)} ${ago(state.now, i.ended)}${i.commit !== null ? `, commit ${i.commit.slice(0, 9)}` : ""}`;
  }
  const ticketUri = obsidian(d?.uri) ?? vaultUri(t?.file);
  const mapUri = obsidian(d?.map_uri) ?? vaultUri(t ? mapNote(t.file) : null);
  const board = vaultUri(state.queue.runs?.[t?.map ?? (i?.kind === "ticket" ? (i.map ?? itemMap(i)) : "")]);
  return (
    <>
      <SheetHeader>
        <SheetTitle>{title}</SheetTitle>
        <SheetDescription className="flex flex-wrap items-center gap-2">
          <span>{where}</span>
          {word && <Badge tone={word === "ready" ? "ok" : word === "blocked" ? "warn" : word === "waits for you" ? "brand" : "neutral"}>{word}</Badge>}
        </SheetDescription>
        {(ticketUri !== null || mapUri !== null || board !== null) && (
          <nav aria-label="In Obsidian" className="mt-2 flex flex-wrap gap-1.5">
            {ticketUri !== null && <ObsidianButton href={ticketUri} words="Ticket" main />}
            {mapUri !== null && <ObsidianButton href={mapUri} words="Map" />}
            {board !== null && <ObsidianButton href={board} words="Tonight's run board" />}
          </nav>
        )}
      </SheetHeader>
      <div className="flex flex-col gap-5 px-6 py-5">
        {i && (
          <Block title="In the queue">
            <p className="text-sm">{status}</p>
            {(i.state === "failed" || i.state === "skipped") && <p className="text-sm whitespace-pre-wrap text-destructive">{i.note || "no reason recorded"}</p>}
            <Checks checks={i.checks ?? []} />
            <SelfChecks item={i} />
            <Pictures item={i} full />
            <FileLinks item={i} />
          </Block>
        )}
        {isJob && (
          <Block title="Prompt">
            <p className="text-sm whitespace-pre-wrap">{i.prompt}</p>
          </Block>
        )}
        {t?.why && (
          <Block title="Why">
            <p className="text-sm text-pretty">{t.why}</p>
          </Block>
        )}
        {t?.question && (
          <Block title="Question">
            <p className="text-sm whitespace-pre-wrap">{t.question}</p>
          </Block>
        )}
        {t && (
          <Block title="Done when">
            <p className="text-sm whitespace-pre-wrap">{t.done_when || <span className="text-muted-foreground">not written yet</span>}</p>
          </Block>
        )}
        {after.length > 0 && (
          <Block title="After">
            <p className="text-sm">{after.join(", ")}</p>
          </Block>
        )}
        {t?.checks.length === 0 && <p className="text-sm text-warn">It has no checks, so it cannot be queued until its map has some.</p>}
        {!isJob && <Trail itemKey={itemKey} />}
        <QueueActions itemKey={itemKey} />
        {!isJob && <TicketActions itemKey={itemKey} mapChecks={d?.map_checks ?? null} />}
      </div>
    </>
  );
}

/** The handoff, checkpoint and newest run of its map, and the comment count: each opens in Obsidian. */
function Trail({ itemKey }: { itemKey: string }): React.JSX.Element | null {
  const { state } = useBoard();
  const detail = useTicketDetail(itemKey);
  if (detail.isPending) return <Skeleton className="h-10 w-full" />;
  if (detail.isError) return <p className="text-sm text-destructive">Its details could not be read: {detail.error.message}</p>;
  const d = detail.data;
  const trail = d.trail.filter((x) => obsidian(x.uri) !== null);
  if (trail.length === 0 && d.comments.length === 0) return null;
  return (
    <Block title="In the vault">
      {d.comments.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {d.comments.length === 1 ? "1 comment" : `${String(d.comments.length)} comments`}, newest: “{d.comments.at(-1)?.replace(/^- /, "").slice(0, 160)}”
        </p>
      )}
      <ul className="flex flex-col gap-1">
        {trail.map((x) => (
          <li key={x.path} className="flex items-baseline gap-2 text-sm">
            <a className="text-brand hover:underline" href={obsidian(x.uri) ?? undefined}>
              {x.name}
            </a>
            <span className="text-xs text-muted-foreground">{ago(state.now, x.at)}</span>
          </li>
        ))}
      </ul>
    </Block>
  );
}

function QueueActions({ itemKey }: { itemKey: string }): React.JSX.Element | null {
  const { state, ix, qv, enqueue, unqueue, move, down, busy } = useBoard();
  const t = ix.byKey.get(itemKey);
  const i = state.queue.items.find((x) => x.key === itemKey);
  const off = down || busy;
  if (i?.state === "running") return <RunningActions itemKey={itemKey} />;
  if (i?.kind === "job" || t === undefined) return null;
  const queued = i?.state === "queued";
  const at = qv.queuedKeys.indexOf(itemKey);
  if (!queued && (qv.live.has(itemKey) || !addable(t, ix))) return null;
  return (
    <Block title="Queue">
      <div className="flex flex-wrap items-center gap-2">
        {queued ? (
          <>
            <Button size="sm" variant="outline" disabled={off || at <= 0} onClick={() => void move(itemKey, at - 1)}>
              <IconChevronUp aria-hidden />
              Up
            </Button>
            <Button size="sm" variant="outline" disabled={off || at < 0 || at >= qv.queuedKeys.length - 1} onClick={() => void move(itemKey, at + 1)}>
              <IconChevronDown aria-hidden />
              Down
            </Button>
            <Button size="sm" variant="outline" disabled={off} onClick={() => void unqueue(itemKey)}>
              <IconArrowBackUp aria-hidden />
              Unqueue
            </Button>
            <AccountPicker itemKey={itemKey} chosen={i.agent} title={t.title} />
          </>
        ) : (
          <Button size="sm" variant="brand" disabled={off} onClick={() => void enqueue(itemKey)}>
            <IconListNumbers aria-hidden />
            Queue it
          </Button>
        )}
      </div>
    </Block>
  );
}

/** What the owner says to a worker: stop. The hub has no stop route; the worker reads it after its next tool call. */
const STOP_WORDS = "Stop now, from the owner: start nothing new, commit nothing more, write your report saying where you stopped, and end.";

function RunningActions({ itemKey }: { itemKey: string }): React.JSX.Element {
  const { state, writes, openMessage, down } = useBoard();
  const [sure, setSure] = useState(false);
  const pending = Object.values(state.messages).some((m) => m.to === itemKey && m.text === STOP_WORDS && m.delivered === null && m.lost === undefined);
  return (
    <Block title="Its worker">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={down}
          onClick={() => {
            openMessage(itemKey);
          }}
        >
          <IconMail aria-hidden />
          Message
        </Button>
        {pending ? (
          <span className="text-sm text-muted-foreground">Asked to stop: it reads that after its next tool call.</span>
        ) : sure ? (
          <span role="alert" className="flex flex-wrap items-center gap-2 text-sm">
            Stop this worker?
            <Button
              size="sm"
              variant="destructive"
              autoFocus
              disabled={down}
              onClick={() => {
                setSure(false);
                void writes.send(itemKey, STOP_WORDS).then((out) => {
                  say(out.ok ? { ok: true, words: "Asked to stop: it reads that after its next tool call." } : out);
                });
              }}
            >
              Yes, stop it
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setSure(false);
              }}
            >
              Cancel
            </Button>
          </span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            className="text-destructive"
            disabled={down}
            onClick={() => {
              setSure(true);
            }}
          >
            <IconPlayerStop aria-hidden />
            Stop
          </Button>
        )}
      </div>
    </Block>
  );
}

/** A ticket action: the button that picks it, what the confirmation says, and the yes button. */
const ACTS: Readonly<Record<TicketAction, readonly [string, string, string]>> = {
  comment: ["Comment", "Add this comment", "Yes, add it"],
  done: ["Done", "Mark it done with this line", "Yes, mark it done"],
  drop: ["Drop", "Drop it, out of scope, with this reason", "Yes, drop it"],
  release: ["Release", "Release the claim: it goes back to open", "Yes, release it"],
  tier: ["Tier", "Run it on this tier", "Yes, set it"],
  checks: ["Map checks", "Set its map's checks (every ticket of the map)", "Yes, set them"],
};

function TicketActions({ itemKey, mapChecks }: { itemKey: string; mapChecks: readonly string[] | null }): React.JSX.Element | null {
  const { ix, writes, down } = useBoard();
  const t = ix.byKey.get(itemKey);
  const [action, setAction] = useState<TicketAction | null>(null);
  const [text, setText] = useState("");
  const [commit, setCommit] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const available: TicketAction[] = t ? ["comment", "done", "drop", ...(t.status === "claimed" ? (["release"] as const) : []), "tier", "checks"] : ["comment"];
  const pick = (a: TicketAction): void => {
    setAction(a === action ? null : a);
    setConfirm(false);
    setErr(null);
    setCommit("");
    setText(a === "tier" ? (t?.tier ?? "sonnet") : a === "checks" ? (mapChecks ?? []).join("; ") : "");
  };
  const go = async (): Promise<void> => {
    if (action === null) return;
    setWorking(true);
    const body = action === "release" ? { key: itemKey } : action === "done" && commit.trim() ? { key: itemKey, text: text.trim(), commit: commit.trim() } : { key: itemKey, text: text.trim() };
    const out = await writes.ticket(action, body, `Done: ${ACTS[action][1].toLowerCase()}.`);
    setWorking(false);
    setConfirm(false);
    say(out);
    if (out.ok) setAction(null);
    else setErr(out.words);
  };
  return (
    <Block title="Actions">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Ticket actions">
        {available.map((a) => (
          <Button
            key={a}
            size="xs"
            variant={action === a ? "secondary" : "outline"}
            aria-pressed={action === a}
            disabled={down}
            className={cn(a === "drop" && action !== a && "text-destructive")}
            onClick={() => {
              pick(a);
            }}
          >
            {ACTS[a][0]}
          </Button>
        ))}
      </div>
      {action !== null && (
        <form
          className="mt-2 flex flex-col gap-2 rounded-lg border bg-card p-3"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (action !== "release" && !text.trim()) {
              setErr("Type it first.");
              return;
            }
            setErr(null);
            setConfirm(true);
          }}
        >
          {action === "comment" && (
            <Label>
              Comment, added under the ticket's Comments with today's date
              <Textarea value={text} maxLength={4000} onChange={(ev) => { setText(ev.currentTarget.value); }} />
            </Label>
          )}
          {action === "done" && (
            <>
              <Label>
                What was done, in one line
                <Input value={text} maxLength={300} placeholder="e.g. fixed by hand in the editor" onChange={(ev) => { setText(ev.currentTarget.value); }} />
              </Label>
              <Label>
                Its commit, optional
                <Input value={commit} maxLength={40} onChange={(ev) => { setCommit(ev.currentTarget.value); }} />
              </Label>
            </>
          )}
          {action === "drop" && (
            <Label>
              Why it is out of scope
              <Input value={text} maxLength={300} placeholder="e.g. replaced by another ticket" onChange={(ev) => { setText(ev.currentTarget.value); }} />
            </Label>
          )}
          {action === "release" && <p className="text-sm text-muted-foreground">{t?.reason ?? "claimed"}</p>}
          {action === "tier" && (
            <Label>
              The model it runs on
              <Select value={text} onChange={(ev) => { setText(ev.currentTarget.value); }}>
                <option value="sonnet">sonnet</option>
                <option value="opus">opus</option>
              </Select>
            </Label>
          )}
          {action === "checks" && (
            <Label>
              Checks of its map, separated by ;
              <Input value={text} maxLength={2000} placeholder="e.g. pnpm typecheck; pnpm test" onChange={(ev) => { setText(ev.currentTarget.value); }} />
            </Label>
          )}
          {err !== null && (
            <p role="alert" className="text-sm text-destructive">
              {err}
            </p>
          )}
          {confirm ? (
            <div role="alert" className="flex flex-col gap-2 rounded-md bg-warn-soft p-2.5 text-sm">
              <span>
                {ACTS[action][1]}
                {text.trim() && action !== "release" ? `: “${text.trim()}”` : ""}
                {commit.trim() ? `, commit ${commit.trim()}` : ""}?
              </span>
              <div className="flex gap-2">
                <Button type="button" size="xs" variant={action === "drop" ? "destructive" : "default"} disabled={working || down} autoFocus onClick={() => void go()}>
                  {working ? "Working…" : ACTS[action][2]}
                </Button>
                <Button type="button" size="xs" variant="ghost" disabled={working} onClick={() => { setConfirm(false); }}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <Button type="submit" size="xs" variant={action === "drop" ? "destructive" : "default"} disabled={down}>
                {ACTS[action][0]}…
              </Button>
            </div>
          )}
        </form>
      )}
    </Block>
  );
}

/** A project's repo, Unity and provider widgets, and its sessions. */
function ProjectPanel({ path }: { path: string }): React.JSX.Element {
  const { state, agents } = useBoard();
  const panels = state.providers[path] ?? [];
  const sessions = agents.sessions.filter((a) => a.project === path);
  return (
    <>
      <SheetHeader>
        <SheetTitle>{folder(path) || "No project"}</SheetTitle>
        <SheetDescription className="font-mono text-xs break-all">{path}</SheetDescription>
      </SheetHeader>
      <div className="flex flex-col gap-5 px-6 py-5">
        {panels.length === 0 && <p className="text-sm text-muted-foreground">No repo, Unity or provider widgets for it yet.</p>}
        {panels.map((p) => (
          <Block key={p.title} title={p.title}>
            <ul className="flex flex-col gap-1.5">
              {p.widgets.map((w, n) => {
                const ww = w as { kind?: string; label?: string; value?: unknown; level?: unknown; lines?: unknown };
                if (ww.kind === "log" && Array.isArray(ww.lines)) {
                  return (
                    <li key={n}>
                      <p className="text-xs text-muted-foreground">{ww.label}</p>
                      <pre className="max-h-48 overflow-auto rounded-md bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">{ww.lines.map(String).join("\n")}</pre>
                    </li>
                  );
                }
                const tone = ww.level === "bad" ? "bg-destructive" : ww.level === "warn" ? "bg-warn" : ww.level === "ok" ? "bg-ok" : "bg-muted-foreground";
                return (
                  <li key={n} className="flex items-center gap-2 text-sm">
                    <span className={cn("size-2 shrink-0 rounded-full", tone)} aria-hidden />
                    <span className="text-muted-foreground">{ww.label}</span>
                    <span className="ml-auto truncate">{typeof ww.value === "string" || typeof ww.value === "number" ? String(ww.value) : ""}</span>
                  </li>
                );
              })}
            </ul>
          </Block>
        ))}
        {sessions.length > 0 && (
          <Block title="Its sessions">
            <ul className="flex flex-col gap-1">
              {sessions.map((a) => (
                <li key={a.agent} className="flex items-center gap-2 text-sm">
                  <StateIcon state={a.state} />
                  {a.title ?? a.name ?? a.agent.slice(0, 6)}
                </li>
              ))}
            </ul>
          </Block>
        )}
      </div>
    </>
  );
}
