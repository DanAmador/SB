---
wayfinder: ticket
operonId: d886c5c
number: 101
title: The worker guard catches the everyday ways around it
why: "The guard that stops workers closing tickets or rewriting history lets through commands any worker might write by accident, and workers on the other provider run with no guard at all."
project: sb-workflow
aliases:
  - "#101"
  - "101"
status: Project.Planned
type: task
priority: C
tier: opus
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - skills/sb/hooks/guard_git.py
  - skills/sb/scripts/sbhub.py
  - tests/test_hub_guard.py
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/task
---
> Owner, 2026-11-15: Yes, file them (the morning review's five bugs to fix first)

## Question

Close these gaps in the guard: a git command inside `if …; then`, `{ }`, `timeout`, `xargs` or `sudo -u`; a `;` inside a quoted message (both the miss and the false refusal); git's abbreviations such as `--amen`; reaching the main checkout through `cd`, `GIT_DIR=`, `--git-dir` or `-C<path>`; writes into `.git/`; the sbmap write commands missing from its list (`spend`, `migrate --write`, `diagram --write`, `board`, `wiki`); sbmap hidden behind interpreter flags. Give workers on the other provider the same guard. The morning review (wayfinder/sb-workflow/runs/2026-11-15-final-review-sb-workflow/review.md, Fix first) has the file:line evidence.

## Done when

1. A test per gap above: the command is refused, with the way out named.
2. A test: `git commit -m 'never git push; ever'` is allowed.
3. A test: a worker launched on the other provider starts with the guard's settings.
4. Real data: the cases are run through the hook as the hub installs it, not by calling its parser alone.
5. Every check exits 0.

## Comments
