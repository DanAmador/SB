# sb hub queue: the hub runs the night's tickets itself

Status: approved by the owner, 2026-11-12 (a fresh reader's nine questions are settled below as my calls). Builds on
[the hub](2026-11-12-sb-hub-design.md). Evidence: [session analysis](2026-11-12-session-analysis.md),
[start context](2026-11-12-start-context.md).

## Intent

The owner brainstorms by voice with one agent, then wants implementation to run unattended. Today
an orchestrator session does the night's bookkeeping in a model: it took 46% of all input tokens in
three weeks, several runs share one usage limit by accident, and after a limit the owner restarts
each by hand (the same "please continue" message nine times). The queue moves that bookkeeping
into plain code in the hub.

Owner, 2026-11-12: "I like the hub runs tickets itself." · unattended workers: "Yes, auto mode." ·
agents: "just have a way to choose which installed agent i can use because i only use antigravity
on emergencies / mechanical tasks." · the unit: "I prefer to have control of the tickets … use the
status of the tickets to see what I can unqueue … these are the tickets that are available to work
with tonight. Find the order of like how to implement them as efficiently as possible, and just
have a implementation queue that runs with the equivalent of SP tonight. But the UI should just
work like a command office with a way to view everything at a glance."

## Goals

1. **No orchestrator session.** The hub picks the next ready ticket, starts one worker, checks its
   result and records it, with no model in that loop.
2. **Workers start small.** A worker is a headless session (measured: 28.7k tokens at start,
   against 78k in the desktop app).
3. **One queue for everything that runs unattended**: map tickets and one-off jobs (an audit, a
   review, a wiki tend), in the order the owner set, never two copies of the same job.
4. **The owner chooses the agent** per queued item, from the ones installed; nothing switches by
   itself.
5. **A limit is a pause.** When the chosen agent hits its usage limit, the queue waits for the
   reset and carries on, with no message from the owner.
6. **The page is the control**: add, reorder, pause, start, see what ran and what waits.

Non-goals (now): running two workers on one repo at once; worktrees; spreading one item across
agents; starting desktop-app sessions; remote or multi-user use.
Anti-goals: a model that only waits and dispatches; a second record beside the vault; a worker
that asks in chat; the hub deciding anything that needs judgement.

## Approaches

| | approach | trade-off |
|---|---|---|
| ✅ picked by the owner | The hub runs tickets itself: frontier → claim → headless worker → mechanical check → resolve | judgement steps become their own queued jobs |
| | The hub queues whole runs, one orchestrator session per run board | smallest change, but the orchestrator's tokens stay |
| | Both, with a fallback orchestrator for maps that are not ready | two paths to build and keep working |

## How it works

**Agents.** `~/.sb-hub/agents.json` lists what is installed, found by `sbhub agents --scan`
(Claude Code configs `~/.claude*` that are signed in; `agy` when on PATH) and editable. An agent is
`{name, kind: claude|agy, config dir, default model}`. Each is shown on the page with its state:
free, running, limited until 04:40. *My call:* one worker at a time per agent.

**The unit is the ticket, and the owner holds the list** (revised 2026-11-12, replacing "a map
item works its frontier"). The hub reads every open map in the vault through `sbmap` and sorts each
open ticket into one of six states:

| state | means | on the page |
|---|---|---|
| ready | type `task`/`research`/`prototype`, has a `Done when` and checks, every blocker resolved or itself queued ahead | ticked for tonight by default; untick to leave it out |
| blocked | waits on a ticket that is not queued | shows which one; ticking the blocker makes it ready |
| waits for you | `grilling` or `architecture`, or a playtest | listed, never run |
| not ready | no `Done when` or no checks | says what is missing |
| running / claimed | a worker or another session holds it | who, since when |
| done tonight / failed | resolved, or left open after its retry | commit, or the reason |

**Tonight's queue** is the ticked ready tickets, put in order by the hub in code (*my call*, the
rule is fixed so the same ticks always give the same order):

1. a ticket runs after everything it is blocked by;
2. then by the ticket's priority (S to F);
3. then the ticket that unblocks the most others;
4. then map order.

Tickets of different repos are independent: with two agents chosen, two repos run side by side;
inside one repo the order is serial. The owner can drag a ticket to override, within rule 1. The
queue shows the estimate (1.5 h a ticket by default, the repo's own figure when the map has one) and
the clock time it ends, as `tonight` does today.

**Jobs** are the second kind of queue line, for what needs a model's judgement or is not a ticket:
an audit, the night's final review, reconciling the ticked tickets against the code before the
run (`tonight`'s step 2), `/sb learn`. A job names its project, prompt (or a vault note holding
it), agent and model; the same project and prompt within a day is refused as a duplicate.

Everything is added and removed on the page, by `sbhub queue …`, or by the `sb_queue` MCP tool at
the end of a brainstorm ("queued 6 tickets of <map> for tonight"). The queue lives in the hub's own
state: the vault stays the record of tickets, the queue is only tonight's selection and order.

**The ticket loop** (per queued ticket, serial per repo):

1. Take the next ticket in the queue whose repo and agent are free.
2. Re-read it: if it was resolved, claimed or blocked since it was queued, mark it so and go on.
3. `sbmap claim`, then start the worker headless in the repo, in **auto** permission mode, with the
   session brief ([templates/session-brief.md](../../../skills/sb/templates/session-brief.md))
   filled from the ticket, the model by the ticket's tier (`sonnet` unless the ticket says
   `opus`), and a time limit (default 90 minutes). The worker reports to the hub through the
   existing hooks, so it shows as a row with its ticket.
4. When the worker exits, the hub checks, in code: a new commit exists carrying the trailer
   `Ticket: <map>/<NNN>`; it touches only the ticket's `paths` when the ticket has them; each check
   command exits 0. *My call:* check commands come from a `checks:` list on the map (set once with
   `sbmap set <map> checks=…`, written by `chart`/`tonight` from the contract), overridable per
   ticket.
5. Pass → `sbmap resolve` with the commit, the checks' counts and the worker's report path.
   Fail → one retry on the next model tier with the failed output in the brief; a second failure
   leaves the ticket open with a comment, releases the claim and moves on.
6. A worker's blocking question goes through `sbhub ask` as today (default at the deadline).
7. Queue empty → the hub writes the night's digest to each map's run board and, when the owner
   ticked it, runs one last job: the final review on the capable tier.

**Limits.** The worker's exit output is read for the agent's limit message; the agent is marked
limited until the reset time it names (or one hour when none is given), the ticket's claim is
released, and the queue resumes that item at the reset. Items on other agents keep running.

**Stop conditions** per item: frontier empty, its ticket limit or stop time reached, the same
failure three tickets in a row, or the owner pauses it. A paused or crashed hub resumes from its
state file: a claimed ticket with no live worker is released.

**Antigravity.** An item given to `agy` runs the same loop with `agy -p`; because the owner uses it
for emergencies and mechanical work, it is never chosen by default and the page says so on the
picker.

## The page: a command office

One screen, no navigation, read at a glance and from across the room:

- **Top strip**: what needs the owner (count), running now, queued, done tonight, failed; each
  agent with its state (free, running, limited until 04:40); when the queue ends.
- **Running now**: one row per live worker and per interactive session, as today's Sessions rows
  (title, project, ticket, last request, quiet-for warning).
- **Tonight's queue**: the ordered tickets, numbered, each with project, tier, agent and estimate;
  drag to reorder, untick to take out, pause all.
- **Available**: every open map's other tickets grouped by project, each with its state from the
  table above, so "what can I add or take out" is one look. Ticking a blocked ticket's blocker
  pulls both in.
- **Needs you** stays on top of everything, as today: questions with buttons, blocked workers,
  permission prompts.
- **Decided / done**: tonight's results, newest first, with commits.

In chat, `sb_board` shows the same strip and queue, and `sb_queue` adds tickets.

`/sb tonight` becomes: reconcile and size as a job, write `checks`, tick the tickets. Its long Run
section is replaced by a pointer to the queue.

## What stays a model's job

Reconciling a map against the code before a night, sizing, the final review, and rulings. Each is a
**job item** the owner (or `tonight`) queues, so they also run headless, one at a time.

## Settled after a fresh reader's check (my calls, for the owner to overrule)

0. **The agent is chosen per night, not per ticket**, with a per-ticket override: tonight's queue
   has one agent picker (Antigravity never preselected); a single ticket can be sent elsewhere.
1. **Checks and "ready".** `sbmap` gains map-level properties (`sbmap set <map> checks="cmd one; cmd two"`,
   in scope). A ticket is ready when it has a `Done when` and either its own `checks` or the
   map's. A map with no checks runs nothing and the page says "add checks to start".
2. **Starting a worker.** Claude: `CLAUDE_CONFIG_DIR=<agent's dir> claude -p "<brief>"
   --permission-mode auto --model <model> --output-format json`, run in the repo (each flag exists
   in the installed CLI). Antigravity: `agy -p "<brief>" --model <model> --output-format json`.
   **The plan's first task is a spike**: one real ticket through this command, gating the rest.
3. **Linking a worker to its item, with no model in between.** The hub starts the worker with
   `SB_HUB_AGENT=<ticket id>` and `SB_HUB_PARENT=<queue item id>` in its environment; `sbhub hook`
   reads them and reports under that id and parent. The worker never has to report itself.
4. **Where a worker writes.** The hub calls `sbmap run <map>` once per map item; each worker's
   report goes in that run folder as `<NNN>.md`, and the hub keeps the board's log. The contract and
   hard rules are the map's `## Notes` (written by `chart`/`tonight`); the brief points there.
5. **The brief is filled from the ticket alone**: title, why, Question, Done when, Not this ticket,
   paths; its background is the map's `## In plain words`. Nothing in it is model-written.
6. **Tier.** A ticket property `tier` (`sonnet` by default, `opus` when the charting session set
   it). A failed `sonnet` ticket retries once on `opus`; a ticket already on the top tier, or on
   Antigravity, gets no retry.
7. **One writer.** Only the running hub changes the queue; the CLI, the page and `sb_queue` all go
   through it and refuse when it is down. The hub holds each worker's process id; after a restart a
   ticket it had claimed with no live process is released and re-queued.
8. **Concurrency.** The hub starts the first queued ticket whose repo and agent are both free. One
   worker per agent, and one per repo whatever the agent.
9. **Stops.** "The same failure" is no commit, or the same check command failing, on three tickets
   in a row. A limited agent's items idle until its reset; an item's stop time ends it even while
   waiting.
10. **Jobs.** A duplicate is the same project and the same prompt text (by hash) within a day. A
    job's last message and any file it names are saved in the vault at
    `wayfinder/<project>/runs/<date>-<job name>/`; the page links there.
11. **Scope of this build**: the queue in the hub, the page's Queue and Agents sections, `sb_queue`,
    the `sbmap` map properties and `tier`, and the edits to `tonight` and `resume`, the skill text last.

## Left to the builder

State layout, CLI flag names, how the worker process is supervised (subprocess with a process
group and a timeout), the limit-message patterns per agent kind, the digest's wording.

## Not yet proved

- ⚠️ A headless worker in **auto** mode on this machine finishing a real ticket end to end.
- ⚠️ What a headless session prints when it hits a usage limit, per agent kind (the patterns must
  be collected from a real hit; until then a non-zero exit with no commit is "failed").
- ⚠️ Whether hooks and the `sb` skill load in a headless session started by the hub the same way
  (the one headless test ran a plain prompt).
- ⚠️ Antigravity's headless run: quota was exhausted on 2026-11-12, so only its start and stop
  hooks were seen.
- ⚠️ The 28.7k start was measured on Haiku on the personal config; other models and configs may
  differ.
