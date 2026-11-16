---
wayfinder: ticket
operonId: e2ca839
number: 105
title: An error while the hub rebuilds itself no longer blocks its reviews
why: "If anything unexpected goes wrong while the hub rebuilds itself, it stays marked busy, and no review starts on its own repo until someone restarts it by hand."
project: sb-workflow
aliases:
  - "#105"
  - "105"
status: Project.Planned
type: task
priority: C
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
blocked_by:
  - "[[wayfinder/sb-workflow/night-spend/issues/101 The worker guard catches the everyday ways around it|101]]"
paths:
  - skills/sb/scripts/sbhub.py
  - tests/test_hub_rebuild.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: Yes, file them (the morning review's five bugs to fix first)

## Question

The rebuild always clears its busy mark when it ends, however it ends, and tells the owner what failed. The path that holds reviews while a restart is pending gets a test. The morning review (wayfinder/sb-workflow/runs/2026-11-15-final-review-sb-workflow/review.md, Fix first) has the file:line evidence.

## Done when

1. A test: a rebuild whose build step raises leaves the hub not busy, and a review then starts.
2. The same when the restart step raises.
3. A test of the restart-hold path.
4. Every check exits 0.

## Comments
