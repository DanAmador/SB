# sb hub

The hub (`scripts/sbhub.py`) is a local web page and API that shows what sb sessions are doing. The
vault stays the record; the hub never writes into it. Agents use three of its commands; the rest of
this file is providers.

## Report, ask, lock

The hub is optional, and a run reads the same without it: with the hub down, `report` does
nothing, `ask` prints its default, and `lock` and `unlock` exit 2 (`sbhub: not running`): go on
unlocked.

- **`report`**: with the `hub-report` mod (`./install.sh --hub`) a session's state reaches the hub
  on its own. `report` adds what hooks cannot know: a run's progress (`--done`, `--total`), the
  ticket a worker is on (`--ticket`), a ticket session's run (`--parent`). The operator runs it at
  each ticket boundary ([tonight](../verbs/tonight.md) step 6); a ticket session at its start and
  end ([session brief](../templates/session-brief.md)).
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
