/** A question a session asked, answered with one click before its default applies. */
import { IconCheck, IconClock, IconHelpCircle } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import type * as React from "react";
import type { Question } from "@sb-hub/contract";
import { Button } from "@/components/ui/button";
import { agentLabel, agentOf, dur, folder } from "@/lib/board.ts";
import { say } from "@/lib/notice.ts";
import { cn } from "@/lib/utils";
import { ToneIcon } from "./bits.tsx";
import { IconNotebook } from "@tabler/icons-react";
import { useBoard } from "./context.tsx";

/** The clock, once a second: question countdowns move between polls. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => {
      setNow(Date.now() / 1000);
    }, 1000);
    return () => {
      clearInterval(t);
    };
  }, []);
  return now;
}

export function QuestionCard({ id, q }: { id: string; q: Question }): React.JSX.Element {
  const { state, ix, writes, down } = useBoard();
  const now = useNow();
  const [sending, setSending] = useState<string | null>(null);
  const decided = q.answer !== null;
  const left = q.deadline - now;
  const pending = !decided && left <= 0;
  const asker = agentOf(state, q.agent);
  const ticket = ix.byKey.get(asker?.agent ?? q.agent) ?? ix.byKey.get(q.agent);
  const off = decided || pending || down || sending !== null;
  const choose = async (o: string): Promise<void> => {
    setSending(o);
    const out = await writes.answer(id, o);
    setSending(null);
    if (!out.ok) say(out);
  };
  return (
    <article
      aria-label={`Question from ${asker ? agentLabel(asker) : q.agent}`}
      className={cn("flex flex-col gap-2 rounded-lg border bg-card p-3", decided ? "opacity-70" : "border-brand/40 shadow-sm")}
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <ToneIcon icon={IconHelpCircle} tone="brand" label="question" />
        <span className="truncate font-medium text-foreground">{asker ? agentLabel(asker) : q.agent.slice(0, 6)}</span>
        {asker?.project !== undefined && <span className="truncate">· {folder(asker.project)}</span>}
        {ticket?.links.ticket != null && (
          <a href={ticket.links.ticket} aria-label="Open its ticket in Obsidian" title="Open its ticket in Obsidian" className="-my-1.5 inline-flex size-6 shrink-0 items-center justify-center rounded-md hover:bg-accent hover:text-foreground">
            <IconNotebook className="size-4" aria-hidden />
          </a>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-1">
          {decided ? (
            q.by === "default" ? "default applied" : q.by === "you" ? "you chose" : `chosen by ${q.by ?? ""}`
          ) : pending ? (
            <span className="text-warn">deciding…</span>
          ) : (
            <span className={cn("flex items-center gap-1", left < 60 && "font-medium text-warn")} title="the default applies then">
              <IconClock className="size-3.5" aria-hidden />
              {dur(left)} left
            </span>
          )}
        </span>
      </div>
      <p className="text-sm leading-snug text-pretty">{q.q}</p>
      <div className="flex flex-wrap gap-1.5">
        {q.options.map((o) => {
          const chosen = decided && o === q.answer;
          return (
            <Button
              key={o}
              size="xs"
              variant={chosen ? "secondary" : o === q.default ? "default" : "outline"}
              disabled={off}
              className={cn("h-auto min-h-7 py-1 whitespace-normal text-left", chosen && "opacity-100")}
              onClick={() => {
                void choose(o);
              }}
            >
              {chosen && <IconCheck aria-hidden />}
              {sending === o ? "Sending…" : o}
              {o === q.default && <span className="font-normal opacity-70">· default</span>}
            </Button>
          );
        })}
      </div>
    </article>
  );
}
