# sb hub

The hub (`scripts/sbhub.py`) is a local web page and API that shows what sb sessions are doing,
plus an MCP face (`scripts/sbhub_mcp.py`, bundled in `mods/hub-report/.mcp.json` for Claude Code
and `mods/hub-report-agy/mcp_config.json` for Antigravity) that renders the same live board and
question buttons directly in chat. The vault stays the record; the hub writes it only through
`sbmap` (claim, comment, resolve, run). Agents use three actions (`report`, `ask`, `lock`); the hub
also holds **tonight's queue** and runs it; the rest of this file is providers.

## Tonight's queue

The owner ticks tickets on the page; the hub orders them, runs each through a headless worker
(`claude -p` in auto mode, no orchestrator session), checks the result in code and records it in
the vault. Only the running hub writes the queue (`$SB_HUB_HOME/state.json`); CLI, page and
`sb_queue` go through its API and refuse when it is down.

- **Ready** only when the ticket's type is `task`, `research` or `prototype`, it has a `Done when`,
  it has checks (its own or its map's), and every blocker is resolved or queued ahead of it. Else it
  shows on the page with its reason: `blocked`, `waits for you` (grilling, architecture),
  `not ready` (no done-when; a ticket with no check commands still runs and the review judges it), `claimed`.
- **Checks**: shell commands, run in the ticket's repo after the worker exits, that all exit 0:
  `sbmap mapset <map> checks="cmd one; cmd two"` on the map, or `sbmap set <map> <NNN> checks="…"`
  on one ticket. The repo's fast loop only: they run once per ticket. Three layers, first found wins:
  the ticket's own, the map's, then the repo's `.sb/checks` (one command per line, `#` lines and
  blanks skipped; the owner agrees it in the design session and it is committed). A Done when item
  no command can check is judged by the reviewer.
  **Test only what the change reaches:** every check gets `SB_CHANGED`, the files the ticket's commit
  changed, one per line. In a repo with a `.codegraph/` index, one `.sb/checks` line runs only the tests
  CodeGraph finds, else the fast suite:
  `t=$(printf "%s\n" "$SB_CHANGED" | codegraph affected --stdin -q 2>/dev/null); if [ -n "$t" ]; then <runner> $t; else <fast suite>; fi`
  **After landing:** a check line starting `after-landing: ` (sk4te: `after-landing: python3
  .sb/checks-compile.py`) runs in the checkout itself, once the ticket's work landed there: a game's
  compile asks the one open Unity, which has the checkout open, never the ticket's worktree. Every
  other line runs before landing, in the worktree, as before. For such a ticket the hub takes the lock
  `unity:<repo folder name>` (chat sessions take the same one with `sb_lock` before they use that
  Unity; the hub waits up to 10 minutes while one holds it, then rechecks later), fast-forwards, runs
  the after-landing lines, and lets go. If one fails, the landing is backed out by **one revert commit**
  that undoes only the ticket's commits and its integrator's (each named on an `Undoes:` line); anything
  else committed meanwhile is kept, and history is never rewritten, the work is replayed on the
  ticket's branch, and the ticket goes back to its worker with the failure in its brief (the one Opus
  retry), so the next ticket lands on a building main. One that exits 75 (Unity did not answer) is
  backed out too and lands again at its recheck. A hub that stops mid-landing keeps the landing in
  the lock; the next hub backs it out, lets go of the lock and lands the ticket again without its
  worker. A ticket that ran in the checkout itself (no worktree) runs the line there like any other.
  **The Unity stage** (a repo with `ProjectSettings/ProjectVersion.txt`): Unity is a ticket's last stage, one
  ticket at a time.
  1. **The worker codes without Unity.** It always runs in its own worktree, and its guard refuses any `unity`
     command (`SB_HUB_UNITY=off`). Its brief asks for a `## Play checks` section in its report.
  2. **The integrator plays it on the checkout.** Once the work lands, the hub keeps the lock `unity:<repo>` and
     starts an integrator (Opus, `templates/integrate.md`) in the checkout. The integrator compiles, plays the
     Play checks, fixes what is broken and commits, then writes `<num>-integrate.md`, which ends in
     `VERDICT: works|broken|no unity`.
  3. **The hub judges when it ends.**
     - **Files Unity changed on its own during Play** are saved to `<num>-unity-leftovers.patch` and restored.
     - **`works`:** the after-landing lines run with the integrator's fixes in, and the ticket is landed when
       they pass.
     - **`broken`, or past its limit:** the whole stage is backed out by one revert, and the worker tries again,
       told the integrator's report.
     - **`no unity`:** the stage is backed out, and the ticket lands again at its recheck.

  **While a stage runs**, every other ticket of that repo waits for the Editor (`waits for Unity`). Waiting costs
  it no try and no recheck. **After a hub restart**, a live integrator is adopted. A stage whose integrator died
  is backed out and lands again. **Stop** on a ticket in its stage backs the stage out.
  **A Unity pass** (`sbhub queue integrate <map> <NNN>...`) is for a failed ticket whose work is already in the
  checkout, for example one judged short because nobody could play it. No worker runs: the integrator takes the
  lock on the checkout as it stands, plays what the review found short and fixes it, and the review judges the
  ticket again. A pass that cannot fix it backs out only its own fixes, and the ticket goes back to the owner.
- **Tier**: `sbmap set <map> <NNN> tier=opus` on a complex ticket; Sonnet when absent. A failed
  Sonnet ticket retries once on Opus.
- **Order**, fixed: after its blockers; then priority S→F; then the ticket that unblocks the most
  queued or available tickets; then map order.
- **Verdict**, in code: a commit with the `Ticket:` trailer and every check green. The ticket's paths
  are where the worker starts, not a fence: a change may edit other files it needs, and the verdict
  names them in the ticket's answer (tests beside owned files are not named). A research ticket that
  made no commit passes on its written report. Workers test in the shared checkout with the editor or
  dev server already running, never a second copy. A check that fails while the repo holds someone else's uncommitted work runs once more on a
  clean copy of the commit (a detached worktree, installed `node_modules` linked in), and passes if it passes there;
  a clean folder never pays for this. Then `sbmap resolve`. Anything else stays open with the reason
  as a comment; the commit is left in place; the repo's next ticket still runs.
- **Workers**: one per repo at a time; a worker past 90 minutes is killed and fails. A new queue
  starts **paused**: nothing runs until the owner (or `tonight`) resumes it.
- **Worker start**: a worker gets the hub's tools (the `mods/hub-report` plugin), the repo's own `.claude`
  settings, skills and `.mcp.json`, and these variables only: PATH, HOME, USER, LOGNAME, SHELL, LANG, `LC_*`,
  TERM, TMPDIR, CLAUDE_CONFIG_DIR, `SB_HUB_*`. Not the owner's connectors, skills, hooks or keys. A repo adds a
  variable by naming it, one per line, in `.sb/env`.
- **Pool and pacing**: the night's agents are a pool (`sbhub queue agents assembio personal`); a
  ticket's own `agent` override pins it. Each Claude worker streams its account's usage (5-hour and
  weekly window, reset times); with nothing running the hub reads it with a one-line Haiku call. A Codex
  account's use is read every 10 minutes from its session files (`$CODEX_HOME/sessions`), for the board's
  Usage panel only: Codex is not paced (`SB_HUB_CODEX_USAGE=0` turns the reads off). Each finished Codex
  ticket's own session file gives its cost (the rise in 5-hour use), averaged per account apart from Claude's,
  so the panel can say how many more Codex tickets fit; before the first it says there is no estimate yet. An
  item starts on the pool agent where it fits whose week resets soonest (then whose five hours reset
  soonest, then the most room), so what is about to expire is spent first: the account's use, plus what its
  running items still need, plus this item's cost (learned per account and tier from finished
  items), stays under 90% of the 5-hour window (a reset before the item would need the rest counts),
  and weekly use is under 80%. Up to 4 workers per account (one per repo still holds); one until its cost is learned. An item
  that fits nowhere waits with a note naming the account, its use and the reset time. At 95% the hub
  tells running workers to commit what passes and stop. A ticket cut off by a limit or a logout
  resumes on another account with room, from where it stopped. An expired login takes that account
  out of the pool and asks the owner to sign in.
- **Sessions**: each Claude worker runs as its own session (`--session-id`); its queue item keeps
  `session` and `session_dir` (the account's config dir). A stop at a limit or a logout, a hub restart
  and the review's one more try go on with that session (`claude -p --resume <id> "<what happened>"`,
  same worktree, same model); on another account its file is copied into that account's `projects/`
  first. A failed try's retry (the Opus one too) starts a new session, told every earlier try's commit
  and the last report. No session kept, its file missing or older than a day, or a resume that ends
  with an error before any turn: the try starts afresh with the whole brief and the old log's path.
- **Review**: a ticket whose checks pass lands (`landed`, with `landed_at`) and waits for its map's Opus
  review, one per map at a time, which judges every landed ticket no review holds. It starts when the map's run
  ends, or, while the map still runs, once its oldest landed ticket waited 25 minutes (`SB_REVIEW_EVERY_MIN`),
  counted from `landed_at` in the queue file, so a restart does not reset it; the map-end review then takes only the
  leftovers. `POST /api/review/now {}` (`sbhub review-now`) starts the review the timer would for every map with
  landed tickets, busy or not, and answers `{ok, started: [maps]}`; a map whose review runs starts nothing new.
  `/api/state`'s `review_next_at` is when the timer next looks (null: nothing waits). No review starts while the
  hub rebuilds its own code. A review running when the hub stops is started afresh, once, by the next hub.
- **In Play lines**: a Done when item that starts `In Play` is checked in the Unity Editor. The worker's brief
  lists it as "played by the review, leave it" and the worker is not judged on it. A map's review whose tickets
  have such lines takes the repo's Unity lock (`unity:<repo>`, held by `sb-hub review <map>`) before it starts,
  plays them on main and records what it saw (numbers, screenshots in `<run>/<num>-media/`); the hub frees the
  lock when it ends, and a restarted hub frees one left over. A review without In Play lines never takes it. While
  someone else holds the lock the review waits, up to 10 minutes; then it starts without it and marks those lines
  `not played yet`, never `not met`. A ticket whose only open items are lines no one played (`not played yet`)
  resolves as **landed, waits for your look**: no redo, no re-queue, `done` on the page with a `look` field (the
  lines and the checklist note). Each such ticket goes on the night's one checklist note for its repo,
  `wayfinder/<repo>/runs/<date>-validate.md` (one checkbox per ticket: what to do in Play and its link); the
  morning note links it under **Play these**. A look that fails: the owner reopens the ticket. A ticket with any other item
  `not met` gets its one more try as before.
- **Jobs**: a one-off prompt for any agent, in a wayfinder project or any git checkout by path
  (`sbhub queue job …`, or the page's New job form). No claim, no verdict: exit 0 is done.

Commands (`scripts/sbhub.py`):

| command | does |
|---|---|
| `queue` | the queue in run order, each item with its state |
| `queue add\|rm <map> <NNN>... [--by <agent id>]` | tick or untick tickets (running and finished items stay); `add --by` puts that session in charge of the map unless another live session is |
| `queue pause\|resume` | hold or release the queue |
| `queue agents <name>...` | the night's pool, in preference order |
| `queue job --project P --agent A [--model M] [--name N] (--prompt T \| --prompt-file F)` | a one-off job |
| `review-now` | start the review of every map with landed, unreviewed tickets, now |
| `agents [--scan]` | installed agents; `--scan` finds `~/.claude*` configs and `agy` |

In chat: `sb_queue(add=["<map>#<num>"], remove=[…])` returns the queue as a few lines;
`sb_board`'s text carries `queue: N queued, M running, ends about HH:MM`.

## The board and the phone page

The hub page (`http://127.0.0.1:8765/`) is a kanban board that redraws itself every few seconds, keeping
scroll, the open panel and half-typed text. Above it: the counts, one chip per account (5-hour use, reset
time, sign-in state), one chip per project (its repo, Unity and provider widgets open in the side panel), and
filters (project, map, text) kept in the page link. Columns:

| column | holds |
|---|---|
| Needs you | open questions, sessions that need you, signed-out accounts, grilling and architecture tickets (their options as buttons, the recommended one filled, and a line for your own answer) |
| Ready | what can be queued, by project then map; the rest of the open tickets folded underneath |
| Queued | tonight's order: drag to reorder, drag back to Ready to untick (or a card's menu) |
| Running | queue workers and the sessions you run by hand ("yours"), each with its latest step |
| Done | every finished item of the last 7 days, newest first: commit, checks, self-checks, report and log |
| Failed | failed and skipped items with the reason; Tick again queues one afresh |

Dragging a Ready card into Queued queues it (and what it waits on). Dismiss and Clear quiet
sessions take rows off the board without stopping anything. A card opens a side panel: why, done when, paths,
checks, comments, its map's handoff, checkpoint and newest run board, Open in Obsidian links (`sbmap uri`), and
the actions Done, Drop, Release, Comment, Tier and the map's Checks, each confirmed and each run through
`sbmap` (`GET /api/ticket?key=`, `POST /api/ticket/<action>`); a ticket a queue worker is running refuses them,
and a failed `sbmap` shows its own message.

A worker whose change shows on screen looks at its own screenshots or short clips before it commits and
leaves them in `<run folder>/<num>-media/` (the brief's rule: png, jpg, gif, webp, mp4 or webm, at most 6,
each under 8 MB). When the item ends, done or failed, the hub records their names; its Done or Failed card
shows up to 3 thumbnails and the side panel shows all of them, videos with controls. The files come only from
`GET /api/media?key=<item>&name=<file>`, which serves a name the item recorded from that folder alone (with
byte ranges, so a phone plays the clips) and answers anything else with an empty 404.

**Phone page.** `python3 scripts/sbhub_lan.py serve` (port 8766, every interface; the `sb-hub-lan` entry in
`.claude/launch.json`) serves the same page read-only to a phone on the WiFi: `sbhub_lan.py url` prints its
address, `http://<the machine's WiFi address>:8766/v/<token>/`. The token (32 characters, `$SB_HUB_HOME/lan-token`)
is in every path; without it every path answers an empty 404. It forwards reads under `/api/` to the hub and
only the writes that change display state: dismiss, clear quiet sessions. Every other write answers
403, and the page hides its controls.

## Nights

A night is one sb tonight: `id`, `name` (default `Night of 2026-11-14, 22:45`), `started`, `by`, `state` (`live`,
`stopping`, `ended`), `ended`, `how` (`finished`, `stopped`, `stop_time`), `counts` and, after a stop, `not_reached`.
Every queue item carries its night's `night` id; at most one night is live. Queueing only fills the queue: with no
night live an item waits for Start (waits kind `start`), and nothing runs until the owner presses **Start run** on the
board or a chat runs `POST /api/night/start {name?, by?, drain?}` (`sbhub night start [--name] [--drain]`), which
opens a night and takes in everything waiting; everything queued while it is live joins it. A second start is refused
(400). A night started from the board or a chat ends only on Stop. A `--drain` night (what `tonight` starts) also
ends by itself: when its last item has ended and been judged it ends as `finished`; its items leave the live line for the night's own record (outcome, commit, report,
review links), so nothing is cleared by hand. `POST /api/night/stop {mode: "after"}` (`sbhub night stop`) starts
nothing new, lets what runs finish and be judged, then ends the night as `stopped`; the tickets it never reached
leave the line, stay open and not queued, and are listed on the night as `not_reached` (queuing while it stops is
refused). A night whose queue stop time passes ends as `stop_time`. `GET /api/nights` lists nights newest first with
counts; `GET /api/night?id=` gives one with its items. A queue saved before nights loads as one ended night, `Before
runs`, plus a live night for what was queued or running. The final review and the run note belong to the live night.

## Running it unattended

A hub started from a terminal or an app session stops when that session does, and its workers with
it (one night's queue lost two hours that way). For a night, run it as macOS background services:
`scripts/sbhub_service.sh install` writes two LaunchAgents, `com.sb.hub` (the hub, under `caffeinate
-i`, so the Mac does not idle-sleep while it runs; closing the lid on battery still sleeps) and
`com.sb.hub-lan` (the phone page; `--no-lan` leaves it out), and starts them. Each restarts within
10 s when it exits and starts again at login. PATH, `SB_HUB_HOME`, `SB_VAULT` and `SB_CODE` come from the shell
that ran install: run it again after those change.

On Linux the same command writes systemd user units to `~/.config/systemd/user` instead: `com.sb.hub`
and `com.sb.hub-lan` with the same restart, environment, take-over and log behaviour
(`KillMode=process` keeps the workers across restarts), plus `com.sb.hub-awake`, a `systemd-inhibit`
idle and sleep lock in place of `caffeinate` that stops with the hub. logind grants that lock only to a
logged-in user, so before login it retries every minute. `--linger` runs `loginctl enable-linger`:
the units then start at boot and keep running after logout; without it they start at login. Desktop
notifications use `notify-send`.

- A hub already on port 8765 makes install stop; `--take-over` kills only that hub's own process,
  and the new hub adopts its running workers (*started before the hub restarted*). Re-running
  install on the service keeps the workers the same way.
- `status` prints each service's state; `uninstall` stops the hub normally, which ends its running
  workers, and removes both.
- Logs: `$SB_HUB_HOME/com.sb.hub.log` and `com.sb.hub-lan.log`.
- To keep one account out of a night, set the pool without it (`sbhub queue agents assembio`); an
  item already running there finishes.

## The night on the phone

While `serve` runs the queue it keeps one note, `wayfinder/runs/hub-now.md`, in the vault: when it was written
and whether the queue is running, paused or empty; then a block per map with something running, queued or
ended today (counts, the running tickets with minutes and last step, the next ones, the ended ones with their
outcome and reason, each a wikilink); last, what waits for you. It is rewritten whole (a hidden temp file,
then a rename) on every start and end and at most every 5 minutes while something runs, and only when its
text changed apart from the time, because Obsidian Sync uploads every change and keeps old versions against
a 1 GB limit. Sync uploads only while Obsidian is open on the Mac.

## Chat widgets (MCP)

When the `sbhub` MCP server is connected (`./install.sh --hub`):

- **`sb_board`**: call once to show the owner the live board widget in chat; do not repeat its
  contents in prose.
- **`sb_ask`**: multiple-choice buttons in chat and on the hub page. In an interactive chat, leave
  `block_seconds=0` and end your turn so the owner's click arrives as their next message. In a
  subagent or unattended run, pass `block_seconds=600` (or use `sbhub.py ask`).
- **`sb_report`**, **`sb_lock`**, **`sb_unlock`**: same semantics as the CLI below; calling
  `sb_report` as an orchestrator aliases the session just like `sbhub.py report`.
- **`sb_join`**, **`sb_leave`**: join the live run as `integrator` or `implementer`, or leave it
- **`sb_take`**, **`sb_done`**: a joined chat builds a queued ticket itself in its own worktree, then says it is built
  (see *Joining a run*).

## Joining a run

The board shows a chat only once it joins the live run; the hub drops hook events from chats that never joined
(queue workers, and the helpers of a joined chat or worker, are always kept). `sb_join(agent, role)`,
`POST /api/run/join {agent, role}` or `sbhub night join --agent X --role integrator|implementer` joins; the call also
aliases the session to `X`, like `report`. Any number of chats may join, in either role; joining again changes the
role. A joined row carries `joined: {night, role, at}`. `sb_leave` / `sbhub night leave --agent X` leaves, and a run
that ends unjoins its chats. Joining needs a live run (400 otherwise). Only a joined chat keeps `chat_runs`.

### A finished ticket goes to its chat

A queue item records the chat that queued it (`by`, from `sb_queue` `agent` or `--by`). When a worktree ticket's
checks pass and a chat is joined, the hub does not land it: it rebases it onto the checkout's newest commit, runs its
checks there in its worktree and hands it over (state `handed`, `handed: {to, at}`, "To integrate · chat" on the
graph). It goes to the chat that queued it while that chat is joined (either role), else to the joined integrator
with the fewest tickets waiting (the earliest to join first); with no chat joined the hub lands it and its map's Opus
review judges it, as before. A handed ticket keeps its map current, so the map's review and the run's end wait for it.

The chat runs `sbhub watch --chat <id>` in the background: it exits 0 with each ticket handed to that chat, its
commit, branch and worktree and the two commands below, which wakes the chat; 3 when the chat has joined no live
run. The chat reviews the branch, then `sb_integrate(agent, key, action)` / `POST /api/run/integrate` /
`sbhub integrate <key> land|back --agent <id> [--note N]`:

- `land`: the hub lands it at its next tick under the repo's landing lock (`land:<repo folder>`; a chat that lands
  by hand takes it with `sb_lock` first, and the hub waits for it), then resolves the ticket as the chat's review: no
  Opus review follows. One that cannot land yet goes back to the chat; a failed landing is a try, as for a worker.
- `back` (a note is required): it is queued again at the front as its next try, the worker told the note.

A chat that leaves hands its waiting tickets to the next integrator, or, with none, to the hub, which lands them.

### A chat builds a ticket itself

A joined chat can take a queued ticket of the live run instead of leaving it to a worker:
`sbhub.py take KEY --agent <chat>` (`sb_take`). The hub makes the ticket's own worktree and branch, claims
it as `hub chat <chat>`, starts no worker for it, and prints the brief a worker would get. Build and commit
only in that worktree, never in the repo's main folder. A ticket a worker already runs is refused.

When it is built, `sbhub.py done KEY --agent <chat>` (`sb_done`). The hub runs its checks as it would a
worker's: passed, it goes to the run's integrator, or, with none joined, lands the hub's way and its map's
review judges it. Failed, it comes back to the chat with why, its work kept and no try spent; `done` prints
that and exits 4, and `watch` wakes the chat for it. A chat that leaves gives its ticket back to the queue,
and the worker that takes it goes on in the chat's worktree. The owner's Stop ends it, its work kept.

## Report, ask, lock

The hub is optional, and a run reads the same without it: with the hub down, `report` does
nothing, `ask` prints its default, and `lock` and `unlock` exit 2 (`sbhub: not running`): go on
unlocked.

- **`report`**: with the `hub-report` mod (`./install.sh --hub`) a session's state reaches the hub
  on its own. `report` adds what hooks cannot know: a run's progress (`--done`, `--total`), the
  ticket a worker is on (`--ticket`), a ticket session's run (`--parent`), and the map this session is in charge of (`--map <project>/<map>`; `sb_report` takes `map`). The operator reports its map and queues with `--by` (`sb_queue` `agent`) so the page can say who runs a map; the hub drops the charge when the session ends or is dismissed, and a queue worker's row shows its `map` and `in_charge`. Queue workers need
  none of it: the hub knows what it started. An operator without the hub runs it at each ticket
  boundary ([tonight](../verbs/tonight.md), *No hub*).
- **`ask`**: see [output.md](output.md), *Unattended*.
- **`lock <name> --by <agent>`**, then **`unlock`** with the same arguments: a resource one agent
  may use at a time (the Unity editor, a port). Prints `ok`, or exits 1 `held by <who>`: do the
  work that needs no lock, then try again while the holder is still listed in `sbhub state`; after
  ~5 minutes, report yourself `--state blocked`. A holder no longer listed loses the lock 10 minutes
  after taking it: wait for the hub to drop it, or the owner clears it with `sbhub unlock <name> --by
  <holder>`. Tickets are never locked here: `sbmap claim` holds its own lock and exits 3 when it
  cannot get it in 5 s.

## Providers

A provider turns a project's state into widgets for the hub page. For every project that has an
agent, the hub runs, about every 15 s (and at once when a new project reports):

1. the generic provider, built in (icon `git`): `Repo and maps` with `Branch`, `Uncommitted files`
   (level `warn` above 0), `Last commit`, and a `log` of the first 8 lines of `sbmap maps --repo
   <project>`;
2. then every executable file in `<project>/.sb/providers/`, sorted by name, run with the project as
   cwd. Symlinks there are skipped.

### Trust

A cloned repo must not get its scripts run just because a session opened in it. Step 2 runs only for
projects the owner trusted: `sbhub.py trust <project path>` adds the absolute path to
`$SB_HUB_HOME/trusted` (default `~/.sb-hub/trusted`, one path per line) and prints `trusted <path>`;
`sbhub.py untrust <path>` removes it. Neither needs the hub running; the hub re-reads the file on
each refresh, so a change shows within about 15 s. For an untrusted project that has at least one
executable there, the page shows one `Project providers` entry saying `Not trusted yet` (`run: sbhub
trust <project>`) and no script runs. A reported `project` that is not an absolute path to an
existing directory gets no providers at all.

Providers are optional. A project with no `.sb/providers/` gets the generic one only. Non-executable
files there (a README) are ignored.

### Output

A script prints one JSON object on stdout and exits 0:

```json
{"title": "Test suite", "icon": "tests", "widgets": [
  {"kind": "status", "label": "Suite", "value": "green", "level": "ok"}]}
```

- `title`: the tooltip on the provider's row (its icon); defaults to the file name. The heading
  above the rows is the project's folder name.
- `icon`: optional short name the page maps to a pictogram: `git`, `tests`, `unity`, `build`,
  `server`; anything else shows a wrench.
- `widgets`: a list; required.

A script that exits non-zero, prints anything but a JSON object with a `widgets` list of objects
(and, if present, a string `title` and `icon`), or runs longer than 120 s shows only its error as a
red `provider` status under its file name. It never affects other providers or the hub.

### Widget kinds (the whole vocabulary)

| kind | fields |
|---|---|
| `status` | `label`, `value` (string), `level`: `ok`, `warn` or `bad` |
| `progress` | `label`, `value`, `max` (numbers) |
| `counts` | `label`, `items`: `{name: integer}` |
| `log` | `label`, `lines`: list of strings |

Labels and values are shown to the owner as written: plain words, no internal codes.

### Example

A script that prints one `status` widget:

```python
#!/usr/bin/env python3
import json
print(json.dumps({"title": "Build", "widgets": [{"kind": "status", "label": "Last build", "value": "green", "level": "ok"}]}))
```

Keep it fast: the hub runs it on every refresh and stops it, with whatever it started, after 120 seconds.
Never run a long job such as a test suite from it. Make it executable (`chmod +x`).

The hub serves the latest results in `GET /api/state` as `"providers": {project: [result, ...]}`.
