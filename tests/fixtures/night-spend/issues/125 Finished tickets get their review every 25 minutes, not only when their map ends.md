---
wayfinder: ticket
operonId: 755bf26
number: 125
title: "Finished tickets get their review every 25 minutes, not only when their map ends"
why: "Today a finished ticket waits for its review until every ticket of its map is done, so on a long map work sits unjudged for hours and its follow-ups wait. After this the hub reviews whatever has finished every 25 minutes, and the hub has a call that does the same at once for the website's button."
project: sb-workflow
aliases:
  - "#125"
  - "125"
status: Project.Planned
type: task
priority: C
tier: opus
check: tests
created: 2026-11-16
filed_during: "Night of 2026-11-15, 15:22"
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
paths:
  - skills/sb/scripts/sbhub.py
  - skills/sb/hub/packages/contract
  - tests/test_hub_queue.py
  - skills/sb/reference/hub.md
tags:
  - project/sb-workflow
  - status/open
  - type/task
  - wayfinder/map/sb-workflow-night-spend
  - wayfinder/ticket
run_minutes: 64.432
check_minutes: 3.03
tries: 1
tokens_in: 138
tokens_out: 31636
cache_read: 5723897
cost_usd: 2.6756
model: opus
account: assembio
night: night-20261115-152229
outcome: failed
---
> Owner, 2026-11-16: "we need some sort of pacekeepr that pings every couple of run a ping every 20 - 30  mins to see if any ticket has been finished to do a review. But also be able to enqueue it manually from the website to finalize multiple tickets at once". Ruled on the hub page, 2026-11-16: every 25 minutes; the review at a map's end covers only what the timer has not, so no ticket is reviewed twice; the website gets one Review finished now button that does what the timer would, right away.

## Not this ticket

The review's brief, its verdicts and when a ticket closes stay as they are; the page's button is the next ticket.

## Question

Review start lives in sbhub.py (the method whose docstring begins 'For each map whose run has ended'; it skips a map with anything queued, running or in checks). (1) A map that is still busy also gets a review when its oldest landed, unreviewed ticket has waited 25 minutes (REVIEW_EVERY_MIN = 25, overridable by env SB_REVIEW_EVERY_MIN). Still one review at a time per map; a running review's tickets are never taken again. (2) The review at the map's end is unchanged: it already takes only landed tickets no review holds, so it covers just the leftovers. (3) POST /api/review/now starts, for every map with landed unreviewed tickets, the review the timer would start, busy or not; it answers which maps started. sbhub review-now does the same from the shell. (4) The contract (routes.ts, schemas.ts, fixtures) gets the route, and /api/state says when the next timed look is due (review_next_at). (5) Not during a rebuild of the hub's own code: the same rule that holds a map's review today holds this one.

## Done when

1. A test with the fake worker: a map of three tickets, two landed 26 minutes ago and one still running; one review starts on the two, and the third is reviewed alone at the map's end.
2. A test: a ticket that landed 10 minutes ago is not reviewed by the timer.
3. A test: POST /api/review/now starts reviews for two maps with landed tickets and answers both names; called again while they run, it starts nothing new.
4. Next step: after a hub restart, a review that was running is not started twice, and the 25-minute clock counts from each ticket's landing time kept in the queue file, not from the restart.
5. Real data: the review-now test reads a queue file as the real hub writes it.
6. Shared word: the open ticket of this map about a review of all of a map's tickets at its end gets a comment that the map-end review now holds only the leftovers.
7. The contract fixture test passes with the new route; the map's checks pass.

## Comments

- **2026-11-16**: R: a ticket landed before this change (no landed_at in the queue file) counts as due at once on a busy map, cost if wrong: one early review of old landed tickets after the first restart on this code.

- **2026-11-16**: R: review_next_at is the oldest landed ticket's landing plus 25 minutes over maps with no review running, and is optional in the contract so older state mocks still parse, cost if wrong: the page's countdown may show a time already past while a rebuild holds the review.

- **2026-11-16**: R: on a hub that serves read-only (no queue supervisor), POST /api/review/now answers ok with started: [] rather than an error, cost if wrong: the button looks like it did nothing on that hub instead of saying why.

- **2026-11-16**: R: the fake-worker tests went into tests/test_hub_runner.py beside the other review tests (that is where the runner harness lives), not tests/test_hub_queue.py, cost if wrong: none beyond where to look.

- **2026-11-16**: The sb hub's run of this ticket failed (opus on agent assembio): check failed: pnpm --dir skills/sb/hub test
  packages/web test:       953 |     await expect.poll(() => queuedKeys(page)).toEqual([...before, "demo/batch#1", "demo/batch#2", "demo/batch#3"]);
  packages/web test:       954 |     await expect(bar).toHaveCount(0);
  packages/web test:         at /Users/danamador/.sb-hub/worktrees/sb-workflow-74ed4c/sb-workflow-night-spend-125/skills/sb/hub/packages/web/e2e/board.spec.ts:951:45
  packages/web test:     Error Context: test-results/board-Map-view-a-box-dragg-8d88e-s-them-ticked-Escape-clears/error-context.md
  packages/web test:     attachment #2: trace (application/zip) ─────────────────────────────────────────────────────────
  packages/web test:     test-results/board-Map-view-a-box-dragg-8d88e-s-them-ticked-Escape-clears/trace.zip
  packages/web test:     Usage:
  packages/web test:         pnpm exec playwright show-trace test-results/board-Map-view-a-box-dragg-8d88e-s-them-ticked-Escape-clears/trace.zip
  packages/web test:     ────────────────────────────────────────────────────────────────────────────────────────────────
  packages/web test:   1 failed
  packages/web test:     e2e/board.spec.ts:876:3 › Map view › a box dragged over three nodes ticks them; the bar says 3, Queue queues those three, Table shows them ticked; Escape clears 
  packages/web test:   6 skipped
  packages/web test:   20 did not run
  packages/web test:   50 passed (2.3m)
  packages/web test: Failed
  /Users/danamador/.sb-hub/worktrees/sb-workflow-74ed4c/sb-workflow-night-spend-125/skills/sb/hub/packages/web:
   ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL  @sb-hub/web@0.0.0 test: `vitest run && playwright test`
  Exit status 1
  [ELIFECYCLE] Test failed. See above for more details.
  $ pnpm -r test
  Its work stays on branch sb/sb-workflow-night-spend-125 in /Users/danamador/.sb-hub/worktrees/sb-workflow-74ed4c/sb-workflow-night-spend-125.
  The commit 72457b0b0 is left in place.
