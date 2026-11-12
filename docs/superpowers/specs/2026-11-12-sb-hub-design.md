# sb hub: one local server for every agent session

Status: approved by the owner, 2026-11-12. Built behind tests in `skills/sb/scripts/sbhub.py`; the
throwaway spike that proved the parts is gone.

## Intent

The owner runs several orchestrators at once and today must open each conversation to learn its
state or answer it. The hub makes the work more autonomous: one page shows every session, and a
session reaches the owner only for a real question, always as multiple choice, in one place.

## Goals

1. **One overview** of every Claude Code session and its workers, with no model tokens spent on it.
2. **One inbox.** Real questions arrive in a single list, multiple choice, default marked.
3. **Autonomy.** A question never stalls a run: its default applies after a wait and is recorded.
4. **A real lock.** Two agents can never hold the same ticket.
5. **Providers.** A project adds its own state (Unity editor, test runner) with a small script.

Non-goals (now): chat widgets, remote or multi-user access, a database, replacing the vault.
Anti-goals: agents spending tokens to report; a second source of truth beside the vault; a page
the owner must watch.

## Approaches

| | approach | trade-off |
|---|---|---|
| ✅ picked | One local server; a web page first, chat widgets (MCP) later as a second face | two steps; nothing inside chat at first |
| | Chat widgets only | a widget lives in one chat, so no home for "all agents"; unproven for local servers in this app |
| | Web page only, no server-side lock or tools | leanest, but no lock and no cheap status call |

Python, standard library only, as `sbmap` is (owner, 2026-11-12: no Rust).

## Parts

**Server** (`skills/sb/scripts/sbhub.py serve`, 127.0.0.1 only). Holds live state in memory and a
small file under `~/.sb-hub/`; the vault stays the record. Endpoints: report, lock, unlock, ask,
answer, state.

**Reporting from Claude Code, free of tokens.** A mod (`mods/hub-report/`) registers hooks that
pipe each event to `sbhub hook`: session start and end, each tool call, a permission or idle
notice, turn end, subagent start and stop. A hook never blocks or fails its session (proved: bad
input and a stopped hub both exit 0).

**Two kinds of agent, two displays.**

| | orchestrator (a session) | worker (a ticket session or subagent) |
|---|---|---|
| shown as | a card | a row inside its orchestrator's card |
| says | state, queue progress (done/total), current note, its open questions | ticket, last action, age, done with its commit |
| source | hooks, plus `sbhub report --done --total` at each ticket boundary | hooks for subagents; the orchestrator's `--parent` for ticket sessions |

A session silent for 10 minutes fades. "Needs you" (a permission prompt, a block) rises to the top.

**Questions.** `sbhub ask --q … --options "a|b|c" --default a --wait <s>`: always two to four
choices, in the owner's words (the skill's Plain words rule), the default first. The owner clicks
on the page; the waiting command prints the choice. On timeout the default applies and is listed
under *Decided* as "by default", and the agent writes it on the ticket as `R: …` (the contract's
existing rule). One macOS notification per question or "needs you" change.

**Lock.** Two kinds. *Tickets:* `sbmap claim` does its read-check-write under a kernel lock
(`flock`) on a file in the map's folder, so the vault alone prevents a double claim and the hub is
not needed for it (simpler than the first draft, which asked the hub first). *Shared resources*
only one agent may use at a time (the Unity editor, a port): `sbhub lock <name> --by <agent>`,
shown on the page.

**Providers.** The generic one ships in the skill: branch, uncommitted files, last commit, the
repo's maps. A project adds executables in `<repo>/.sb/providers/`; each prints
`{"title", "widgets": [...]}` with kinds `status`, `progress`, `counts`, `log`. Optional; a failing
provider shows its error and harms nothing. The hub runs a project's own scripts only once the
owner trusted it (`sbhub trust <path>`); until then the page says so and none runs.

**One row per session.** A session that runs `sbhub report --agent X` is X: the hook event of that
Bash call aliases the session to X, so its later events and its subagents land on X's row, and its
`SessionEnd` removes X.

**Lock expiry.** A shared-resource lock whose holder is no longer listed is dropped 10 minutes after
it was taken; the owner can clear one sooner with `sbhub unlock`.

**Idle is not needs you.** An idle prompt makes a session "your turn", with no notification; only a
permission prompt or a block is "needs you".

**Skill changes.** `tonight`, `resume` and the session brief gain: report at each ticket boundary,
ask through the hub. Claims stay with `sbmap claim`. `output.md` names the hub as where questions
go.

## Left to the builder

Port and file names; how provider results are cached; the page's styling; test layout.

## Not yet proved

- ⚠️ The hook events against a live session (tested with hand-written events only).
- ✅ An answer that arrives after its question timed out is ignored: the default stands (settled
  on this branch).
- ⚠️ Reaching the page from a phone (the server listens on this machine only).
- ⚠️ Chat widgets from a local server in the Code tab (the later, second face).
