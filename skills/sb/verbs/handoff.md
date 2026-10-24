# /sb handoff [what the next session does]

Context or tokens are running out, or the work moves to another session, model or harness. Leave a
vault file that a fresh agent can start from with nothing but one pasted line, in any tool.

1. **Bring the maps up to date first**: every ticket this session resolved has its Answer, Status
   and Decisions line; claims you are leaving are released (`open`) unless the next session is
   expressly taking them over; new findings are tickets (see `capture`); `sbmap diagram --write`.
   A handoff that says more than the map is a handoff the map will contradict.
2. **Write or update the handoff** at `<vault>/wayfinder/<effort>-handoff.md` from
   [templates/handoff.md](../templates/handoff.md). Update an existing one in place, dated, rather
   than writing a second. It points at tickets and the contract; it does not restate them. It
   *does* carry what lives nowhere else: this session's state of the world, gotchas learned, the
   rulings the owner gave in chat (quoted), and the one question to ask first.
3. **Cold-read it.** Dispatch a cheap-tier subagent with only the kickoff line and ask: what will you
   do first, and what would you have to ask? Fix every gap it names, then re-run until its first
   action is right and it has only the listed question.
4. **Print the kickoff line** in its own block, ready to paste:
   `Read <absolute path> and do what it says.` plus the role sentence. Then one line saying what the
   next session will do first and which model tier should run it, and `obsidian open` the handoff.
