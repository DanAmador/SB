/**
 * A running worker that looks stuck (ticket 195): an amber dot and the hub's reason, on its run row and its Now card.
 * A click opens the ticket, whose Live block shows what it is doing and takes a steer.
 */
import type * as React from "react";
import type { QueueItem } from "@sb-hub/contract";
import { agentOf, hm, sessionOf } from "@/lib/board.ts";
import { setLink } from "@/lib/link.ts";
import { cn } from "@/lib/utils";
import { useBoard } from "./context.tsx";

export function StuckFlag({ item, className }: { item: QueueItem; className?: string }): React.JSX.Element | null {
  const { state } = useBoard();
  const stuck = item.state === "running" ? (agentOf(state, sessionOf(item))?.stuck ?? null) : null;
  if (stuck === null) return null;
  return (
    <button
      type="button"
      data-testid="stuck"
      title={`Looks stuck since ${hm(stuck.since)}: open its live feed`}
      onClick={() => { setLink({ t: item.key }); }}
      className={cn("relative z-10 flex max-w-full min-w-0 items-center gap-1.5 text-left text-xs text-warn hover:underline focus-visible:underline focus-visible:outline-none", className)}
    >
      <span className="size-2 shrink-0 rounded-full bg-warn" aria-hidden />
      <span className="truncate">{`Stuck: ${stuck.why}`}</span>
    </button>
  );
}
