/**
 * Sessions: a hub trail (the last 40 actions of one agent) made into lot-map's board, the cards' order and the
 * rules for the two flags. The drawing itself is lot-map's, vendored under vendor/lot-map.
 */
import type { AgentRow, State, Trail, TrailAction } from "@sb-hub/contract";
import { classify, clean } from "@/vendor/lot-map/classify.ts";
import { drawMap } from "@/vendor/lot-map/draw.ts";
import { setupFrom } from "@/vendor/lot-map/setup.ts";
import type { Board, Entry, StationId } from "@/vendor/lot-map/types.ts";
import type { Links } from "@sb-hub/contract";
import { agentLabel, itemTitle, rank, SILENT, splitAgents, type Agents, type TicketIndex } from "./board.ts";

export { STATIONS } from "@/vendor/lot-map/setup.ts";

/** A session is idle once its last event is this old, or it says so: its card greys and goes last. */
export const IDLE = 1800;
/** The panel lists this many of the last actions. */
export const FEED_ROWS = 16;

const SETUP = { light: setupFrom({ theme: "light", background: "transparent" }), dark: setupFrom({ theme: "dark", background: "transparent" }) } as const;

/** What the hub's trail keeps of a tool call is its name and a label, not the input: put the label where lot-map reads it. */
function inputOf(tool: string, label: string): Record<string, unknown> {
  switch (tool) {
    case "Read":
    case "Write":
    case "Edit":
    case "NotebookEdit":
      return { file_path: label };
    case "WebFetch":
      return { url: label };
    case "Skill":
      return { skill: label };
    default:
      return { description: label, command: label };
  }
}

/** One trail action as a lot-map entry; a prompt is a signal from you, a subagent's run belongs to the agents station. */
export function entryOf(a: TrailAction, i: number): Entry {
  const status = a.end === null ? "run" : a.ok === false ? "err" : "ok";
  const base = { id: String(i), startedAt: a.start * 1000, status } as const;
  const end = a.end === null ? {} : { endedAt: a.end * 1000 };
  if (a.sub) return { ...base, ...end, station: "agents", label: clean(a.label || a.tool), from: "core", agentId: a.tool };
  if (a.tool === "prompt") return { ...base, ...end, station: "you", label: clean(a.label || "prompt"), from: "inbound" };
  if (a.tool === "stop") return { ...base, ...end, station: "model", label: clean(a.label || "answer ready"), from: "core", mark: "done" };
  const c = classify(a.tool, inputOf(a.tool, a.label), SETUP.dark);
  return { ...base, ...end, station: c.station, label: clean(a.label || c.label), from: "core" };
}

/** A trail becomes stations: each station's count, its failures and which run now. */
export function boardOf(trail: Trail): Board {
  const entries = trail.actions.map(entryOf);
  const counts: Partial<Record<StationId, number>> = {};
  const faults: Partial<Record<StationId, number>> = {};
  for (const e of entries) {
    if (e.mark === "done" || e.station === "model") continue;
    counts[e.station] = (counts[e.station] ?? 0) + 1;
    if (e.status === "err") faults[e.station] = (faults[e.station] ?? 0) + 1;
  }
  const agents = entries.filter((e) => e.station === "agents" && e.status === "run" && e.agentId !== undefined).map((e) => e.agentId ?? "");
  return { entries, counts, faults, agents, ...(trail.ctx === null ? {} : { context: trail.ctx }) };
}

/** The map as SVG text, in the palette of the page's theme. */
export const mapSvg = (trail: Trail, nowSec: number, dark: boolean): string => drawMap(boardOf(trail), nowSec * 1000, dark ? SETUP.dark : SETUP.light);

export interface Station {
  readonly station: StationId;
  readonly count: number;
  readonly faults: number;
  readonly running: boolean;
}

/** The stations a trail touched, most visited first. */
export function stationsOf(trail: Trail): Station[] {
  const b = boardOf(trail);
  return (Object.keys(b.counts) as StationId[])
    .map((station) => ({
      station,
      count: b.counts[station] ?? 0,
      faults: b.faults?.[station] ?? 0,
      running: b.entries.some((e) => e.station === station && e.status === "run"),
    }))
    .sort((x, y) => y.count - x.count);
}

export type Kind = "worker" | "chat";

export interface SessionCard {
  readonly id: string;
  readonly kind: Kind;
  readonly agent: AgentRow;
  readonly title: string;
  readonly project: string;
  /** The queue account a worker runs on; "" for a chat. */
  readonly account: string;
  /** The ticket's key for a worker; a chat has none. */
  readonly ticketKey: string | null;
  /** Seconds since its last event. */
  readonly quiet: number;
  readonly silent: boolean;
  readonly idle: boolean;
  /** "HH:MM" of its last event for a worker with no queue item that went quiet for IDLE seconds, else null. */
  readonly silentSince: string | null;
  readonly now: string;
  /** obsidian:// links of the ticket a worker runs on. */
  readonly links: Links | undefined;
}

const clock = (sec: number): string => new Date(sec * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

const projectName = (p: string | undefined): string => (p ?? "").split("/").filter(Boolean).pop() ?? "";

/** Every live session, workers and the owner's chats: awake ones first (blocked, then by recency), idle ones (ended or quiet chats and helper workers) last. */
export function sessionCards(state: State, ix: TicketIndex, ags: Agents = splitAgents(state)): SessionCard[] {
  const ticketOf = (a: AgentRow): string | null => (/#\d+$/.test(a.agent) ? a.agent : null);
  const make = (a: AgentRow, kind: Kind): SessionCard => {
    const quiet = Math.max(0, state.now - a.at);
    const item = state.queue.items.find((i) => i.key === a.agent);
    const ended = a.state === "done";
    const stale = quiet >= IDLE;
    // a helper a chat started has no queue item to say it ended: quiet for IDLE while "working" is all there is to go by
    const lost = a.role === "worker" && item === undefined && !ended && a.state === "working" && stale;
    return {
      id: a.agent,
      kind,
      agent: a,
      title: kind === "worker" ? (item ? itemTitle(item, ix.byKey.get(item.key)) : agentLabel(a)) : agentLabel(a),
      project: projectName(a.project),
      account: kind === "worker" ? (item?.runner ?? item?.agent ?? state.queue.agent ?? "") : "",
      ticketKey: ticketOf(a),
      quiet,
      silent: !ended && quiet >= SILENT,
      idle: a.state === "idle" || a.state === "done" || (stale && (kind === "chat" || item === undefined)),
      silentSince: lost ? clock(a.at) : null,
      now: a.note ?? a.asked ?? "",
      links: item?.links,
    };
  };
  const all = [...ags.workers.map((a) => make(a, "worker")), ...ags.sessions.map((a) => make(a, "chat"))];
  return all.sort((x, y) => Number(x.idle) - Number(y.idle) || rank(x.agent) - rank(y.agent) || x.quiet - y.quiet);
}

export const KINDS = ["all", "worker", "chat"] as const;
export type KindFilter = (typeof KINDS)[number];
export const KIND_WORDS: Readonly<Record<KindFilter, string>> = { all: "All", worker: "Workers", chat: "Chats" };
