You are implementing one ticket in `<repo path>`, branch `<branch>`, unattended. Nobody will answer
a question: when you would ask, take the recommendation, write it in your report as a ruling, and
continue.

## The ticket

<the ticket file's full body, or its path if the brief would exceed ~4k tokens>

## Files you own

<paths>. Other dirty files belong to peers: leave them as they are.

## The contract

<the map's contract block, verbatim>

## Build the least

Before any new file, module or dependency: does it need to exist; does a tool the repo already has
do it; does the stdlib; can it be one line? Take the first that holds. No abstraction with one
user, no scaffolding for later; the shortest working diff wins. A deliberate shortcut gets a
`ponytail:` comment naming its ceiling. Never cut validation, data-loss handling or security.

## Git

Commit only your own paths, by explicit pathspec, when the ticket's checks pass:
`git commit -m "<type>: <imperative>" -m "Ticket: <map folder>/<NNN>" -- <paths>`. Read-only git (`status`, `diff -- <file>`, `log`)
is yours; tree-wide git (`stash`, `checkout`, `reset`, `restore`, `clean`) and `push` are not.
No subagents of your own.

## Done when

<the ticket's Done-when, plus the per-ticket verify commands from the contract, with their output>

## Report (required)

Write `<report path>`: the commit sha, each check run with its result and counts, what you could
**not** verify and why, every ruling you made, files touched. Then reply with its path and a
three-line summary.
