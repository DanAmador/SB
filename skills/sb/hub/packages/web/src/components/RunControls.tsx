/**
 * What the Run tab lets you set: how many tickets each repo runs at once, which accounts are in tonight's pool, the
 * account and model of a waiting ticket (one, or every ticked one), and the words for why a ticket waits.
 */
import { IconCheck, IconChecklist, IconChevronDown, IconMinus, IconPlus, IconRobot, IconX } from "@tabler/icons-react";
import { useState, useSyncExternalStore } from "react";
import type * as React from "react";
import type { QueueItem } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { say } from "@/lib/notice.ts";
import { hm, itemTitle, mapTitle, plural, poolOf } from "@/lib/board.ts";
import { accountLines, poolWith, repoLines, waitWords, type AccountLine } from "@/lib/night.ts";
import { Store } from "@/lib/store.ts";
import { cn } from "@/lib/utils";
import { SectionTitle } from "./bits.tsx";
import { AccountList } from "./AccountPicker.tsx";
import { useBoard } from "./context.tsx";

const MODELS = ["sonnet", "opus"] as const;

// ---- the ticked waiting rows (the Run tab's own; the table keeps its own ticks) ----

const ticked = new Store<ReadonlySet<string>>(new Set());
const useTicks = (): ReadonlySet<string> => useSyncExternalStore(ticked.subscribe, ticked.get, ticked.get);
const tickRows = (keys: Iterable<string>, on: boolean): void => {
  const next = new Set(ticked.get());
  for (const k of keys) {
    if (on) next.add(k);
    else next.delete(k);
  }
  ticked.set(next);
};
const clearTicks = (): void => {
  ticked.set(new Set());
};

/** The box on a waiting row. */
export function TickBox({ itemKey, title }: { itemKey: string; title: string }): React.JSX.Element {
  const on = useTicks().has(itemKey);
  return (
    <input
      type="checkbox"
      checked={on}
      aria-label={`Pick ${title} for a change of account or model`}
      className="size-4 shrink-0 accent-[var(--brand)]"
      onChange={() => {
        tickRows([itemKey], !on);
      }}
    />
  );
}

// ---- why it waits ----

/** One line of plain words under a waiting row. */
export function WaitReason({ item }: { item: QueueItem }): React.JSX.Element | null {
  const { ix, tickets } = useBoard();
  if (item.waits === undefined) return null;
  const name = (k: string): string => {
    const t = ix.byKey.get(k);
    if (t) return t.title;
    const inMap = tickets?.find((x) => x.map === k);
    return inMap ? mapTitle(inMap) : k;
  };
  return (
    <p data-testid="wait-reason" className="truncate text-xs text-muted-foreground" title={waitWords(item.waits, name)}>
      {waitWords(item.waits, name)}
    </p>
  );
}

// ---- the account and model of a waiting ticket ----

/** Account and model: the menu on one waiting row. */
export function RowMenu({ item, title }: { item: QueueItem; title: string }): React.JSX.Element {
  const { queueWrite, down, busy } = useBoard();
  const [open, setOpen] = useState(false);
  const account = item.agent;
  const model = item.model ?? null;
  const words = `${account ?? "pool"}${model !== null ? ` · ${model}` : ""}`;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="xs"
          disabled={down || busy}
          aria-label={`${words}: the account and model for ${title}`}
          className={cn("h-6 max-w-44 gap-1 px-1.5 font-normal", account !== null || model !== null ? "text-brand" : "text-muted-foreground")}
        >
          <IconRobot aria-hidden />
          <span data-testid="row-agent" className="truncate">{words}</span>
          <IconChevronDown className="size-3!" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(18rem,calc(100vw-1rem))] p-1.5">
        <AgentChoice
          account={account}
          model={model}
          onPick={(b) => {
            setOpen(false);
            void queueWrite("POST /api/queue/item_agent", { key: item.key, ...b }, `${title}: ${b.name !== undefined ? (b.name ?? "tonight's accounts") : (b.model ?? "its own tier")}.`);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

interface Pick { name?: string | null; model?: "sonnet" | "opus" | null }

function AgentChoice({ account, model, onPick }: { account: string | null | undefined; model: string | null | undefined; onPick: (b: Pick) => void }): React.JSX.Element {
  return (
    <div className="flex flex-col gap-1">
      <p className="px-2 pt-1 text-xs text-muted-foreground">Account</p>
      <AccountList chosen={account ?? null} onPick={(name) => { onPick({ name }); }} />
      <p className="px-2 pt-1 text-xs text-muted-foreground">Model</p>
      <ul role="listbox" aria-label="Model" className="flex flex-col gap-0.5">
        {([null, ...MODELS] as const).map((m) => (
          <li key={m ?? ""} role="option" aria-selected={(model ?? null) === m}>
            <button type="button" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent focus-visible:bg-accent" onClick={() => { onPick({ model: m }); }}>
              <IconCheck className={cn("size-4 shrink-0", (model ?? null) === m ? "text-brand" : "invisible")} aria-hidden />
              <span className="font-medium">{m ?? "the ticket's own"}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The bar over the ticked waiting rows: one account and model for all of them. */
export function TickBar({ items }: { items: readonly QueueItem[] }): React.JSX.Element | null {
  const { ix, queueWrite, down, busy } = useBoard();
  const keys = useTicks();
  const [open, setOpen] = useState(false);
  const mine = items.filter((i) => i.state === "queued" && keys.has(i.key));
  if (mine.length === 0) return null;
  const set = async (b: Pick): Promise<void> => {
    let done = 0;
    for (const i of mine) {
      const out = await queueWrite("POST /api/queue/item_agent", { key: i.key, ...b }, `${itemTitle(i, ix.byKey.get(i.key))}: done.`);
      if (!out.ok) break;
      done += 1;
    }
    if (done === mine.length) clearTicks();
  };
  return (
    <div role="region" aria-label="Ticked waiting tickets" data-testid="tick-bar" className="sticky bottom-2 z-20 flex flex-wrap items-center gap-1.5 rounded-xl border bg-card p-3 shadow-lg">
      <span className="mr-1 text-sm font-medium tabular-nums">{`${plural(mine.length, "ticket")} ticked`}</span>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button size="xs" variant="outline" disabled={down || busy}>
            <IconRobot aria-hidden />
            Set account and model
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[min(18rem,calc(100vw-1rem))] p-1.5">
          <AgentChoice
            account={undefined}
            model={undefined}
            onPick={(b) => {
              setOpen(false);
              void set(b);
            }}
          />
        </PopoverContent>
      </Popover>
      <Button size="xs" variant="ghost" className="ml-auto" onClick={clearTicks}>
        <IconX aria-hidden />
        Clear
      </Button>
    </div>
  );
}

// ---- how many run at once, and who is in the pool ----

export function Limits(): React.JSX.Element | null {
  const { state, queueWrite, down, busy } = useBoard();
  const repos = repoLines(state.queue);
  const accounts = accountLines(state);
  if (repos.length === 0 && accounts.length === 0) return null;
  const can = !down && !busy;
  const pool = poolOf(state);
  return (
    <section aria-label="Limits and accounts" className="flex flex-col gap-2">
      <SectionTitle>At once, and on which account</SectionTitle>
      <div className="flex flex-col divide-y rounded-xl border bg-card">
        {repos.map((r) => (
          <div key={r.repo} data-testid="repo-line" data-repo={r.name} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 text-sm">
            <div className="min-w-0 flex-[1_1_14rem]">
              <p className="truncate font-medium">{r.name}</p>
              <p data-testid="repo-words" className="text-xs text-muted-foreground">{r.words}</p>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-1">
              <Button
                variant="outline"
                size="icon-sm"
                disabled={!can || r.atOnce <= 1}
                aria-label={`Run one fewer at once in ${r.name}`}
                onClick={() => {
                  void queueWrite("POST /api/queue/parallel", { repo: r.repo, n: r.atOnce - 1, version: state.queue.version }, `${r.name} runs ${String(r.atOnce - 1)} at once.`);
                }}
              >
                <IconMinus aria-hidden />
              </Button>
              <span className="w-5 text-center tabular-nums" aria-hidden>{r.atOnce}</span>
              <Button
                variant="outline"
                size="icon-sm"
                disabled={!can || r.atOnce >= 8}
                aria-label={`Run one more at once in ${r.name}`}
                onClick={() => {
                  void queueWrite("POST /api/queue/parallel", { repo: r.repo, n: r.atOnce + 1, version: state.queue.version }, `${r.name} runs ${String(r.atOnce + 1)} at once.`);
                }}
              >
                <IconPlus aria-hidden />
              </Button>
            </div>
          </div>
        ))}
        {accounts.map((a) => (
          <AccountRow
            key={a.name}
            a={a}
            now={state.now}
            disabled={!can || (a.inPool && pool.length <= 1)}
            onSwitch={() => {
              const next = poolWith(pool, a.name, !a.inPool);
              if (next !== null) void queueWrite("POST /api/queue/agents", { names: next, version: state.queue.version }, a.inPool ? `${a.name} is out of tonight's accounts.` : `${a.name} is in tonight's accounts.`);
            }}
          />
        ))}
      </div>
    </section>
  );
}

function Bar({ label, pct, resets, now }: { label: string; pct: number | null; resets: number | null; now: number }): React.JSX.Element {
  return (
    <div className="min-w-0 flex-1 basis-28" data-testid={`bar-${label}`}>
      <div className="flex items-baseline justify-between gap-1 text-xs text-muted-foreground">
        <span>{label}</span>
        <span className="tabular-nums">{pct === null ? "no reading" : `${String(pct)}%${resets !== null ? ` · resets ${resets - now > 86400 ? `${new Date(resets * 1000).toLocaleDateString(undefined, { weekday: "short" })} ` : ""}${hm(resets)}` : ""}`}</span>
      </div>
      <div role="progressbar" aria-label={`${label} use`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? 0} className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", (pct ?? 0) >= 85 ? "bg-warn" : "bg-brand")} style={{ width: `${String(Math.min(100, pct ?? 0))}%` }} />
      </div>
    </div>
  );
}

function AccountRow({ a, now, disabled, onSwitch }: { a: AccountLine; now: number; disabled: boolean; onSwitch: () => void }): React.JSX.Element {
  return (
    <div data-testid="account-line" data-account={a.name} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 text-sm">
      <span className="inline-flex min-w-0 flex-[0_0_6rem] items-center gap-1 truncate font-medium">
        <IconRobot className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="truncate">{a.name}</span>
      </span>
      <div className="flex min-w-0 flex-[1_1_14rem] flex-wrap gap-x-4 gap-y-1.5">
        <Bar label="5 hours" pct={a.five} resets={a.fiveResets} now={now} />
        <Bar label="week" pct={a.week} resets={a.weekResets} now={now} />
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={a.inPool}
        aria-label={`${a.name} takes work tonight`}
        title={a.inPool ? "In tonight's accounts" : "Out of tonight's accounts"}
        disabled={disabled}
        onClick={onSwitch}
        className={cn("relative ml-auto inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-50", a.inPool ? "bg-brand" : "bg-muted")}
      >
        <span className={cn("block size-3.5 rounded-full bg-background shadow transition-transform", a.inPool ? "translate-x-4.5" : "translate-x-0.5")} />
      </button>
    </div>
  );
}

// ---- Review finished now ----

/** The finished tickets no review has taken yet, with a button that starts every map's review at once. */
export function ReviewNow(): React.JSX.Element {
  const { state, tickets, writes, down, busy } = useBoard();
  const [pending, setPending] = useState(false);
  const [said, setSaid] = useState("");
  const waiting = state.queue.items.filter((i) => i.kind === "ticket" && i.state === "landed").length;
  const next = state.review_next_at ?? null;
  const off = down || busy || pending || waiting === 0;
  // busy is on for the read-only phone page and chat card
  const nameOf = (map: string): string => {
    const t = tickets?.find((x) => x.map === map);
    return t === undefined ? map : mapTitle(t);
  };
  const press = async (): Promise<void> => {
    setPending(true);
    const out = await writes.reviewNow();
    setPending(false);
    say(out);
    setSaid(!out.ok ? "" : out.started.length === 0 ? "No review started: each map with finished tickets already has one running." : `Review started on ${out.started.map(nameOf).join(", ")}.`);
  };
  return (
    <div data-testid="review-now" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <Button variant="outline" size="sm" disabled={off} onClick={() => { void press(); }}>
        <IconChecklist aria-hidden />
        {waiting === 0 ? "Review finished now" : `Review ${String(waiting)} finished now`}
      </Button>
      <span className="text-muted-foreground">
        {waiting === 0 ? "No finished ticket waits for a review." : next !== null ? `The next timed look is at ${hm(next)}.` : "Finished tickets are reviewed when their map ends."}
      </span>
      {said !== "" && <span>{said}</span>}
    </div>
  );
}
