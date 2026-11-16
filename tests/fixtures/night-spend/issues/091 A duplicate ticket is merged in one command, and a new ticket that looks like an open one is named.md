---
wayfinder: ticket
operonId: 3718365
number: 91
title: "A duplicate ticket is merged in one command, and a new ticket that looks like an open one is named before it is made"
why: "Duplicates across maps get worked twice, and a placeholder ticket on sk4te cost two worker runs and two reviews doing nothing. After this a merge closes the copy with a pointer to the one that stays, and creating a ticket warns about a lookalike in any map of the repo."
project: sb-workflow
aliases:
  - "#091"
  - "091"
status: Project.Planned
type: task
priority: B
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - skills/sb/scripts/sbmap.py
  - tests/test_tracker.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: Owner, 2026-11-15: "Go through the tickets and make sure there are no redundant tickets, how exactly could we share the knowledge / tasks between maps in a way that they can be self referential ?" ... "another agent is currently working on it as well so it'd be best to have a ticket"

## Not this ticket

Cross-map blocking by number is already fixed (9839664); no change to how blockers resolve or to the hub.

## Question

(1) sbmap resolve <map> <NNN> --merged-into <ref>: sets status out-of-scope, writes '## Answer: merged into [[survivor]]', and appends the dropped ticket's Done when to the survivor as a dated comment; refuses if the survivor is cleared. (2) sbmap new: before writing, compare the title's content words and --paths against every open ticket of the repo's maps (repo_tickets) and print each lookalike with its link on stderr; never refuses. The rules these serve are in wayfinder/sk4te/runs/2026-11-15-ticket-dedupe.

## Done when

A test merges one ticket into another across two maps and finds the survivor's comment and the dropped ticket in done/ with the pointer; a test creates a ticket with the title of an open one in another map and finds the warning naming it. The tracker tests pass.

## Comments

- **2026-11-15**: Half of this ticket is done. Since 415d850 (2026-11-15), sbmap new already refuses a ticket that reads like an open one of the repo (Semantra, cosine 0.5 or more; --not-a-duplicate overrides), which is stricter than the warning asked for here. What is left is part (1) alone: sbmap resolve --merged-into. Ticket dedupe of 2026-11-15, owner: 'Yes, apply them'. Report: wayfinder/sb-workflow/runs/2026-11-15-ticket-dedupe/2026-11-15-ticket-dedupe.md
