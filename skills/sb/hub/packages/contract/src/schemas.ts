/**
 * The shapes the Python hub (skills/sb/scripts/sbhub.py) answers with and accepts. Objects the hub builds
 * itself are strict: a field renamed in sbhub.py is an unknown key here, and the fixture test fails.
 * Only what a project's own provider script returns stays open (`ProviderPanel`).
 */
import { z } from "zod";
import { Links } from "./links.ts";

/** Epoch seconds, as Python's time.time() gives them. */
export const Seconds = z.number();
/** A progress count: a number from a hook or the page, the text as typed from `sbhub.py report --done N`. */
export const Count = z.union([z.number(), z.string()]);

// ---- agents, locks, questions, messages ----

export const AgentRow = z.strictObject({
  agent: z.string(),
  name: z.string().optional(),
  title: z.string().optional(),
  asked: z.string().optional(),
  project: z.string().optional(),
  role: z.string().optional(),
  parent: z.string().optional(),
  ticket: z.string().optional(),
  state: z.string().optional(),
  note: z.string().optional(),
  done: Count.optional(),
  total: Count.optional(),
  at: Seconds,
  since: Seconds.optional(),
  spawns: z.array(z.string()).optional(),
  /** The Claude session id a hub worker first reported from; a helper under the same name has another. */
  session: z.string().optional(),
});
export type AgentRow = z.infer<typeof AgentRow>;

export const Lock = z.strictObject({ by: z.string(), at: Seconds });
export type Lock = z.infer<typeof Lock>;

export const Question = z.strictObject({
  agent: z.string(),
  q: z.string(),
  options: z.array(z.string()).min(2).max(4),
  default: z.string(),
  asked: Seconds,
  deadline: Seconds,
  answer: z.string().nullable(),
  /** "you", "default" (its deadline passed), or who answered. */
  by: z.string().nullable(),
  answered: Seconds.optional(),
});
export type Question = z.infer<typeof Question>;

export const Message = z.strictObject({
  to: z.string(),
  text: z.string(),
  at: Seconds,
  delivered: Seconds.nullable(),
  /** The hook event that delivered it. */
  how: z.string().nullable(),
  /** Set when its session ended before the message was delivered. */
  lost: Seconds.optional(),
});
export type Message = z.infer<typeof Message>;

// ---- installed agents ----

export const UsageReading = z.strictObject({
  five_hour: z.number(),
  five_hour_resets: z.number().nullable(),
  seven_day: z.number().nullable(),
  seven_day_resets: z.number().nullable(),
});
export const Usage = UsageReading.extend({ at: Seconds });
export type Usage = z.infer<typeof Usage>;

export const Installed = z.strictObject({
  kind: z.enum(["claude", "agy"]),
  dir: z.string().nullable(),
  model: z.string().nullable(),
  limited_until: Seconds.nullable(),
  usage: Usage.optional(),
  costs: z.record(z.string(), z.strictObject({ avg: z.number(), n: z.number().int() })).optional(),
  pending: z.strictObject({ tier: z.string(), u0: UsageReading }).optional(),
  probed: Seconds.optional(),
  login: z.literal("expired").nullable().optional(),
});
export type Installed = z.infer<typeof Installed>;

// ---- the queue ----

/** review: its commit and checks passed and the Opus second pass judges it against its Done when. */
export const ItemState = z.enum(["queued", "running", "review", "recheck", "done", "failed", "skipped"]);
export type ItemState = z.infer<typeof ItemState>;

/** The Opus second pass's judgement of a ticket against its Done when: only finished resolves it. */
export const Verdict = z.enum(["finished", "partly", "not met"]);
export type Verdict = z.infer<typeof Verdict>;

/** The one more try a first review that was not finished asks for: the first try's commit, verdict and findings. */
export const Redo = z.strictObject({
  /** null: the first try made no commit (its report said no change was needed). */
  commit: z.string().nullable(),
  verdict: z.enum(["partly", "not met"]),
  /** The review's not-met lines (all its lines when none says not met), each starting "- ". */
  findings: z.array(z.string()),
  /** The first review's file, kept as <num>-review-1.md. */
  review: z.string().nullable(),
  /** The first try's base commit. */
  base: z.string().nullable(),
});
export type Redo = z.infer<typeof Redo>;

export const CheckRun = z.strictObject({
  cmd: z.string(),
  /** null when it timed out. */
  code: z.number().int().nullable(),
  secs: z.number(),
  tail: z.string(),
});
export type CheckRun = z.infer<typeof CheckRun>;

const itemFields = {
  key: z.string(),
  agent: z.string().nullable(),
  state: ItemState,
  note: z.string(),
  commit: z.string().nullable(),
  tries: z.number().int(),
  started: Seconds.nullable(),
  ended: Seconds.nullable(),
  title: z.string().optional(),
  repo: z.string().optional(),
  runner: z.string().optional(),
  run: z.string().optional(),
  log: z.string().optional(),
  log_start: z.number().int().optional(),
  pid: z.number().int().nullable().optional(),
  /** The process's start time as `ps -o lstart` prints it. */
  pid_start: z.string().nullable().optional(),
  base_sha: z.string().nullable().optional(),
  first_base: z.string().nullable().optional(),
  result: z.string().optional(),
  retry: z.string().optional(),
  resume: z.strictObject({ agent: z.string(), log: z.string(), why: z.string() }).optional(),
  stops: z.number().int().optional(),
  digested: z.boolean().optional(),
  /** recheck: how many times its checks (or its review) ran again, and when they next do (null: waiting for the
   * Recheck button). rechecks is null once a review starts afresh. */
  rechecks: z.number().int().nullable().optional(),
  recheck_at: Seconds.nullable().optional(),
  media: z.array(z.string()).optional(),
  checks: z.array(CheckRun).optional(),
  /** The second pass's verdict once it gave one (null while none). */
  verdict: Verdict.nullable().optional(),
  /** Its review file, <run>/<num>-review.md, once the review started. */
  review: z.string().nullable().optional(),
  /** The one more try its first review asked for (partly or not met): set once, there is no other. Dropped when
   * the owner queues it again. */
  redo: Redo.optional(),
  /** The hub's own check that passed, kept while the review runs (or waits to run again); null after. */
  checked: z.string().nullable().optional(),
  /** obsidian:// links to its notes, added by the TypeScript server (links.ts). */
  links: Links,
};

export const TicketItem = z.strictObject({
  ...itemFields,
  kind: z.literal("ticket"),
  map: z.string().optional(),
  model: z.string().nullable().optional(),
  /** The ticket's own worktree and branch when its repo runs tickets side by side (`git config sb.parallel`). */
  tree: z.string().nullable().optional(),
  branch: z.string().nullable().optional(),
  /** Its paths while it runs in a worktree: another ticket whose paths meet these waits. */
  paths: z.array(z.string()).nullable().optional(),
});
export type TicketItem = z.infer<typeof TicketItem>;

export const JobItem = z.strictObject({
  ...itemFields,
  kind: z.literal("job"),
  model: z.string().nullable(),
  project: z.string(),
  repo: z.string(),
  prompt: z.string(),
  hash: z.string(),
  name: z.string(),
  title: z.string(),
  created: Seconds,
  /** Held until then (a job queued with `at`). */
  not_before: Seconds.optional(),
  close_off: z.literal(true).optional(),
});
export type JobItem = z.infer<typeof JobItem>;

export const QueueItem = z.discriminatedUnion("kind", [TicketItem, JobItem]);
export type QueueItem = z.infer<typeof QueueItem>;

export const Queue = z.strictObject({
  version: z.number().int(),
  seeded: z.boolean(),
  paused: z.boolean(),
  agent: z.string().nullable(),
  items: z.array(QueueItem),
  agents: z.array(z.string()).optional(),
  stop_at: Seconds.nullable().optional(),
  final_review: z.boolean().optional(),
  /** Finished items taken off the list: the page's log. */
  cleared: z.array(QueueItem).optional(),
  /** Map -> tonight's run board. */
  runs: z.record(z.string(), z.string()).optional(),
  /** Repo -> the night's first base, for the final review. */
  bases: z.record(z.string(), z.strictObject({ sha: z.string().nullable(), project: z.string().nullable() })).optional(),
  close_off_day: z.string().optional(),
});
export type Queue = z.infer<typeof Queue>;

// ---- providers: the hub's own panel is strict, a project's script may add anything ----

export const Level = z.enum(["ok", "warn", "bad"]);
export type Level = z.infer<typeof Level>;

export const StatusWidget = z.strictObject({ kind: z.literal("status"), label: z.string(), value: z.string(), level: Level });
export const LogWidget = z.strictObject({ kind: z.literal("log"), label: z.string(), lines: z.array(z.string()) });

/** The panel sbhub.py's generic_provider builds for every project with an agent. */
export const RepoProvider = z.strictObject({
  title: z.literal("Repo and maps"),
  icon: z.literal("git"),
  widgets: z.array(z.discriminatedUnion("kind", [StatusWidget, LogWidget])),
});

/** Any panel: one from a project's .sb/providers script, or the hub's own. */
export const ProviderPanel = z.looseObject({
  title: z.string(),
  icon: z.string().optional(),
  widgets: z.array(z.looseObject({ kind: z.string().optional(), label: z.string().optional() })),
});
export type ProviderPanel = z.infer<typeof ProviderPanel>;

// ---- GET answers ----

/** One action in a session's trail: a tool call, a subagent's run, a prompt or the end of a turn. */
export const TrailAction = z.strictObject({
  tool: z.string(),
  label: z.string(),
  start: Seconds,
  /** null while it runs. */
  end: Seconds.nullable(),
  /** null while it runs; false when the tool failed. */
  ok: z.boolean().nullable(),
  /** A subagent's run rather than a tool call. */
  sub: z.boolean(),
});
export type TrailAction = z.infer<typeof TrailAction>;

/** The last 40 actions of one agent, oldest first. Served by GET /api/trail, never part of /api/state. */
export const Trail = z.strictObject({
  agent: z.string(),
  /** Context used, in percent, when a report said so. */
  ctx: z.number().nullable(),
  /** When the agent ended; its trail goes ten minutes later. */
  ended: Seconds.nullable(),
  actions: z.array(TrailAction).max(40),
});
export type Trail = z.infer<typeof Trail>;

/** How a run ended; unknown for a run in the vault the queue never judged. */
export const RunOutcome = z.enum(["done", "failed", "skipped", "unknown"]);
export type RunOutcome = z.infer<typeof RunOutcome>;

/** One run of one ticket, from the queue's items and the vault's run folders. */
export const Run = z.strictObject({
  /** `<map>#<number>`, as a queue item's key. */
  key: z.string(),
  title: z.string(),
  project: z.string(),
  map: z.string(),
  outcome: RunOutcome,
  /** Why it did not finish, in plain words; empty for a run that is done. */
  reason: z.string(),
  account: z.string().nullable(),
  model: z.string().nullable(),
  started: Seconds.nullable(),
  ended: Seconds.nullable(),
  commit: z.string().nullable(),
  tries: z.number().int(),
  /** How many actions the worker's hook refused, and the last few ("refused: Bash: ..."). */
  refused: z.number().int(),
  refused_lines: z.array(z.string()),
  /** File names in its <number>-media folder, served by api/media?key=&name=. */
  pictures: z.array(z.string()),
  links: Links,
});
export type Run = z.infer<typeof Run>;

/** One page of runs, newest first; `total` counts every run in the time range asked for. */
export const RunsPage = z.strictObject({ runs: z.array(Run), total: z.number().int(), offset: z.number().int(), limit: z.number().int() });
export type RunsPage = z.infer<typeof RunsPage>;

/** What the run viewer shows: the run, its checks, its report and the end of its log (null where it has none). */
export const RunDetail = z.strictObject({ run: Run, checks: z.array(CheckRun), report: z.string().nullable(), log: z.string().nullable() });
export type RunDetail = z.infer<typeof RunDetail>;

export const State = z.strictObject({
  agents: z.record(z.string(), AgentRow),
  locks: z.record(z.string(), Lock),
  questions: z.record(z.string(), Question),
  /** Session id -> the agent id it reports as. */
  aliases: z.record(z.string(), z.string()),
  messages: z.record(z.string(), Message),
  queue: Queue,
  installed: z.record(z.string(), Installed),
  /** Ended runs the owner has opened, as `<key>@<ended>`, oldest first. */
  seen: z.array(z.string()),
  now: Seconds,
  /** Project path -> its panels. */
  providers: z.record(z.string(), z.array(ProviderPanel)),
  /** Who holds ~/.sb-hub/queue.lock: `mine` is false on a hub that serves read-only beside another that runs the queue. */
  queue_lock: z.strictObject({ mine: z.boolean(), holder: z.string() }).optional(),
});
export type State = z.infer<typeof State>;

export const TicketState = z.enum(["ready", "blocked", "claimed", "waits for you", "not ready"]);
export type TicketState = z.infer<typeof TicketState>;

/** One open ticket: sbmap's `tickets --json` row plus the hub's state, reason and queued. */
export const TicketRow = z.strictObject({
  map: z.string(),
  num: z.number().int(),
  title: z.string(),
  why: z.string(),
  type: z.string(),
  status: z.enum(["open", "claimed"]),
  priority: z.string().nullable(),
  blocked_by: z.array(z.union([z.number().int(), z.string()])),
  blocked_by_open: z.array(z.union([z.number().int(), z.string()])),
  paths: z.array(z.string()),
  tier: z.string(),
  has_done_when: z.boolean(),
  done_when: z.string(),
  question: z.string(),
  out: z.string(),
  checks: z.array(z.string()),
  repo: z.string(),
  file: z.string(),
  map_title: z.string(),
  map_order: z.number().int(),
  claimed_by: z.string().nullable(),
  queued: z.boolean(),
  state: TicketState,
  reason: z.string(),
  /** obsidian:// links to its notes, added by the TypeScript server (links.ts). */
  links: Links,
});
export type TicketRow = z.infer<typeof TicketRow>;
export const Tickets = z.array(TicketRow);

/** A ticket another ticket comes after: in this map or another; `num` is null when it names a whole map. */
export const Blocker = z.strictObject({
  map: z.string(),
  num: z.number().int().nullable(),
  title: z.string(),
  /** The ticket's or map's status; "missing" when the reference points nowhere. */
  status: z.string(),
});

/** One ticket of GET /api/map: open, claimed, resolved or out of scope. */
export const MapTicket = z.strictObject({
  num: z.number().int(),
  title: z.string(),
  type: z.string(),
  status: z.enum(["open", "claimed", "resolved", "out-of-scope"]),
  /** The hub's state word as /api/tickets gives it, plus "done" and "out of scope". */
  state: z.union([TicketState, z.enum(["done", "out of scope"])]),
  why: z.string(),
  priority: z.string().nullable(),
  tier: z.string(),
  /** 1-based place among the queued tickets, or null when it is not queued. */
  place: z.number().int().nullable(),
  /** The outcome of its last queue run, or null when it never ran. */
  last_run: z.strictObject({ state: z.string(), note: z.string(), ended: Seconds.nullable() }).nullable(),
  blocked_by: z.array(Blocker),
  file: z.string(),
  links: Links,
});
export type MapTicket = z.infer<typeof MapTicket>;

/** GET /api/map?map=: a map's bearings and every ticket of it, in map order. */
export const MapRoute = z.strictObject({
  map: z.string(),
  title: z.string(),
  status: z.string(),
  /** The first sentence of the map's plain words. */
  words: z.string(),
  checks: z.array(z.string()),
  uri: z.string(),
  tickets: z.array(MapTicket),
});
export type MapRoute = z.infer<typeof MapRoute>;

export const TrailFile = z.strictObject({
  name: z.string(),
  path: z.string(),
  at: Seconds,
  first: z.string(),
  uri: z.string(),
});

/** GET /api/ticket?key=: what the side panel shows beyond the row. */
export const TicketDetail = z.strictObject({
  key: z.string(),
  title: z.string(),
  file: z.string(),
  open: z.boolean(),
  comments: z.array(z.string()),
  map_checks: z.array(z.string()),
  trail: z.array(TrailFile),
  uri: z.string(),
  map_uri: z.string(),
});
export type TicketDetail = z.infer<typeof TicketDetail>;

/** A worker's report or log: plain text. */
export const ItemText = z.string();

export const MEDIA_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp", "video/mp4", "video/webm"] as const;
export const MediaType = z.enum(MEDIA_TYPES);

// ---- POST bodies ----

export const ReportBody = z.strictObject({
  agent: z.string(),
  /** The reporting Claude session's id, sent by the hook for a hub worker. */
  session: z.string().optional(),
  alias: z.string().optional(),
  spawn: z.string().optional(),
  name: z.string().optional(),
  title: z.string().optional(),
  asked: z.string().optional(),
  project: z.string().optional(),
  role: z.string().optional(),
  parent: z.string().optional(),
  ticket: z.string().optional(),
  /** "gone" removes the agent. */
  state: z.string().optional(),
  note: z.string().optional(),
  done: Count.optional(),
  total: Count.optional(),
  /** One hook event for the trail (GET /api/trail). */
  trail: z
    .strictObject({
      kind: z.enum(["pre", "post", "fail", "substart", "substop", "prompt", "stop", "refused"]),
      tool: z.string(),
      label: z.string(),
    })
    .optional(),
  /** Context used, in percent. */
  ctx: z.number().optional(),
});
export const LockBody = z.strictObject({ key: z.string(), by: z.string() });
export const AskBody = z.strictObject({
  agent: z.string(),
  q: z.string().min(1),
  options: z.array(z.string().min(1)).min(2).max(4),
  default: z.string(),
  /** Seconds before the default applies. */
  wait: z.number().nonnegative(),
});
export const AnswerBody = z.strictObject({ qid: z.string(), answer: z.string(), by: z.string().optional() });
export const SendBody = z.strictObject({ to: z.string().min(1), text: z.string().min(1).max(4000) });
export const UnsendBody = z.strictObject({ id: z.string() });
export const TakeBody = z.strictObject({ agent: z.string(), how: z.string().nullable().optional() });
export const QueueSetBody = z.strictObject({ keys: z.array(z.string()), version: z.number().int().nullable() });
export const QueueMoveBody = z.strictObject({ key: z.string(), to: z.number().int(), version: z.number().int().nullable() });
export const QueuePauseBody = z.strictObject({ paused: z.boolean() });
export const QueueAgentBody = z.strictObject({ name: z.string() });
export const QueueAgentsBody = z.strictObject({ names: z.array(z.string()).min(1), version: z.number().int().nullable() });
export const QueueOptionsBody = z.strictObject({
  stop_at: Seconds.nullable().optional(),
  final_review: z.boolean().optional(),
  version: z.number().int().nullable(),
});
export const QueueJobBody = z.strictObject({
  /** A wayfinder project folder, or an absolute path to a git checkout. */
  project: z.string(),
  prompt: z.string().min(1),
  agent: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
  /** "HH:MM", local: held until the clock next shows it. */
  at: z.string().nullable().optional(),
});
export const QueueRemoveJobBody = z.strictObject({ key: z.string(), version: z.number().int().nullable() });
export const QueueClearFinishedBody = z.strictObject({ version: z.number().int().nullable().optional() });
export const QueueItemAgentBody = z.strictObject({ key: z.string(), name: z.string().nullable().optional() });
/** `<run key>@<ended>`: one ended run, once. */
export const RunSeenBody = z.strictObject({ key: z.string().min(1) });
export const AgentsDismissBody = z.strictObject({ agent: z.string() });
export const EmptyBody = z.strictObject({});
export const TICKET_ACTIONS = ["done", "drop", "release", "comment", "tier", "checks", "recheck"] as const;
export const TicketAction = z.enum(TICKET_ACTIONS);
export type TicketAction = z.infer<typeof TicketAction>;
export const TicketActionBody = z.strictObject({
  key: z.string(),
  /** The typed line: needed by every action but release. */
  text: z.string().optional(),
  /** done only: the commit to stamp on the ticket. */
  commit: z.string().optional(),
});

// ---- POST answers ----

export const Ok = z.strictObject({ ok: z.literal(true) });
/** Every 400, 403, 404 and 500 with a body. */
export const ApiError = z.strictObject({ ok: z.literal(false), error: z.string() });
export type ApiError = z.infer<typeof ApiError>;

export const ReportAnswer = z.strictObject({ ok: z.literal(true), needs_you: z.boolean(), agent: z.string() });
export const LockHeld = z.strictObject({ ok: z.literal(false), held_by: z.string() });
export const IdAnswer = z.strictObject({ ok: z.literal(true), id: z.string() });
export const TakeAnswer = z.strictObject({ ok: z.literal(true), messages: z.array(z.string()) });
export const QueueAnswer = z.strictObject({ ok: z.literal(true), queue: Queue });
/** 409: the version sent is not the queue's; nothing changed, here is the queue as it is. */
export const QueueStale = z.strictObject({ ok: z.literal(false), stale: z.literal(true), queue: Queue });
export type QueueStale = z.infer<typeof QueueStale>;
export const QueueJobAnswer = QueueAnswer.extend({ key: z.string() });
export const ClearQuietAnswer = z.strictObject({ ok: z.literal(true), cleared: z.number().int() });
export const ScanAnswer = z.strictObject({ ok: z.literal(true), installed: z.record(z.string(), Installed) });
