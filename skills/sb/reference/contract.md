# The contract

The **contract** is the rules one run works under: how it commits, what it tests, how many lanes,
what to do when blocked. The owner's repos differ on purpose (a Unity repo's gameplay tests are too
slow to run per ticket; a web suite is cheap), so it is **resolved per run, never assumed**.

## Resolve it, narrowest source first

1. The map's `## Notes` contract block (a night run writes one: [templates/launch-contract.md](../templates/launch-contract.md)).
2. The handoff or checkpoint this run continues.
3. The repo's `AGENTS.md` / `CLAUDE.md` and project memory.
4. The owner's defaults below.

A narrower source overrides a wider one; at the same level the newer dated ruling wins. Say which
you applied in one line.

- Notes that adopt another map's contract ("the night-run contract of `../x/map.md` applies") make it this map's.
- On tracker matters the vault README and the map beat a repo's `AGENTS.md`, which may predate the vault.
- A contract that no longer fits the tree (another branch, a newer ruling against it) is a proposal
  question, defaulting to the current branch under its other rules.

## The owner's defaults

Each is a ruling the owner has repeated; the reason sits beside it.

- **Commit per ticket, by explicit pathspec** (`git commit -- <paths>`): a shared index once swept a
  peer's work into a commit. Never push; never merge into `main` without asking.
- **Trailer `Ticket: <map folder>/<NNN>`** on every ticket's commit, so reconciliation can grep the
  log; a bare `#NNN` would point at the wrong GitHub issue.
- **Tests are per project.** Per ticket, the repo's *fast* loop (compile, unit, smoke, the category
  touched); the *slow* suite once at the end, or never where the repo says so. The repo names which
  is which; when silent, ask in the proposal. While lanes share a machine, per ticket runs only the
  ticket's own test files plus the touched packages' typecheck: two full suites at once fail on
  timeouts, not on the code.
- **Prefer Sonnet; Opus for complex work.** Opus charts, grills, orchestrates, decides architecture and
  runs the final review, and implements the tickets the orchestrator judges complex
  ([models.md](models.md)) or that failed once on Sonnet; Sonnet builds the rest. Dispatch the `implementer` (Sonnet) and `scout` (Haiku) agents; any other dispatch
  names its `model:`. In October 84% of the owner's tokens ran on Opus, subagents included.
- **Hand off at ~150k context**: finish the step in flight, `/sb handoff`, continue fresh. Three
  quarters of October's input tokens were spent past 200k. One ticket per implementer context.
- **CodeGraph first.** In a repo with `.codegraph/`, `codegraph_explore` before grep, `cat` or Read,
  and read by line range. October: 172 CodeGraph calls against ~34,000 grep/cat/Read.
- **Main tree, serial by default.** Worktrees only when the owner asks: changes in another folder are
  invisible to them. **Lanes** only on disjoint paths, as `sbmap lanes` splits them, **max 2 agents at
  once, reviewers and researchers counted**: that is the token budget. Every session sharing the
  usage counts, the owner's own included; the owner may raise the cap at "go".
- **Usage gate: past 90% of the 5-hour window, finish the ticket in flight and start nothing new
  until it resets.** It spreads the night's tokens and leaves the owner's sessions room. Every
  session sharing the budget follows it.
- **The owner's live services are theirs.** A dev server, store, library or vault they run is never
  written: a lane that needs one starts its own on throwaway data and stops it after. One left
  running for visual checks is read-only.
- **Git guardrails:** commit only your own paths; tree-wide git (`stash`, `checkout`, `reset`,
  `restore`, `clean`) is off limits, because the stash and index are repo-global and one call wipes
  every peer. The `implementer` agent carries this; any other dispatch quotes it. Write a
  `git diff > <outside-repo>.patch` snapshot between waves so a wipe is recoverable.
- **Unattended means unattended.** Questions go in plain text with their default, applied at once;
  a question card blocks the session until the owner wakes. **Blocked on a decision:** take the
  recommendation, write it on the ticket as `R: …, cost if wrong: …`, keep going. **Blocked on the
  world** (Editor dead, service down): finish what needs no live check, list the unverified rest.
- **Stay inside the ticket.** Its `why` is the goal, its `Not this ticket` the edge. Neighbouring
  work becomes a ticket (`capture`), never part of this commit: the owner has reverted whole lanes
  that pulled a neighbour in.
- **Findings go on the ticket** (`## Answer`), not into new markdown files in the repo.
- **Delete, don't rewrite,** a test that fails only because a tuned number moved. Feel and the
  owner's playtest outrank a green suite.
- **Size in commits, not lines:** about 1.5 h per commit of this repo's history, and a 45 to 65
  minute floor per ticket once its gates run.

A run writes the resolved contract into the map's Notes, dated; later rulings edit that block in
place, never a second copy. Every implementer brief quotes it.
