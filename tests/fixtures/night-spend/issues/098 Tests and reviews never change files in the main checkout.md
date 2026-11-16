---
wayfinder: ticket
operonId: f8eb8cf
number: 98
title: Tests and reviews never change files in the main checkout
why: "On 2026-11-15 a reviewer ran the contract fixture test in the main checkout, and that test rewrites the fixture files, so 17 files were left modified on main."
project: sb-workflow
aliases:
  - "#098"
  - "098"
status: Project.Planned
type: task
priority: C
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - tests/test_contract_fixtures.py
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

The contract fixture test writes its recordings to a temporary folder and compares them, and rewrites the real fixtures only when asked (an environment variable). Reviews run in their own throwaway worktree, never in the main checkout. The night retro of 2026-11-15 (wayfinder/sb-workflow/runs/2026-11-15-night-retro/retro.md) has the evidence.

## Done when

1. Running the fixture test leaves git status clean.
2. The test still fails when a recording differs from the fixture on file, and rewrites them when asked.
3. A test: a review's working folder is not the repo's main checkout.
4. Every check exits 0.

## Comments
