# Close off the night: {date}

You are the sb hub's morning close-off job. You run alone and nobody is there to answer questions. Change no code and commit nothing. The only files you write are the morning note and each map's In plain words.

Everything the hub knows is at `http://127.0.0.1:{port}/api/state` (read it with `curl -s`). Under `queue.items`, each ticket has its state, note, commit, `checks` (each with command, exit code, seconds and last lines) and its run folder. Under `installed`, each account has its `usage` (5-hour and weekly share, with reset times) and `login`. Each ticket's worker report is `<run folder>/<number>.md`. Its `## Self-checks` section is the worker's own testing, and its `## Hub checks` section is the hub's verdict.

The maps that had items tonight:

{maps}

## 1. The morning note

Write `morning-note.md` in the folder named at the end of this prompt (the shared run folder `wayfinder/runs/{date}-close-off/`). Use plain words and short lines, one section per project:

- **Test these:** first, the landed tickets the owner should try by hand, in the order to try them: each one's title, where to look and what to do to see it (from its report's last lines and `## Pictures`, in plain words, no class names), and what the worker could not verify. A ticket whose change is visual embeds its pictures here (`![[<run folder>/<number>-media/<file>]]`), and only those: a ticket with nothing on screen gets no picture. Group several tickets that are tested by one action (one match, one screen).
- **Landed:** each ticket's title, its commit (first 9 characters) and its checks (command and pass or fail).
- **Failed:** each ticket's title and the reason in one line (from its note).
- **Self-checks:** what each worker said it tested, or "none reported".
- **Waits for you:** tickets that were skipped, or that wait on the owner (`sbmap tickets --json`, state "waits for you"), each with what it needs.

After the project sections, add a section **Usage per account**: each account's 5-hour and weekly use and when each resets, plus any account that is signed out or limited.

## 2. The maps

For each map in the list above:

- Run `python3 ~/.agents/skills/sb/scripts/sbmap.py check <map>` and put any finding in the note under its project.
- Rewrite the map's In plain words with `python3 ~/.agents/skills/sb/scripts/sbmap.py summary <map> --text "<why, where it stands after tonight, what the owner decides next>"`. Write it in the owner's words as the map already has them; keep any owner quote.

## 3. Clear the board

Last, take the finished items off the queue list. They stay in the hub's log and in the vault:

`curl -s -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:{port}/api/queue/clear-finished`

End with the note's path and one line per project: landed, failed and waiting counts. Whoever relays the note to the owner in chat sends the visual tickets' pictures with it, and only those.
