---
wayfinder: ticket
operonId: 34e2ebf
number: 94
title: You decide whether hub changes run first in a night
why: "Tickets that change the hub's own code landed between page tickets all night: each one either restarted the hub, cutting workers off, or left the hub on old code so a review stalled."
project: sb-workflow
aliases:
  - "#094"
  - "094"
status: Project.Planned
type: grilling
priority: C
tier: sonnet
check: tests
created: 2026-11-15
map: "[[wayfinder/sb-workflow/night-spend/map|The night's tokens go to work that lands]]"
tags:
  - wayfinder/ticket
  - wayfinder/map/sb-workflow-night-spend
  - project/sb-workflow
  - status/open
  - type/grilling
---
> Owner, 2026-11-15: file them (the retro's fixes), onto night-spend

## Question

All night, tickets that change the hub's own code landed between page tickets: each one either restarted the hub and cut workers off, or left it on old code so a review stalled. The 2026-11-15 night retro has the evidence. Should the queue run those tickets first in each repo, then restart the hub once?

## Options

- ➡️ Yes: hub-changing tickets run first, the hub picks them out from the files they touch, then one restart
- No: keep the current order

## Done when

1. The owner's answer is a ruling on this ticket.
2. If yes, a build ticket for it is filed on this map.

## Comments

- **2026-11-15**: The question before it was split into options for the hub page:
  Should the queue run every ticket that changes the hub itself (its server, queue, templates or saved-state format) before the other tickets of that repo, and restart the hub once after them? ➡️ yes, with the hub naming those tickets itself from their files. The night retro of 2026-11-15 (wayfinder/sb-workflow/runs/2026-11-15-night-retro/retro.md) has the evidence.
