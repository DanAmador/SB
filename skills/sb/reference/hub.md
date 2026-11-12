# sb hub

The hub (`scripts/sbhub.py`) is a local web page and API that shows what sb sessions are doing. The vault stays the record; the hub never writes into it. This file has two parts: providers (below) and the agent-facing commands (added separately).

## Providers

A provider turns a project's state into widgets for the hub page. For every project that has an agent, the hub runs, about every 15 s (and at once when a new project reports):

1. the generic provider, built in (icon `git`): `Repo and maps` with `Branch`, `Uncommitted files` (level `warn` above 0), `Last commit`, and a `log` of the first 8 lines of `sbmap maps --repo <project>`;
2. then every executable file in `<project>/.sb/providers/`, sorted by name, run with the project as cwd. Symlinks there are skipped.

### Trust

A cloned repo must not get its scripts run just because a session opened in it. Step 2 runs only for projects the owner trusted: `sbhub.py trust <project path>` adds the absolute path to `$SB_HUB_HOME/trusted` (default `~/.sb-hub/trusted`, one path per line) and prints `trusted <path>`; `sbhub.py untrust <path>` removes it. Neither needs the hub running; the hub re-reads the file on each refresh, so a change shows within about 15 s. For an untrusted project that has at least one executable there, the page shows one `Project providers` entry saying `Not trusted yet` (`run: sbhub trust <project>`) and no script runs. A reported `project` that is not an absolute path to an existing directory gets no providers at all.

Providers are optional. A project with no `.sb/providers/` gets the generic one only. Non-executable files there (a README) are ignored.

### Output

A script prints one JSON object on stdout and exits 0:

```json
{"title": "Test suite", "icon": "flask", "widgets": [
  {"kind": "status", "label": "Suite", "value": "green", "level": "ok"}]}
```

- `title`: shown as the section heading; defaults to the file name.
- `icon`: optional short name the page maps to a pictogram: `git`, `tests`, `unity`, `build`, `server`; anything else shows a wrench.
- `widgets`: a list; required.

A script that exits non-zero, prints anything but a JSON object with a `widgets` list of objects (and, if present, a string `title` and `icon`), or runs longer than 120 s shows only its error as a red `provider` status under its file name. It never affects other providers or the hub.

### Widget kinds (the whole vocabulary)

| kind | fields |
|---|---|
| `status` | `label`, `value` (string), `level`: `ok`, `warn` or `bad` |
| `progress` | `label`, `value`, `max` (numbers) |
| `counts` | `label`, `items`: `{name: integer}` |
| `log` | `label`, `lines`: list of strings |

Labels and values are shown to the owner as written: plain words, no internal codes.

### Example

`.sb/providers/tests` in this repo runs the unittest suite and prints a `status`, a `progress`, a `counts` and a `log` widget. Copy it as a starting point; make it executable (`chmod +x`).

The hub serves the latest results in `GET /api/state` as `"providers": {project: [result, ...]}`.
