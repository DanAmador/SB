# The contract

The **contract** is the set of rules one run works under: how it commits, what it tests, how many
lanes, what to do when blocked. The owner works in several repos whose rules differ on purpose
(a Unity repo's gameplay tests take too long to run per ticket; a web repo's suite is cheap), so
the contract is **resolved per run, never assumed**, and written down where the next session finds it.

## Resolve it, narrowest source first

1. The map's `## Notes`, its contract block (a night run writes one there: [templates/launch-contract.md](../templates/launch-contract.md)).
2. The handoff or checkpoint in the vault, if this run continues one.
3. The repo's `AGENTS.md` / `CLAUDE.md`, and its project memory.
4. The owner's defaults below.

A narrower source overrides a wider one. Where two sources at the same level disagree, the newer
dated ruling wins; say which you applied in one line.

- A map whose Notes adopt another map's contract ("the night-run contract of `../x/map.md`
  applies") has that contract as its own.
- On tracker and workflow matters (where maps live, how tickets resolve), the vault README and the
  map beat the repo's `AGENTS.md`, which may predate the vault.
- A contract that no longer fits the tree (its branch is not the current one, a newer owner ruling
  contradicts it) is a proposal question, defaulting to the current branch under the contract's
  other rules.

## The owner's defaults

Each line is a ruling the owner has repeated across sessions; the reason sits beside it.

- **Commit per ticket, by explicit pathspec** (`git commit -- <paths>`). A shared index has swept a
  peer's work into a commit before. Never push. Never merge into `main` without asking.
- **Every ticket's commit carries a trailer** `Ticket: <map folder>/<NNN>`, so reconciliation can
  grep the log. A bare `#NNN` would point at the wrong GitHub issue for local-only numbers.
- **Tests are per project.** Per ticket, run the repo's *fast* loop (compile, unit, smoke, the
  category the change touches). Run the *slow* suite once, at the end of the run, or not at all where
  the repo says so. A gameplay suite is slow; a web unit suite is usually fast. The repo's
  instructions name which is which; when they are silent, ask in the proposal.
- **Main tree, serial by default.** Worktrees only when the owner asks: changes in another folder are
  invisible to him. **Lanes** (parallel implementers) only on disjoint file sets, **max 2 at a time,
  reviewers and researchers counted**: that is the token budget.
- **Every dispatch carries the git guardrails:** commit only your own paths; tree-wide git
  (`stash`, `checkout`, `reset`, `restore`, `clean`) is off limits because the stash and index are
  repo-global and one call wipes every peer. Write a `git diff > <outside-repo>.patch` snapshot
  between waves so a wipe is recoverable.
- **Unattended means unattended.** Questions go in plain text, each with the default it falls back
  to, and the default is applied at once. A question card blocks the session until the owner wakes.
- **Blocked on a decision:** take the recommendation, write it on the ticket as a ruling ("R: …,
  cost if wrong: …"), keep going. Blocked on the world (Editor dead, service down): finish the
  tickets that need no live check, and list the unverified ones.
- **Findings go on the ticket** (`## Answer`), not into new markdown files in the repo.
- **Delete, don't rewrite,** a test that fails only because a tuned number moved. Feel and the
  owner's playtest outrank a green suite.
- **Size in commits, not lines:** about 1.5 h per commit of this repo's own history, and a 45 to 65
  minute floor per ticket once its gates run.

## Where it ends up

When a run launches, the resolved contract is written into the map's Notes from
[templates/launch-contract.md](../templates/launch-contract.md), dated. Every implementer brief
quotes it. A later ruling edits that block in place, never a second copy.
