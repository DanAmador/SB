<!-- The prompt of a ticket's own session, which the hub fills for every queued ticket
     (`sbqueue.brief`): each {name} comes from the ticket alone, and a line whose value is empty is
     dropped. This comment is not sent. A name the hub cannot fill is an error, so add none. -->
Background: {background}

Implement one ticket, alone, in {repo} on {branch}, unattended.
Read the ticket first: {sbmap} show {map} {num3}

{title}.
Why: {why}
Do: {question}
Leave alone: {out}
Files you own: {paths}. Start there, and change another file when the ticket truly needs it (a caller,
a registry, a shared type, a test): name each one under `## Files` in your report with why. Do not stop
only because a file is not on the list.
Test in this checkout and with the editor or dev server already running for it: never open a second copy.

Done when: {done_when}
These commands must all exit 0 when you finish:
{checks}

- Verify your own change before you commit, by this repo's own rules (the verification section of its AGENTS.md or CLAUDE.md): run the tests that cover what you changed, or add one that proves the Done when where the repo allows tests; where it forbids them, use the checks it names instead. Put each command you ran and its result (counts, exit code) in your report under `## Self-checks`.
- When your change shows on screen, capture screenshots (or a short clip) with the repo's own tool named in its AGENTS.md or CLAUDE.md (a Unity screenshot command, Playwright), look at each one yourself and fix what looks wrong before you commit. Save them in {run_folder}/{num}-media/ under short names ending in .png, .jpg, .gif, .webp, .mp4 or .webm: at most 6 files, each under 8 MB, a clip at most 20 s. List each under `## Pictures` in your report with one line on what it shows; a change with nothing on screen says so there in one line.
- Commit once by pathspec, with this as the last line of the message:
  Ticket: {map}/{num3}
  Do not resolve the ticket; the operator does.
- Write every ruling you make on the ticket: {sbmap} comment {map} {num3} --text "R: the ruling, cost if wrong: what it costs"
- Write your report to {run_folder}/{num}.md: the commit, each check with its counts, what you could not verify, rulings, files. Say nothing along the way. Your last message, two lines: what works now and how to see it; the report's path.
