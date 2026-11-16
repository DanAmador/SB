---
wayfinder: ticket
operonId: 8b6b956
number: 127
title: "Finished work goes onto one branch, never into stashes or loose folders"
why: "Today the hub copies each finished ticket straight into the folder you and other chats edit in; any unsaved edit there makes it fail, and its work is left on a side branch in a hidden folder. On 2026-11-16 four finished tickets were stranded that way, and sk4te's folder held a hand-made second copy of one of them. After this every finished ticket ends up on one branch you own, and your folder never blocks it."
project: sb-workflow
aliases:
  - "#127"
  - "127"
status: Project.Planned
type: architecture
priority: C
tier: opus
check: tests
created: 2026-11-16
filed_during: "Night of 2026-11-15, 15:22"
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/architecture
---
> Owner, 2026-11-16: "the review should land any tickets into the brain session branch, because right now a lot is being lost in stashes and worktrees, it's become a mess" and "i think this workflow has been a mess so far what's the best option ?"

## Not this ticket

Reviews, checks and the worker's own private folder stay as they are; only where passed work goes changes.

## Question

Where should a finished ticket's work go so nothing is stranded? Today it is copied into your project folder and fails when that folder has unsaved edits; the fix being built now makes it wait for you instead, so nothing lands overnight while edits sit there. A night branch would sit in a folder only the hub uses: every ticket lands there and is checked there, and in the morning one merge brings the whole night into your branch, with any clash shown to you once.

## Options

- ➡️ A night branch in the hub's own folder; one merge into your branch each morning, clashes shown once (about 2 sessions)
- Keep landing into your folder, and the hub waits while it has unsaved edits (being built now; nothing else changes)
- Each finished ticket opens its own pull request; you merge them (about 1 session, many merges)

## Done when



## Comments
