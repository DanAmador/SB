---
wayfinder: ticket
operonId: e164845
number: 100
title: "A new map knows its repo's folder, and the nine that say only a dot are fixed"
why: "Nine maps name their repo as '.', so the hub skips every ticket on them when they are queued; sk4te's 13 tickets were skipped that way on 2026-11-15."
project: sb-workflow
aliases:
  - "#100"
  - "100"
status: Project.Planned
type: task
priority: C
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
> Owner, 2026-11-15: file them (the retro's fixes), onto night-spend

## Question

`sbmap init` writes the repo's absolute folder (from --repo, else the current git root) and refuses a relative one. `sbmap check` flags a map whose repo is not an absolute folder. The nine maps are set to their real folders through sbmap. The night retro of 2026-11-15 (wayfinder/sb-workflow/runs/2026-11-15-night-retro/retro.md) has the evidence.

## Done when

1. A test: init from inside a repo with no --repo writes its absolute root.
2. A test: check flags a map whose repo is '.'.
3. `sbmap check` over the vault flags no map for its repo.
4. Every check exits 0.

## Comments
