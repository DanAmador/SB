/** The board: the header with the views and the toolbar, what needs you, one view at a time, the panel and the dialogs. */
import { IconAlertTriangle, IconCircleCheck, IconCircleX, IconWifiOff } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import type * as React from "react";
import type { RouteBody, State } from "@sb-hub/contract";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { itemInScope, plural, projOf, queueView, scopeItems, scopeWaits, sidebarTree, splitAgents, ticketIndex, waitsFor, withBlockers } from "@/lib/board.ts";
import { sessionCards } from "@/lib/sessions.ts";
import { READONLY } from "@/lib/api.ts";
import { useHubState, useTickets, useWrites, type Outcome } from "@/lib/hub.ts";
import { setLink, useLink, VIEWS, type View } from "@/lib/link.ts";
import { say, useNotices } from "@/lib/notice.ts";
import { cn } from "@/lib/utils";
import { CommandMenu, JobDialog, MessageDialog, type Dialogs } from "./CommandMenu.tsx";
import { BoardContext, type BoardData } from "./context.tsx";
import { Breadcrumb, MenuButton, SidebarColumn, SidebarSheet } from "./Sidebar.tsx";
import { HistoryView } from "./HistoryView.tsx";
import { QueueView } from "./QueueView.tsx";
import { SessionsView } from "./SessionsView.tsx";
import { RunsView } from "./RunsView.tsx";
import { DetailSheet } from "./TicketSheet.tsx";
import { Toolbar } from "./Toolbar.tsx";
import { WaitsView } from "./WaitsView.tsx";

/** The list rows of the view on screen, in reading order. */
const rows = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>("main [role=tabpanel]:not([hidden]) li")].filter((li) => li.querySelector("a, button") !== null && li.closest("details:not([open])") === null);

/** j and k: move the row cursor; it is real focus, so the page scrolls to it and the ring shows. */
function stepRow(by: 1 | -1): void {
  const list = rows();
  if (list.length === 0) return;
  const now = list.findIndex((li) => li === document.activeElement || li.contains(document.activeElement));
  const next = list[Math.min(list.length - 1, Math.max(0, now < 0 ? (by === 1 ? 0 : list.length - 1) : now + by))];
  if (!next) return;
  next.tabIndex = -1;
  next.focus();
  next.scrollIntoView({ block: "nearest" });
}

/** Enter on a focused row opens its panel (the Show details button), else its first link or button. */
function openRow(el: HTMLElement | null): void {
  const li = el?.closest("li") ?? null;
  if (li === null || el !== li) return;
  const go = li.querySelector<HTMLElement>("button[aria-label='Show details']") ?? li.querySelector<HTMLElement>("a, button");
  go?.click();
}

const VIEW_WORDS: Readonly<Record<View, string>> = { runs: "Runs", queue: "Queue", waits: "Waits for you", sessions: "Sessions", history: "History" };

export function Board(): React.JSX.Element {
  const stateQ = useHubState();
  const ticketsQ = useTickets();
  const state = stateQ.data;
  const down = stateQ.isError;
  if (state === undefined) {
    return down ? <Offline first /> : <BoardSkeleton />;
  }
  return <Loaded state={state} tickets={ticketsQ.data ?? null} down={down} lastOk={stateQ.dataUpdatedAt} />;
}

function Loaded({ state, tickets, down, lastOk }: { state: State; tickets: BoardData["tickets"]; down: boolean; lastOk: number }): React.JSX.Element {
  const link = useLink();
  const writes = useWrites();
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<Dialogs>({ kind: "none" });
  const [menu, setMenu] = useState(false);
  const scope = { project: link.project || projOf(link.map), map: link.map };

  const agents = splitAgents(state);
  const qv = queueView(state);
  const ix = ticketIndex(tickets ?? [], state);
  const allWaits = waitsFor(state, tickets, ix, new Set(state.seen));
  const tree = sidebarTree(state, tickets, allWaits);
  const waits = scopeWaits(allWaits, scope, state);
  const alerts = waits.count;
  const sessions = sessionCards(state, ix, agents).filter((c) => !c.idle);
  const counts: Readonly<Record<View, number>> = {
    runs: qv.running.filter((i) => itemInScope(scope, i)).length,
    queue: scopeItems(scope, qv.next).length,
    waits: alerts,
    sessions: sessions.length,
    history: 0,
  };

  const queueWrite: BoardData["queueWrite"] = async (route, body, done) => {
    setBusy(true);
    const out = await writes.queue(route, body, done);
    setBusy(false);
    say(out);
    return out;
  };
  const setKeys = (keys: string[], done: string): Promise<Outcome> =>
    queueWrite("POST /api/queue/set", { keys, version: state.queue.version } satisfies RouteBody<"POST /api/queue/set">, done);
  const data: BoardData = {
    state,
    scope,
    tickets,
    ix,
    qv,
    agents,
    writes,
    down,
    // a read-only page (the phone, the chat widget) has every control off, as when a change is in flight
    busy: busy || READONLY,
    queueWrite,
    async enqueue(key, at) {
      const keys = [...qv.queuedKeys];
      const add = withBlockers(key, ix).filter((k) => !keys.includes(k));
      const words = add.length > 1 ? `Queued with ${plural(add.length - 1, "ticket")} it waits on.` : "Queued.";
      if (at === undefined) {
        await setKeys([...keys, ...add], words);
        return;
      }
      // dropped at a place: the blockers go just before it, so the order stays runnable
      const before = add.slice(0, -1);
      const rest = keys.slice(at);
      await setKeys([...keys.slice(0, at), ...before, key, ...rest], words);
    },
    async unqueue(key) {
      await setKeys(
        qv.queuedKeys.filter((k) => k !== key),
        "Unqueued: back with the open tickets.",
      );
    },
    async move(key, to) {
      await queueWrite("POST /api/queue/move", { key, to, version: state.queue.version }, "Moved.");
    },
    openMessage(to) {
      setDialog({ kind: "message", to });
    },
  };

  useEffect(() => {
    document.title = allWaits.count > 0 ? `(${String(allWaits.count)}) sb hub` : "sb hub";
  }, [allWaits.count]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent): void => {
      const el = ev.target as HTMLElement | null;
      const typing = el !== null && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        setDialog((d) => (d.kind === "command" ? { kind: "none" } : { kind: "command" }));
      } else if (typing || ev.metaKey || ev.ctrlKey || ev.altKey || document.querySelector("[role=dialog]")) {
        return;
      } else if (ev.key === "/") {
        const find = document.querySelector<HTMLInputElement>("input[data-find]");
        if (find) {
          ev.preventDefault();
          find.focus();
        }
      } else if (ev.key >= "1" && ev.key <= "5") {
        const view = VIEWS[Number(ev.key) - 1];
        if (view) setLink({ view });
      } else if (ev.key === "j" || ev.key === "k") {
        stepRow(ev.key === "j" ? 1 : -1);
      } else if (ev.key === "Enter") {
        openRow(el);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const close = (): void => {
    setDialog({ kind: "none" });
  };
  return (
    <BoardContext value={data}>
      <Tabs
        value={link.view}
        onValueChange={(v) => {
          const view = VIEWS.find((x) => x === v);
          if (view) setLink({ view });
        }}
        className="min-h-dvh"
      >
        <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
          <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5 sm:px-6">
            <div className="flex items-center gap-2">
              <MenuButton onClick={() => { setMenu(true); }} />
              <span className="text-sm font-semibold tracking-tight">sb hub</span>
              {READONLY && <span className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">read-only</span>}
              <span
                className={cn("size-2 rounded-full", down ? "bg-muted-foreground" : "bg-ok")}
                role="img"
                aria-label={down ? "offline" : "live"}
                title={down ? "offline" : "live"}
              />
            </div>
            <TabsList aria-label="Views" className="order-3 w-full sm:order-none sm:w-auto">
              {VIEWS.map((v) => (
                <TabsTrigger key={v} value={v}>
                  {VIEW_WORDS[v]}
                  {v === "waits" ? (
                    alerts > 0 && (
                      <span className="min-w-5 rounded-full bg-destructive px-1.5 text-xs leading-5 font-medium text-white tabular-nums" aria-label={`${String(alerts)} waiting`}>
                        {alerts}
                      </span>
                    )
                  ) : (
                    counts[v] > 0 && <span className="text-xs text-muted-foreground tabular-nums">{counts[v]}</span>
                  )}
                </TabsTrigger>
              ))}
            </TabsList>
            <div className="ml-auto">
              <Toolbar
                view={link.view}
                onCommand={() => {
                  setDialog({ kind: "command" });
                }}
              />
            </div>
          </div>
        </header>
        <div className="mx-auto flex max-w-[1600px]">
        <SidebarColumn tree={tree} scope={scope} />
        <main className={cn("flex min-w-0 flex-1 flex-col gap-6 px-4 py-5 sm:px-6", down && "opacity-60")}>
          <Breadcrumb scope={scope} />
          {down && <Offline lastOk={lastOk} />}
          {state.queue_lock?.mine === false && (
            <div role="alert" className="flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn">
              <IconAlertTriangle className="size-4 shrink-0" aria-hidden />
              This hub is read-only: {state.queue_lock.holder} holds the queue lock and runs the queue, not the server answering here.
            </div>
          )}
          <TabsContent value="runs" className="outline-none">
            <RunsView />
          </TabsContent>
          <TabsContent value="queue" className="outline-none">
            <QueueView />
          </TabsContent>
          <TabsContent value="waits" className="outline-none">
            <WaitsView w={waits} />
          </TabsContent>
          <TabsContent value="sessions" className="outline-none">
            <SessionsView />
          </TabsContent>
          <TabsContent value="history" className="outline-none">
            <HistoryView />
          </TabsContent>
        </main>
        </div>
      </Tabs>
      <SidebarSheet tree={tree} scope={scope} open={menu} onOpenChange={setMenu} />
      <DetailSheet />
      <CommandMenu open={dialog.kind === "command"} onClose={close} go={setDialog} tree={tree} />
      <JobDialog open={dialog.kind === "job"} onClose={close} />
      {dialog.kind === "message" && <MessageDialog key={dialog.to} to={dialog.to} onClose={close} />}
      <Notices />
    </BoardContext>
  );
}

function Offline({ first, lastOk }: { first?: boolean; lastOk?: number }): React.JSX.Element {
  const at = lastOk !== undefined && lastOk > 0 ? new Date(lastOk).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  return (
    <div role="alert" className={cn("flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn", first === true && "m-6")}>
      <IconWifiOff className="size-4 shrink-0" aria-hidden />
      {first === true ? "The hub is not answering. The board appears once it does." : `The hub is not answering. Showing the board as it was at ${at}; every change waits until it is back.`}
    </div>
  );
}

function BoardSkeleton(): React.JSX.Element {
  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-6 px-6 py-4" aria-busy="true" aria-label="Loading the board">
      <div className="flex items-center gap-4">
        <Skeleton className="h-5 w-16" />
        <Skeleton className="h-9 w-64" />
        <Skeleton className="ml-auto h-8 w-72" />
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        {[0, 1, 2].map((n) => (
          <div key={n} className="flex flex-col gap-2">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

function Notices(): React.JSX.Element {
  const notices = useNotices();
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4">
      {notices.map((n) => (
        <div
          key={n.id}
          role={n.ok ? "status" : "alert"}
          className="pointer-events-auto flex max-w-md items-center gap-2 rounded-lg border bg-popover px-3 py-2 text-sm shadow-lg animate-in fade-in-0 slide-in-from-bottom-2"
        >
          {n.ok ? <IconCircleCheck className="size-4 shrink-0 text-ok" aria-hidden /> : <IconCircleX className="size-4 shrink-0 text-destructive" aria-hidden />}
          {n.words}
        </div>
      ))}
    </div>
  );
}
