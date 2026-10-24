# /sb chart <idea>

A brain-dump becomes a vault map: a destination, the decisions it needs, and tickets an agent can
later run alone. This is wayfinder's *Chart the map*, run on the vault tracker with the owner's habits
built in.

1. **Load wayfinder's charting rules.** Read the installed wayfinder skill file
   (`~/.claude/plugins/cache/mattpocock/mattpocock-skills/*/skills/engineering/wayfinder/SKILL.md`,
   newest version) for the map's shape, ticket types, fog of war and out of scope. Its tracker is
   replaced by the vault's: `<vault>/wayfinder/README.md` says how a map, ticket, claim and block are
   written. GitHub stays untouched unless the owner asks for it.
2. **Read the vault and the repo** for what already exists on this idea: other maps' Decisions, open
   tickets, `CONTEXT.md`, ADRs. Say in one line what bears on it.
3. **Grill** with the grilling and domain-modeling skills, destination first, then breadth-first.
   Every question carries ➡️ a recommendation; ask in rounds of ≤5; when he answers some, list the rest
   as accepted on recommendation and continue. Record each ruling as `R<n>` under the map's
   `## Comments`, in his words where he gave them.
4. **Write the map** at `<vault>/wayfinder/<repo>-<effort>/map.md` (folder name in kebab case,
   prefixed by the repo's folder name, so `sbmap maps --repo` finds it): the map properties the
   vault README shows (`repo` = the checkout's absolute path), title line, Destination with a *Done when*, Notes (the repo's absolute path, skills to consult, where things live, and a stub for the contract), Decisions so far, Not
   yet specified, Out of scope.
5. **Write the tickets you can specify now**, each created by `sbmap new`. Each one is sized to one
   session and written so a mid-tier agent can run it from the ticket alone: *Question*, the rulings
   that shape it, *Done when*. A structural decision is an **architecture** ticket
   ([reference/architecture.md](../reference/architecture.md)) that the tasks depending on it are
   blocked by. Wire blockers in a second pass with `sbmap block`; every mention of another ticket is a
   wikilink.
6. **Draw it.** `sbmap board <map>` (the Bases board, embedded in the map), `sbmap check` clean,
   then `sbmap diagram <map> --write` for the Route. Add a
   `mindmap` under Destination: the destination at the root, then Decisions, the open questions, Not
   yet specified. `sbmap verify <map>` until every diagram parses, then `obsidian open` the map.
7. **Readiness check.** For each frontier ticket: could an agent start it tonight with no question?
   Say which are ready, which need a grilling session, and offer `/sb tonight` for the ready ones.

Research tickets resolve at once in parallel subagents (the research skill); their findings go to
`<map>/research/<topic>.md` in the vault, linked from the ticket. Charting resolves nothing else.
