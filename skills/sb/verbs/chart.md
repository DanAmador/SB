# /sb chart <idea>

A brain-dump becomes a vault map: a destination, the decisions it needs, and tickets an agent can
later run alone. This is wayfinder's *Chart the map*, run on the vault tracker with the owner's habits
built in.

1. **Rules & scope.** Do not load external skill files or vault docs. Author 100% through `sbmap` CLI.
2. **Scan existing context:** check other maps' Decisions (`sbmap maps --repo <path>`) and local ADRs. Say in one line what bears on it.
3. **Grill:** destination first, then breadth-first. Every question carries ➡️ a recommendation; ask in rounds of ≤5; when he answers some, list the rest as accepted on recommendation.
4. **Initialize the map:** `sbmap init <repo>/<effort> --title "<title>" --destination "<dest>" --done-when "<dw>"`. It creates `map.md`, `board.base`, and initial Route diagram automatically.
5. **Author tickets via CLI:**
   `sbmap new <map> --title "<title>" --type <type> --question "<question>" --done-when "<done-when>" [--blocked-by 624,625]`
   - Each sized to one session (~1.5 h).
   - Structural decisions are `architecture` tickets.
   - Diagram syncs automatically on each ticket.
6. **Verify:** `sbmap check <map>` clean, `sbmap verify <map>`. If Obsidian is open, `obsidian open path="wayfinder/<effort>/map.md"`.
7. **Readiness check.** For each frontier ticket: could an agent start it tonight with no question?
   Say which are ready, which need a grilling session, and offer `/sb tonight` for the ready ones.

Research tickets resolve at once in parallel subagents (the research skill); their findings go to
`<map>/research/<topic>.md` in the vault, linked from the ticket. Charting resolves nothing else.
