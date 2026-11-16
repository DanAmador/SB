---
wayfinder: ticket
operonId: 7a72c80
number: 99
title: The tests widget stops its test runs and stays quiet during a night
why: "On the night of 2026-11-14 the tests widget left 22 test runs behind that ignored the stop signal, the machine's load reached 33 to 47, and a ticket's check timed out at 20 minutes."
project: sb-workflow
aliases:
  - "#099"
  - "099"
status: Project.Planned
type: task
priority: C
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - .sb/providers/tests
  - skills/sb/scripts/sbhub.py
  - tests/test_hub_providers.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: file them (the retro's fixes), onto night-spend

## Question

The tests widget starts each run in its own process group and ends the whole group when it stops or is replaced; it starts no new run while a night is live. The night retro of 2026-11-15 (wayfinder/sb-workflow/runs/2026-11-15-night-retro/retro.md) has the evidence.

## Done when

1. A test: stopping the widget ends its run and every child within 10 seconds.
2. A test: with a live night, the widget starts no run and says why.
3. Every check exits 0.

## Comments
