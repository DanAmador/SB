<!-- The `prompt` of a ticket's own session (tonight step 6.2). `background`: three sentences, what the
     product is, why this map exists in the owner's words, what has landed before this ticket.
     A ticket over ~4k tokens is named by path, not pasted. -->

Implement one ticket, alone, in `<repo path>` on `<branch>`, unattended. Read first, in this order;
their rules bind you:

1. `~/.claude/agents/implementer.md`: the standing rules (find code cheaply, files you own, build
   the least, git, report).
2. The run board `<board path>`: the contract, the per-ticket checks, the hard rules, your ports.
3. The ticket: `python3 ~/.claude/skills/sb/scripts/sbmap.py show <map> <NNN>`, and `<design note>`
   if it names one.

**<ticket name>.** Why: <the ticket's why>.
Do: <the steps, with the files>.
Leave alone: <its `Not this ticket`, or the neighbours' paths>.

Done when: <the ticket's Done-when>, and the board's per-ticket checks pass. Live checks on your own
throwaway data and ports (<ports>), never the owner's.

- Commit once by pathspec, `Ticket: <map>/<NNN>` as the last line. Don't resolve the ticket; the
  operator does.
- A blocking decision goes to `sbhub ask` by `~/.claude/skills/sb/reference/output.md`
  *Unattended*; write what it prints on the ticket before you finish:
  `sbmap comment <map> <NNN> --text "R: <ruling>, cost if wrong: <…>"`.
- Report once at the start and once at the end: `python3 ~/.claude/skills/sb/scripts/sbhub.py
  report --agent ticket-<NNN> --role worker --parent <run name> --ticket "<ticket name>" --state
  working|done --note "<commit or blocker>"`.
- Write your report to `<board folder>/<board name>/<NNN>.md`: commit, each check with its counts,
  what you could **not** verify, rulings, files. Say nothing along the way. Your last message, two
  lines: what works now and how to see it; the report's path.
