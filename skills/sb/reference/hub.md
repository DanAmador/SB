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
  `not ready` (no done-when, no check commands), `claimed`.
- **Checks**: shell commands, run in the ticket's repo after the worker exits, that all exit 0:
  `sbmap mapset <map> checks="cmd one; cmd two"` on the map, or `sbmap set <map> <NNN> checks="…"`
  on one ticket. The repo's fast loop only: they run once per ticket.
- **Tier**: `sbmap set <map> <NNN> tier=opus` on a complex ticket; Sonnet when absent. A failed
  Sonnet ticket retries once on Opus.
- **Order**, fixed: after its blockers; then priority S→F; then the ticket that unblocks the most
  queued or available tickets; then map order.
- **Verdict**, in code: a commit with the `Ticket:` trailer, every commit since the base inside the
  ticket's paths, every check green. Then `sbmap resolve`. Anything else stays open with the reason
  as a comment; the commit is left in place; the repo's next ticket still runs.
- **Workers**: one per repo at a time; a worker past 90 minutes is killed and fails. A new queue
  starts **paused**: nothing runs until the owner (or `tonight`) resumes it.
- **Pool and pacing**: the night's agents are a pool (`sbhub queue agents assembio personal`); a
  ticket's own `agent` override pins it. Each Claude worker streams its account's usage (5-hour and
  weekly window, reset times); with nothing running the hub reads it with a one-line Haiku call. An
  item starts on the pool agent where it fits with the most room: the account's use, plus what its
  running items still need, plus this item's cost (learned per account and tier from finished
  items), stays under 90% of the 5-hour window (a reset before the item would need the rest counts),
  and weekly use is under 80%. Up to 2 workers per account; one until its cost is learned. An item
  that fits nowhere waits with a note naming the account, its use and the reset time. At 95% the hub
  tells running workers to commit what passes and stop. A ticket cut off by a limit or a logout
  resumes on another account with room, from where it stopped. An expired login takes that account
  out of the pool and asks the owner to sign in.
- **Jobs**: a one-off prompt for any agent, in a wayfinder project or any git checkout by path
  (`sbhub queue job …`, or the page's New job form). No claim, no verdict: exit 0 is done.

Commands (`scripts/sbhub.py`):

| command | does |
|---|---|
| `queue` | the queue in run order, each item with its state |
| `queue add\|rm <map> <NNN>...` | tick or untick tickets (running and finished items stay) |
| `queue pause\|resume` | hold or release the queue |
| `queue agents <name>...` | the night's pool, in preference order |
| `queue job --project P --agent A [--model M] [--name N] (--prompt T \| --prompt-file F)` | a one-off job |
| `agents [--scan]` | installed agents; `--scan` finds `~/.claude*` configs and `agy` |

In chat: `sb_queue(add=["<map>#<num>"], remove=[…])` returns the queue as a few lines;
`sb_board`'s text carries `queue: N queued, M running, ends about HH:MM`.

## Chat widgets (MCP)

When the `sbhub` MCP server is connected (`./install.sh --hub`):

- **`sb_board`**: call once to show the owner the live board widget in chat; do not repeat its
  contents in prose.
- **`sb_ask`**: multiple-choice buttons in chat and on the hub page. In an interactive chat, leave
  `block_seconds=0` and end your turn so the owner's click arrives as their next message. In a
  subagent or unattended run, pass `block_seconds=600` (or use `sbhub.py ask`).
- **`sb_report`**, **`sb_lock`**, **`sb_unlock`**: same semantics as the CLI below; calling
  `sb_report` as an orchestrator aliases the session just like `sbhub.py report`.

## Report, ask, lock

The hub is optional, and a run reads the same without it: with the hub down, `report` does
nothing, `ask` prints its default, and `lock` and `unlock` exit 2 (`sbhub: not running`): go on
unlocked.

- **`report`**: with the `hub-report` mod (`./install.sh --hub`) a session's state reaches the hub
  on its own. `report` adds what hooks cannot know: a run's progress (`--done`, `--total`), the
  ticket a worker is on (`--ticket`), a ticket session's run (`--parent`). Queue workers need
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

`.sb/providers/tests` in this repo is an example: it runs the unittest suite and prints a `status`,
a `progress`, a `counts` and a `log` widget. It reruns only when `HEAD` or `git status` changed
since its last run, and otherwise reprints the cached result. Copy it as a starting point; make it
executable (`chmod +x`).

The hub serves the latest results in `GET /api/state` as `"providers": {project: [result, ...]}`.
