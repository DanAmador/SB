---
wayfinder: ticket
operonId: 472233a
number: 103
title: A ticket waiting on a recheck waits instead of being skipped
why: "While a ticket is being rechecked, the tickets after it are skipped instead of waiting, and a recheck with no tries left holds its repo's queue forever."
project: sb-workflow
aliases:
  - "#103"
  - "103"
status: Project.Planned
type: task
priority: C
tier: opus
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
blocked_by:
  - "[[wayfinder/sb-workflow/night-spend/issues/102 Queueing a stopped ticket again keeps the work Stop saved|102]]"
paths:
  - skills/sb/scripts/sbhub.py
  - skills/sb/scripts/sbqueue.py
  - tests/test_queue_rules.py
  - tests/test_hub_queue.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: Yes, file them (the morning review's five bugs to fix first)

## Question

The tickets the queue counts as live include those in recheck, so a ticket after one waits. A recheck that has used its tries ends as failed and waits for the owner, freeing its map. Map-end reviews judge the map's landed tickets even when one recheck failed. The morning review (wayfinder/sb-workflow/runs/2026-11-15-final-review-sb-workflow/review.md, Fix first) has the file:line evidence.

## Done when

1. A test: a ticket after one in recheck stays queued and runs once the recheck passes.
2. A test: a recheck with no tries left ends failed, and the next map in the repo starts.
3. Real data: the tests take the live set from the queue's own function, not a hand-built set.
4. The existing test that passes a hand-built live set is changed to use the real one.
5. Every check exits 0.

## Comments

- **2026-11-16**: Moved from [[wayfinder/sb-workflow/night-by-map/map|You read and steer a night by map]] to [[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]].
