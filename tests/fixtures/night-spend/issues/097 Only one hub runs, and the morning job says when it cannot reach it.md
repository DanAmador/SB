---
wayfinder: ticket
operonId: 8e86119
number: 97
title: "Only one hub runs, and the morning job says when it cannot reach it"
why: "A second hub started from another folder twice on 2026-11-15, and the 09:00 close-off found the hub not answering behind a lock left by a dead process, so no morning note was written."
project: sb-workflow
aliases:
  - "#097"
  - "097"
status: Project.Planned
type: task
priority: C
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - skills/sb/scripts/sbhub.py
  - skills/sb/templates/close-off.md
  - tests/test_hub_lock.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: file them (the retro's fixes), onto night-spend

## Question

`sbhub serve` refuses to start while a live hub holds the queue lock, and takes over a lock whose process is dead. The close-off job checks the hub first; when it cannot reach it, it still writes the phone note from the saved state, saying in its first line that the hub was down and how to restart it. The night retro of 2026-11-15 (wayfinder/sb-workflow/runs/2026-11-15-night-retro/retro.md) has the evidence.

## Done when

1. A test: a second serve on the same hub home exits non-zero and names the running one.
2. A test: a lock held by a dead pid is taken over.
3. A test: the close-off with no hub answering writes the phone note from the saved state, first line saying the hub was down.
4. Every check exits 0.

## Comments
