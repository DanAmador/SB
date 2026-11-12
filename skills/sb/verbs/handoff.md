# /sb handoff [what the next session does]

Context or tokens are running out, or the work moves to another session, model or harness. Leave a
vault file a fresh agent can start from with one pasted line, in any tool.

1. **Bring the maps up to date first**: every ticket this session resolved has its Answer; claims
   you are leaving go back to `open` unless the next session takes them over; new findings are
   tickets (`capture`). Rewrite each touched map's `## In plain words`. A handoff that says more
   than the map is one the map will contradict.
2. **Write the handoff** at `wayfinder/<repo>/<map>/handoff.md` from
   [templates/handoff.md](../templates/handoff.md), overwriting the last one; work spanning several
   maps writes the run board `sbmap run <map> <name>` prints instead (`--shared` across
   projects). 🔒 Never a file at the `wayfinder/`
   root or beside the maps. It points at tickets and the contract without restating them, and
   carries what lives nowhere else: the state of the world, gotchas learned, the owner's rulings
   from chat (quoted), and the one question to ask first.
3. **Cold-read it.** Dispatch `scout` with only the kickoff line and ask: what will you do first,
   and what would you have to ask? Fix every gap it names, and re-run until its first action is
   right and it has only the listed question.
4. **Print the kickoff line** in its own block, ready to paste:
   `Read <absolute path> and do what it says.` plus the role sentence. Then one line: what the
   next session does first and which tier runs it. `obsidian open` the handoff.
