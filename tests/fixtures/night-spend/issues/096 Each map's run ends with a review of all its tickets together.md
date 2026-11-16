---
wayfinder: ticket
operonId: 906243a
number: 96
title: "Each map's run ends with a review of all its tickets together"
why: "The review of each ticket passed nearly everything on 2026-11-15; only the morning review across all tickets found the 12 that are partly done, hours after the night ended."
project: sb-workflow
aliases:
  - "#096"
  - "096"
status: Project.Planned
type: task
priority: C
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - skills/sb/scripts/sbhub.py
  - skills/sb/templates
  - tests/test_hub_runner.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: file them (the retro's fixes), onto night-spend

## Question

When a map's second pass ends, the hub runs one more review over all the map's landed tickets together, with the final review's brief: how the tickets fit, and each one against what the real hub produces. Its findings go on the run board and as one comment per affected ticket; it closes or reopens nothing. The night retro of 2026-11-15 (wayfinder/sb-workflow/runs/2026-11-15-night-retro/retro.md) has the evidence.

## Done when

1. A test: a map of two landed tickets gets one cross-ticket review after its second pass, before the next map starts.
2. Its findings land on the run board and as a comment on each ticket it names.
3. It changes no ticket's status.
4. Every check exits 0.

## Comments

- **2026-11-15**: Build this inside the review that already runs when a map's run ends (080's one Opus session per map), not as a second session after it: that session already holds every landed ticket of the map, so the cross-ticket findings are one more section of its brief and output. One Opus start per map instead of two. Ticket dedupe of 2026-11-15, owner: 'Yes, apply them'. Report: wayfinder/sb-workflow/runs/2026-11-15-ticket-dedupe/2026-11-15-ticket-dedupe.md

- **2026-11-16**: 2026-11-16: the owner ruled that finished tickets are reviewed every 25 minutes (ticket 125) and the review at a map's end covers only what the timer has not, so no ticket is reviewed twice. A cross-ticket section here would then see only the leftovers; the owner turned down a second full review at the map's end ('catches clashes, costs a second review'). Re-scope or close this when 125 is built.

- **2026-11-16**: From #125 (2026-11-16): the review at a map's end now holds only the leftovers. While a map runs, the hub reviews its landed tickets once the oldest waited 25 minutes (or at once on POST /api/review/now / sbhub review-now); the map-end review takes only the landed tickets no earlier review took.
