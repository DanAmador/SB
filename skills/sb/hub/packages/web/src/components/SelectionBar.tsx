/**
 * The bar over the ticked tickets: Queue, Unqueue, Drop, Mark done, Set tier, Comment. Each button says how many of
 * the ticked it applies to and how many it skips. Drop, Mark done, Set tier and Comment ask once for their line and
 * confirm with the count. Queue and Unqueue are one queue write; the rest go one ticket after the other, and a failure
 * is named by its title.
 */
import { IconX } from "@tabler/icons-react";
import { useState } from "react";
import type * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { plural, withBlockers, type TableRow } from "@/lib/board.ts";
import { say } from "@/lib/notice.ts";
import { ACTS, ACT_WORDS, clearSelection, split, tick, useSelection, type Act } from "@/lib/select.ts";
import { cn } from "@/lib/utils";
import { useBoard } from "./context.tsx";

const TIERS = ["sonnet", "opus"] as const;
/** What each asking action wants typed, and its confirm button's verb. */
const ASK: Readonly<Record<"drop" | "done" | "tier" | "comment", readonly [string, string]>> = {
  drop: ["Reason for dropping", "Drop"],
  done: ["What was done", "Mark done"],
  tier: ["Tier", "Set the tier of"],
  comment: ["Comment", "Comment on"],
};
const PAST: Readonly<Record<Act, string>> = { queue: "Queued", unqueue: "Unqueued", drop: "Dropped", done: "Marked done", tier: "Set the tier of", comment: "Commented on", };

export function SelectionBar({ rows }: { rows: readonly TableRow[] }): React.JSX.Element | null {
  const { ix, qv, state, writes, queueWrite, down, busy } = useBoard();
  const keys = useSelection();
  const [ask, setAsk] = useState<keyof typeof ASK | null>(null);
  const [text, setText] = useState("");
  const [tier, setTier] = useState<string>("sonnet");
  const ticked = rows.filter((r) => keys.has(r.key));
  if (ticked.length === 0) return null;
  const off = down || busy;
  const skipWords = (n: number): string => (n > 0 ? `, skipped ${String(n)}` : "");

  const queue = async (act: "queue" | "unqueue"): Promise<void> => {
    const { apply, skip } = split(act, ticked);
    const now = [...qv.queuedKeys];
    const gone = new Set(apply.map((r) => r.key));
    let next: string[];
    if (act === "unqueue") next = now.filter((k) => !gone.has(k));
    else {
      next = now;
      for (const r of apply) for (const k of withBlockers(r.key, ix)) if (!next.includes(k)) next = [...next, k];
    }
    const out = await queueWrite("POST /api/queue/set", { keys: next, version: state.queue.version }, `${PAST[act]} ${plural(apply.length, "ticket")}${skipWords(skip.length)}.`);
    if (out.ok) tick(apply.map((r) => r.key), false);
  };

  const each = async (act: "drop" | "done" | "tier" | "comment"): Promise<void> => {
    const { apply, skip } = split(act, ticked);
    const line = act === "tier" ? tier : text.trim();
    if (line === "") return;
    // every change is drawn at once and the bar clears; the hub takes them one by one, and what it refuses is ticked again
    const asked = ask;
    tick(apply.map((r) => r.key), false);
    setAsk(null);
    setText("");
    const outs = await Promise.all(apply.map((r) => writes.ticket(act, { key: r.key, text: line }, "")));
    const failed = apply.filter((_, n) => !outs[n]?.ok);
    tick(failed.map((r) => r.key), true);
    if (failed.length > 0) {
      setAsk(asked);
      if (act !== "tier") setText(line);
    }
    if (failed.length === 0) say({ ok: true, words: `${PAST[act]} ${plural(apply.length, "ticket")}${skipWords(skip.length)}.` });
    else {
      const why = failed.map((r) => `${r.title} (${outs[apply.indexOf(r)]?.words ?? ""})`);
      say({ ok: false, words: `${PAST[act]} ${String(apply.length - failed.length)} of ${String(apply.length)}. Failed: ${why.join("; ")}` });
    }
  };

  const press = (act: Act): void => {
    if (act === "queue" || act === "unqueue") void queue(act);
    else {
      setAsk(ask === act ? null : act);
      setText("");
    }
  };
  const asked = ask === null ? null : split(ask, ticked);
  return (
    <div role="region" aria-label="Ticked tickets" data-testid="selection-bar" className="sticky bottom-2 z-20 flex flex-col gap-2 rounded-xl border bg-card p-3 shadow-lg">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-sm font-medium tabular-nums">{plural(ticked.length, "ticket")} ticked</span>
        {ACTS.map((a) => {
          const { apply, skip } = split(a, ticked);
          return (
            <Button
              key={a}
              size="xs"
              variant={ask === a ? "secondary" : "outline"}
              disabled={off || apply.length === 0}
              aria-pressed={a === "queue" || a === "unqueue" ? undefined : ask === a}
              className={cn(a === "drop" && ask !== a && "text-destructive")}
              onClick={() => {
                press(a);
              }}
            >
              {ACT_WORDS[a]}
              <span className="tabular-nums">{apply.length}</span>
              {skip.length > 0 && <span className="font-normal text-muted-foreground">skips {skip.length}</span>}
            </Button>
          );
        })}
        <Button size="xs" variant="ghost" className="ml-auto" onClick={clearSelection}>
          <IconX aria-hidden />
          Clear
        </Button>
      </div>
      {ask !== null && asked !== null && (
        <form
          className="flex flex-col gap-2 sm:flex-row sm:items-center"
          onSubmit={(ev) => {
            ev.preventDefault();
            void each(ask);
          }}
        >
          {ask === "tier" ? (
            <select aria-label="Tier" value={tier} onChange={(e) => { setTier(e.currentTarget.value); }} className="h-8 rounded-md border bg-background px-2 text-sm">
              {TIERS.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          ) : (
            <Input aria-label={ASK[ask][0]} placeholder={`${ASK[ask][0]}: one line, for every ticket`} className="h-8 min-w-0 flex-1" maxLength={500} value={text} onChange={(e) => { setText(e.currentTarget.value); }} autoFocus />
          )}
          <Button type="submit" size="xs" disabled={off || (ask !== "tier" && text.trim() === "")} variant={ask === "drop" ? "destructive" : "default"}>
            {`${ASK[ask][1]} ${plural(asked.apply.length, "ticket")}`}
          </Button>
          <Button type="button" size="xs" variant="ghost" onClick={() => { setAsk(null); }}>
            Cancel
          </Button>
        </form>
      )}
    </div>
  );
}
