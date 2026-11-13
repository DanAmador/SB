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
Files you own: {paths}. Touch no other file.

Done when: {done_when}
These commands must all exit 0 when you finish:
{checks}

- Commit once by pathspec, with this as the last line of the message:
  Ticket: {map}/{num3}
  Do not resolve the ticket; the operator does.
- Write every ruling you make on the ticket: {sbmap} comment {map} {num3} --text "R: the ruling, cost if wrong: what it costs"
- Write your report to {run_folder}/{num}.md: the commit, each check with its counts, what you could not verify, rulings, files. Say nothing along the way. Your last message, two lines: what works now and how to see it; the report's path.
