---
wayfinder: ticket
operonId: 09a3f95
number: 95
title: A task never closes without its second pass
why: "Two tickets (Stop, and Everything as one graph) closed at landing with no Opus review on 2026-11-15, and the morning review then found Stop only partly done. Nobody knows why they skipped it."
project: sb-workflow
aliases:
  - "#095"
  - "095"
status: Project.Planned
type: task
priority: C
tier: opus
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
> Owner, 2026-11-15: file them (the retro's fixes), onto night-spend

## Question

Find the path by which a landed ticket was resolved without its review (both had been stopped or re-queued by a restart or a landing conflict before they landed; their answers lack the line the review adds). Close that path so every task the hub resolves went through the second pass. The night retro of 2026-11-15 (wayfinder/sb-workflow/runs/2026-11-15-night-retro/retro.md) has the evidence.

## Done when

1. A test reproduces the skip: a ticket re-queued after a hub restart, and one re-queued after a landing conflict, each land; before the fix one is resolved with no review.
2. After the fix, both are judged by the review and their notes carry review: met, partly or not met, never skipped.
3. Real data: the test drives the real queue and the real sbmap, not a hand-built queue item.
4. Every check exits 0.

## Comments
