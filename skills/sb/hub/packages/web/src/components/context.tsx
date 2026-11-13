/** What every part of the board reads: the hub's state, the open tickets, the grouping rules' answers and the writes. */
import { createContext, use } from "react";
import type { RouteBody, State, TicketRow } from "@sb-hub/contract";
import type { Agents, TicketIndex, QueueView } from "@/lib/board.ts";
import type { Outcome, Writes } from "@/lib/hub.ts";

type QueueRoute = Parameters<Writes["queue"]>[0];

export interface BoardData {
  readonly state: State;
  /** null while the maps are being read. */
  readonly tickets: readonly TicketRow[] | null;
  readonly ix: TicketIndex;
  readonly qv: QueueView;
  readonly agents: Agents;
  readonly writes: Writes;
  /** The hub did not answer the last poll: every write is off. */
  readonly down: boolean;
  /** A queue write is in flight: the queue's controls wait for it. */
  readonly busy: boolean;
  /** One queue write, with the queue's version where the hub checks it; its outcome is said. */
  readonly queueWrite: <K extends QueueRoute>(route: K, body: RouteBody<K>, done: string) => Promise<Outcome>;
  /** Queue a ticket with the open tickets it waits on, optionally at a place in the list. */
  readonly enqueue: (key: string, at?: number) => Promise<void>;
  readonly unqueue: (key: string) => Promise<void>;
  readonly move: (key: string, to: number) => Promise<void>;
  readonly openMessage: (to: string) => void;
}

export const BoardContext = createContext<BoardData | null>(null);

export function useBoard(): BoardData {
  const b = use(BoardContext);
  if (b === null) throw new Error("useBoard outside the board");
  return b;
}
