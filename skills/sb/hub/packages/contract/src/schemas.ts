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

/**
 * What an agent row says. A queue worker's row ends as "done" when its queue item ends (done, failed or skipped), at
 * the item's end time. "silent since HH:MM" is not stored: the page derives it from `at` for a worker with no queue item.
 */
export const AgentState = z.enum(["idle", "working", "waiting", "your turn", "needs you", "blocked", "done"]);
export type AgentState = z.infer<typeof AgentState>;

export const AgentRow = z.strictObject({
  agent: z.string(),
  name: z.string().optional(),
  title: z.string().optional(),
  asked: z.string().optional(),
  project: z.string().optional(),
  role: z.string().optional(),
  parent: z.string().optional(),
  ticket: z.string().optional(),
  /** The map ("<project>/<map>") the session is in charge of, or the map of a queue worker's ticket. */
  map: z.string().optional(),
  /** A queue worker's row: the id of the live session in charge of its map, when there is one. */
  in_charge: z.string().optional(),
  state: AgentState.optional(),
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

/** The hub's own landing that holds a repo's Unity lock (sbhub TicketRun._land): a restarted hub undoes it. */
export const Landing = z.strictObject({
  key: z.string(),
  repo: z.string(),
  before: z.string(),
  sha: z.string(),
  /** null for a Unity pass (sbhub _pass): it plays the checkout as it stands, with no worktree. */
  tree: z.string().nullable(),
  branch: z.string(),
  /** A Unity pass: nothing to merge, only the integrator's play. */
  only: z.boolean().optional(),
});
export const Lock = z.strictObject({ by: z.string(), at: Seconds, landing: Landing.optional() });
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

/**
 * landed: its commit and checks passed and its work landed, but it is not judged yet: it holds no files and no place
 * among the tickets running at once, and the ticket stays open. review: its map's one Opus second pass is judging it
 * against its Done when (a queue saved by an older hub may hold items here with no pass running: they are judged).
 * unclean: its checks passed but its work could not land because the checkout holds unsaved changes to its files
 * (`blocking`): it waits on its branch and lands once they are saved or cleared, rebased when the checkout moved.
 */
export const ItemState = z.enum(["queued", "running", "landed", "review", "recheck", "unclean", "done", "failed", "skipped"]);
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

/** One failed try of a ticket (sbhub `again`): the model it ran on, the first line of why it failed, the commit the
 * hub judged (null: none). */
export const Fail = z.strictObject({
  model: z.string(),
  why: z.string(),
  commit: z.string().nullable(),
});
export type Fail = z.infer<typeof Fail>;
/** The most tries a ticket gets (sbhub.py TRIES_MAX): the page says "try 3 of 5". */
export const TRIES_MAX = 5;

export const CheckRun = z.strictObject({
  cmd: z.string(),
  /** null when it timed out. */
  code: z.number().int().nullable(),
  secs: z.number(),
  tail: z.string(),
});
export type CheckRun = z.infer<typeof CheckRun>;

/** What a queued item waits for. `with` names the ticket (files, after) or map (after) it waits on. */
export const Waits = z.strictObject({
  kind: z.enum(["files", "limit", "after", "account", "paused", "time", "build"]),
  with: z.string().nullable(),
  text: z.string(),
});
export type Waits = z.infer<typeof Waits>;

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
  /** The id of the night it belongs to; absent from an item only a close-off job is. */
  night: z.string().optional(),
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
  /** Every failed try so far, oldest first: it is queued again from its kept work up to five tries (sbhub
   * TRIES_MAX), and goes to Waits for you with these after the last. `tries` is their count. */
  fails: z.array(Fail).optional(),
  resume: z.strictObject({ agent: z.string(), log: z.string(), why: z.string() }).optional(),
  stops: z.number().int().optional(),
  digested: z.boolean().optional(),
  /** recheck: how many times its checks (or its review) ran again, and when they next do (null: waiting for the
   * Recheck button). rechecks is null once a review starts afresh. */
  rechecks: z.number().int().nullable().optional(),
  recheck_at: Seconds.nullable().optional(),
  /** unclean: the checkout's files with unsaved changes that its work waits for. */
  blocking: z.array(z.string()).optional(),
  /** recheck: the repo whose build is broken outside its files; it lands once that builds again (no try spent). */
  held: z.string().nullable().optional(),
  /** job: the repo whose broken build this fix run mends (templates/fix-build.md). */
  fix_build: z.string().optional(),
  /** When it last landed (checks passed): the review timer counts from it, across hub restarts. */
  landed_at: Seconds.optional(),
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
  /** Set each time the hub looks for work, on a queued item only. */
  waits: Waits.optional(),
  /** The owner's Stop, with the reason and when: set while its worker is being ended, kept on the item it ended
   * (skipped, "stopped by you"). Dropped when the owner queues it again. */
  stop_asked: z.strictObject({ reason: z.string(), at: Seconds }).optional(),
  /** How many actions the worker's hook refused so far, and the last few; absent until the first refusal. */
  refused: z.number().int().optional(),
  refused_lines: z.array(z.string()).optional(),
  /** What its tries cost so far (sbhub `_add_spend`); written onto the ticket's note when the item ends. */
  spend: z.strictObject({
    run_minutes: z.number(),
    check_minutes: z.number(),
    tries: z.number().int(),
    model: z.string(),
    account: z.string().nullable(),
    tokens_in: z.number().optional(),
    tokens_out: z.number().optional(),
    cache_read: z.number().optional(),
    cost_usd: z.number().optional(),
  }).optional(),
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
  /** Its last Claude try's session id and the config dir it ran under: a stop, a restart or the review's one more
   * try resumes it (`claude --resume`); dropped when that resume fails or the try ran on agy. */
  session: z.string().optional(),
  session_dir: z.string().optional(),
  /** While it is in its Unity stage (landed, the Unity lock held, an integrator compiling and playing it on the main
   * folder): the landing's commits, the lock, the integrator's pid, log and report folder. Its fields are the
   * hub's own bookkeeping and may grow, so they are not listed. */
  integrate: z.record(z.string(), z.unknown()).optional(),
  /** Queued for a Unity pass: its work is already in the main folder, so no worker runs; the integrator plays it. */
  integrate_only: z.boolean().optional(),
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

/** One repo with something queued or running. */
export const RepoLoad = z.strictObject({
  /** `git config sb.parallel`, 1 to 8. */
  at_once: z.number().int(),
  running: z.number().int(),
  /** The most of its queued tickets that could run side by side given their files. */
  side_by_side: z.number().int(),
});
export type RepoLoad = z.infer<typeof RepoLoad>;

/** A repo's build as its after-landing checks last saw it: `green`, the newest commit whose checks passed; `errors`,
 * the last compile errors seen (by the landing of `errors_by`, at `errors_at`); `broken` while the checkout keeps a
 * landing that does not compile and could not be backed out; `held` while it does not build for a reason outside
 * any ticket's files. */
export const Build = z.strictObject({
  green: z.string().optional(),
  errors: z.array(z.string()).optional(),
  errors_by: z.string().nullable().optional(),
  errors_at: Seconds.optional(),
  broken: z.boolean().optional(),
  /** While the build is broken outside any ticket's files: the check that failed, whether it runs after landing, the
   * files it names, and the commit and time it last ran on. Its repo starts nothing new until it passes. */
  held: z
    .strictObject({ cmd: z.string(), after: z.boolean(), files: z.array(z.string()), head: z.string(), at: Seconds })
    .optional(),
  /** The one fix run of this break: its job's key (null when it could not be queued), whether it ended, and the id of
   * the question put to the owner when it could not mend it. */
  fix: z.strictObject({ key: z.string().nullable(), ended: z.boolean(), asked: z.string().optional() }).optional(),
});
export type Build = z.infer<typeof Build>;

export const Queue = z.strictObject({
  version: z.number().int(),
  seeded: z.boolean(),
  paused: z.boolean(),
  /** Why the hub paused the queue by itself ("paused: three tickets in a row failed with …"); absent otherwise. */
  note: z.string().nullable().optional(),
  agent: z.string().nullable(),
  items: z.array(QueueItem),
  /** The queued maps in run order: in a repo the hub starts tickets only from the first one with work or something
   * to start. A ticket queued alone is a map of one. Absent from a queue saved before maps. */
  maps: z.array(z.string()).optional(),
  agents: z.array(z.string()).optional(),
  stop_at: Seconds.nullable().optional(),
  final_review: z.boolean().optional(),
  /** The id of the night that is live or stopping, null when none is. */
  night: z.string().nullable().optional(),
  /** Finished items taken off the list: the page's log. */
  cleared: z.array(QueueItem).optional(),
  /** Map -> tonight's run board. */
  runs: z.record(z.string(), z.string()).optional(),
  /** Repo -> the night's first base, for the final review. */
  bases: z.record(z.string(), z.strictObject({ sha: z.string().nullable(), project: z.string().nullable() })).optional(),
  close_off_day: z.string().optional(),
  /** Repo -> its load, for each repo with anything queued or running. */
  repos: z.record(z.string(), RepoLoad).optional(),
  /** Repo -> what the hub knows of its build from the after-landing checks. */
  builds: z.record(z.string(), Build).optional(),
});
export type Queue = z.infer<typeof Queue>;

// ---- nights: one sb tonight ----

export const NightState = z.enum(["live", "stopping", "ended"]);
export type NightState = z.infer<typeof NightState>;
/** finished: its last item was judged; stopped: you stopped it after what ran; stop_time: the queue's stop time passed. */
export const NightHow = z.enum(["finished", "stopped", "stop_time"]);
export type NightHow = z.infer<typeof NightHow>;

export const NightCounts = z.strictObject({
  items: z.number().int(),
  queued: z.number().int(),
  /** At work or not judged yet (running, landed, review, recheck, unclean). */
  running: z.number().int(),
  done: z.number().int(),
  failed: z.number().int(),
  skipped: z.number().int(),
  not_reached: z.number().int(),
});

export const Night = z.strictObject({
  id: z.string(),
  name: z.string(),
  started: Seconds,
  /** The session that started it; null when none said. */
  by: z.string().nullable(),
  state: NightState,
  ended: Seconds.nullable(),
  how: NightHow.nullable(),
  /** What a stop left out of the line: open tickets (and jobs) that never started. */
  not_reached: z.array(z.strictObject({ key: z.string(), title: z.string() })),
  counts: NightCounts,
});
export type Night = z.infer<typeof Night>;

export const NightsAnswer = z.strictObject({ nights: z.array(Night) });
export const NightDetail = z.strictObject({ night: Night.extend({ items: z.array(QueueItem) }) });
export const NightAnswer = z.strictObject({ ok: z.literal(true), night: Night });
export const NightStartBody = z.strictObject({ name: z.string().nullable().optional(), by: z.string().nullable().optional() });
export const NightRenameBody = z.strictObject({ name: z.string() });
export const NightStopBody = z.strictObject({ mode: z.literal("after") });

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
  /** Map -> the live session in charge of it. Absent from a state saved before this. */
  charge: z.record(z.string(), z.string()).optional(),
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
  /** When the review timer next looks: the oldest landed ticket's landing plus SB_REVIEW_EVERY_MIN (25) minutes,
   * over maps with no review running; null when no landed ticket waits (absent from a hub older than this). */
  review_next_at: Seconds.nullable().optional(),
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
  /** Who can tell it is done: "tests" (a worker's checks) or "owner" (a ticket the owner checks; never run). */
  check: z.enum(["tests", "owner"]),
  has_done_when: z.boolean(),
  done_when: z.string(),
  question: z.string(),
  /** A decision ticket's `## Options`, the ➡️ one recommended; optional while an older hub runs. */
  options: z.array(z.strictObject({ text: z.string(), recommended: z.boolean() })).optional(),
  /** The owner's answer to a decision ticket (sbmap rule); null until they answer. */
  ruling: z.string().nullable().optional(),
  out: z.string(),
  checks: z.array(z.string()),
  /** Where its checks came from: its own, its map's, the repo's .sb/checks, or "" when it has none. */
  checks_from: z.enum(["ticket", "map", "repo", ""]).optional(),
  repo: z.string(),
  file: z.string(),
  map_title: z.string(),
  map_order: z.number().int(),
  claimed_by: z.string().nullable(),
  /** The bundle (2 to 4 tickets one worker runs together) this ticket is in and its 1-based place; null when none. */
  bundle: z.string().nullable().optional(),
  position: z.number().int().nullable().optional(),
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
  /** The bundle (2 to 4 tickets one worker runs together) this ticket is in and its 1-based place; null when none. */
  bundle: z.string().nullable().optional(),
  position: z.number().int().nullable().optional(),
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
  /** The map ("<project>/<map>") this session is in charge of. */
  map: z.string().optional(),
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
/** `agent`: the session adding the tickets; it is put in charge of their maps unless another live session is. */
export const QueueSetBody = z.strictObject({ keys: z.array(z.string()), version: z.number().int().nullable(), agent: z.string().optional() });
export const QueueMoveBody = z.strictObject({ key: z.string(), to: z.number().int(), version: z.number().int().nullable() });
/** Queue every open ticket of a map that can run, in order, at the map's place (last when it is new). */
export const QueueMapBody = z.strictObject({ map: z.string().min(1), version: z.number().int().nullable(), agent: z.string().optional() });
/** Move a queued map to place `to` among the queued maps. */
export const QueueMoveMapBody = z.strictObject({ map: z.string().min(1), to: z.number().int(), version: z.number().int().nullable() });
export const QueuePauseBody = z.strictObject({ paused: z.boolean() });
export const QueueParallelBody = z.strictObject({
  repo: z.string(),
  n: z.number().int().min(1).max(8),
  version: z.number().int().nullable(),
});
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
/** The owner's Stop on a running item: its worker's whole process group is killed within seconds and the item ends
 * skipped, "stopped by you" with the reason; its work stays where it is. */
export const QueueStopBody = z.strictObject({ key: z.string(), reason: z.string().trim().min(1), version: z.number().int().nullable() });
/** `name`: the account (null: the pool); `model`: sonnet or opus (null: the ticket's own tier). Left out stays as it is. */
export const QueueItemAgentBody = z.strictObject({ key: z.string(), name: z.string().nullable().optional(), model: z.enum(["sonnet", "opus"]).nullable().optional() });
/** `<run key>@<ended>`: one ended run, once. */
export const RunSeenBody = z.strictObject({ key: z.string().min(1) });
export const AgentsDismissBody = z.strictObject({ agent: z.string() });
export const EmptyBody = z.strictObject({});
export const TICKET_ACTIONS = ["done", "drop", "release", "comment", "rule", "tier", "checks", "recheck", "done_when", "paths", "after"] as const;
export const TicketAction = z.enum(TICKET_ACTIONS);
export type TicketAction = z.infer<typeof TicketAction>;
export const TicketActionBody = z.strictObject({
  key: z.string(),
  /** The typed line: needed by every action but release; for rule the owner's answer (an option's text, their words, or both). For done_when the new Done when text; for paths one file per
   * line (empty clears them); for after the ticket numbers of its map, separated by commas (empty clears them). */
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
/** A Unity pass for failed tickets whose work is in the checkout (sbhub queue integrate). */
export const QueueIntegrateBody = z.strictObject({ keys: z.array(z.string()).min(1) });
export const QueueIntegrateAnswer = z.strictObject({ ok: z.literal(true), queued: z.array(z.string()) });
/** Each ticket of the map left out, with why: it needs the owner, has no done-when or checks, is claimed, or waits
 * on a map that is not queued. */
export const QueueMapAnswer = QueueAnswer.extend({
  left_out: z.array(z.strictObject({ key: z.string(), reason: z.string() })),
});
export const ClearQuietAnswer = z.strictObject({ ok: z.literal(true), cleared: z.number().int() });
/** POST /api/review/now: the maps whose review it started (none while each already runs one). */
export const ReviewNowAnswer = z.strictObject({ ok: z.literal(true), started: z.array(z.string()) });
export const ScanAnswer = z.strictObject({ ok: z.literal(true), installed: z.record(z.string(), Installed) });
