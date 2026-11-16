---
wayfinder: ticket
operonId: 8bb839b
number: 102
title: Queueing a stopped ticket again keeps the work Stop saved
why: "Stop keeps a worker's unfinished work, but queueing that ticket again deletes its working copy and resets its branch, so the saved work is lost."
project: sb-workflow
aliases:
  - "#102"
  - "102"
status: Project.Planned
type: task
priority: C
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - skills/sb/scripts/sbhub.py
  - tests/test_hub_runner.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: Yes, file them (the morning review's five bugs to fix first)

## Question

When a stopped ticket is queued again, its next try starts from the kept working copy and branch, as a resumed try does. Also: Stop ends descendants that left the worker's process group, and acts within seconds even while checks run inline. The morning review (wayfinder/sb-workflow/runs/2026-11-15-final-review-sb-workflow/review.md, Fix first) has the file:line evidence.

## Done when

1. A test: stop a worker that left an uncommitted file and a commit, queue it again; the next try starts with both still there.
2. A test: a child that called setsid is gone after Stop.
3. A test: Stop during a long check ends the run within 10 seconds.
4. Next step: a third try after a second Stop still keeps the work.
5. Every check exits 0.

## Comments

- **2026-11-16**: Moved from [[wayfinder/sb-workflow/night-by-map/map|You read and steer a night by map]] to [[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]].
