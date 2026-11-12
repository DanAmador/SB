# sb hub page: fixes for the 2026-11-12 UX audit

Files changed: `skills/sb/scripts/sbhub.html` (rewritten render, same rules: one static file, no inline
event handlers, no outside resources, every state value through `esc`), `skills/sb/scripts/sbhub.py`
(one change: `since`), `skills/sb/scripts/sbhub_widget.html` (row markup kept in step, plus item 13),
`tests/test_hub.py`, `tests/test_hub_cli.py`. Nothing committed.

Evidence folder `$F` = `/private/tmp/claude-501/-Users-danamador-Documents-Coding-sb-workflow/4177cc3d-7705-4c0f-8e57-1bd6e1e0e606/scratchpad/audit/fixes/`.
All browser checks ran on a throwaway hub (port 18991, its own `SB_HUB_HOME`, `SB_HUB_NOTIFY=0`).
The owner's hub on 8765 was not touched (no request of any kind sent to it).

Stress set used: 13 sessions across 5 projects (git repos made for the test; one with 3 uncommitted
files, one with a trusted `.sb/providers/tests` script reporting 41 pass / 2 fail and a `bad` status),
a 9-ticket run with 6 workers (one worker ticket 200 characters, no spaces), a 200-character unbroken
title, note, ticket and `asked`, emoji, Arabic, `<b>x</b> <img onerror>` and `<script>` text, 4 open
questions (one with four 50-60 character options and a 150-character question, one with a 200-character
unbroken word), a 25 s question that expired while watched, a working session silent 12+ minutes (written
into `state.json` with an old `at` and `since` before the hub started), a session with no name or title
(17-character id), a lock held by an unknown 17-character id, zero sessions (fresh home), hub stopped
then started.

## Per item

### 1. Layout never collapses: done
- `body` no longer has `overflow-wrap:anywhere` (the cause of F1). A session is a grid: icon | stacked
  lines | age (html:19-31). Title `.t` wraps on words, breaks unbroken strings, capped at 2 lines on a
  phone and 1 line on desktop with an ellipsis (html:22, html:79). Below 600 px `.main` uses
  `display:contents` so line 1 is icon + title + age and every later line takes the full width (html:64-72).
  At 760 px and up the row is two compact lines: title / last ask on the left, project · ticket · progress /
  note on the right, workers under them (html:73-79).
- Long ticket, project and worker labels are single-line ellipsised chips with a max width; more than 20
  tickets draw a bar with `d/t` instead of pips.
- Measured at 375 px, stress data: document width 375 = viewport (no horizontal scroll), tallest session
  row 130 px (the 6-worker run; the 200-character title row 108 px), light and dark. Desktop 1280 px: no
  horizontal scroll. Before: 466 px and 3815 px rows.
- Evidence: `$F/04-375-light-waiting-and-projects.jpg`, `$F/05-375-light-workers-quiet-log.jpg`,
  `$F/09-375-dark-projects.jpg`, `$F/02-desktop-light-projects.jpg`.

### 2. Needs-you options on a phone: done
- Below 600 px option buttons are `flex:1 1 100%`, `min-height:42px`, wrap their text, left-aligned
  (html:66); at every width buttons have `max-width:100%` and `white-space:normal` (html:45). The `.box`
  no longer has `overflow:hidden`. The default is marked by a word ("· default"), not colour alone.
- Measured at 375 px: 11 buttons, each 333 px wide, 42-47 px tall, `scrollWidth <= clientWidth` for all
  (nothing clipped). Evidence: `$F/03-375-light-needs-you-options.jpg`.
- Note: 4 open questions still make a tall box on a phone (that is the content); nothing is cut.

### 3. Hub down: done
- `#banner` (html:85-86, `role="alert"`) shows "Hub not reachable — showing the last state from 11:51 PM";
  `body.down main` dims to 60 % (html:13); every answer button is disabled (`setDown`, html:209-212; `qrow`
  draws them disabled while down, html:132). `answer()` now checks the response and on failure writes
  "Not sent: <reason>" next to the question (html:162-167, the reason is the hub's error text or "hub not
  reachable"). When the hub answers again the banner goes and the page re-renders at once (`tick`, html:215).
- Checked: stopped the hub, banner appeared within one tick, all buttons disabled, `main` opacity 0.6; called
  the click path for "4" and the row showed "Not sent: hub not reachable"; restarted, within 4 s the banner
  was hidden and 9 buttons enabled. Evidence: `$F/07-hub-down-banner-and-failed-click.jpg`.
- I could not land a real pointer click in the gap before the page noticed the outage (it notices in at most
  2 s); I called the page's own `answer()` instead. The 4xx path ("the hub said 404") was not exercised.

### 4. People, not ids: done
- One label function `lbl` (html:104): title, else ticket ("ticket 12" for a bare number), else name, else
  the first 6 characters of the id. `who(id)` (html:107) resolves an id through `aliases` to the agent and
  falls back to the short id. Used in session rows, worker chips, question rows, Needs-you rows, Log rows
  and lock holders.
- Question rows show "<label> · <project> · asked 3m ago"; Log rows show the question, then "Chosen by you /
  Default applied · <label> · <project> · 5m ago", and the answer chip.
- Checked on the page: "Nightly migration · delta-web", "a6f5c7 · gamma-lab", "zz9999", lock "held by
  Nightly migration", "held by aa1e17". No 17-character id anywhere. `$F/01-desktop-light-top.jpg`.

### 5. Questions: done
- Countdown uses `dur` (floor, never rounds up): "24s left" under a minute, "9m left" after (html:89,
  html:135). A 1 s timer moves it between renders without touching the DOM structure (html:222-227).
- A decided question stays in its place for 20 s, same markup and height, buttons disabled, the chosen one
  marked "✓ <choice>", status "You chose this · moving to the log" or "Default applied · moving to the log";
  it is in the Log at once (html:173, html:197-200). Open and recently decided questions are sorted together
  by deadline so the decided row does not move.
- Measured (25 s question): text went "19s left" ... "1s left" → "deciding…" (buttons disabled) → "Default
  applied · moving to the log"; row height 110 → 111 px, Needs-you box 789 px throughout. Real click on
  "pytest": the asking process printed `pytest`; the row stayed as "✓ pytest / You chose this", the Log
  showed "Chosen by you". Evidence: `$F/06-desktop-answered-row-stays.jpg`.
- After 20 s the decided row leaves the box (a single shift, 20 s after the decision, announced beforehand).

### 6. Attention order: done
- `RANK` (html:96): needs you / blocked 0, your turn 1, working / waiting 2, idle 3, done 4; ties by newest
  `at`. Needs you holds open questions, needs-you/blocked sessions (full rows, no duplicate below) and bad
  provider widgets. "Waiting for you" is its own quiet heading with plain rows (html:185). The header reads
  "13 sessions · 6 workers · 7 need you · 2 waiting for you · 2 locks"; the tab title counts real alerts only.
  With no alerts the top shows "✓ Nothing needs you" (html:184). Evidence: `$F/01-desktop-light-top.jpg`,
  `$F/11-375-empty-state.jpg`.

### 7. What it is doing: done
- `asked` is a visible muted one-line ellipsised line under the title: "You asked: “…”" (html:126). The age
  reads "active 2m ago". Working sessions show "working 25m" from the new `since`.
- Server: `Hub.report` sets `since = at` when the reported state differs from the stored one (or there is no
  `since` yet) and keeps it while the state stays the same; an agent never given a state has none
  (py:155-157). Tests first (both failed, then passed): `test_since_marks_when_the_state_last_changed`
  (tests/test_hub.py:28) and `test_an_agent_reported_without_a_state_has_no_since` (tests/test_hub.py:42),
  injectable clock.

### 8. Silence is a signal: done
- A `working` session silent 10+ minutes gets a warning chip "⚠ quiet for 12m" (html:123) at full contrast.
  The old `opacity:.4` is gone. Only idle/done titles go to the muted colour (html:28), which stays above 4.5:1.
- Measured contrast: quiet chip 5.43:1 light, 7.24:1 dark; muted idle/done title 5.50:1 light, 6.37:1 dark.
  Evidence: `$F/05-375-light-workers-quiet-log.jpg`.

### 9. Projects: done
- Sessions not in Needs you / Waiting are grouped under a project header (folder name), groups ordered by
  their most urgent then most recent session. The header is a `<details>` whose summary line carries the
  folded provider digest: branch, "3 uncommitted", test counts, any warn/bad status (`digest`, html:152);
  opened it shows every provider line and its log `<details>`. A project whose sessions all sit above says
  "2 above". Status widgets with level `bad` are rows in Needs you (html:177, html:182). The separate
  per-project sections at the bottom are gone.
- Open state survives refreshes: opened the gamma-lab header, waited 12 s (one forced re-render, original
  node detached), the new header was open. Evidence: `$F/10-375-light-project-expanded.jpg`.

### 10. Accessibility: done
- `<html lang="en">` (html:1). Primary button text: `#fff` on `#3b5bdb` 5.67:1 light; `#10131f` on `#8ea2ff`
  7.72:1 dark (`--onacc`, html:4-5).
- Pips: pending hollow outline, done filled, current hollow with a thick accent border and taller (html:35-37),
  plus a visible "3/9" and the title text; readable in grey.
- State icons are `role="img"` with `aria-label` (`stIc`); at 600 px and up the state word sits under the icon
  (`.sw`). Needs you is now 🔔, your turn stays 💬. ⏸ is `⏸️` (emoji presentation) in a fixed 20 px box with an
  emoji font stack: every session icon measured 20 px tall.
- axe-core 4.10.3 (loaded from a local copy): 0 violations at 1280 px dark and at 375 px light, after wrapping
  the heading in `<header>` and the content in `<main>` (fixes the audit's moderate `region`).

### 11. Refresh without destroying focus: done
- The skip-when-unchanged logic stays. `render` records the focused element's `data-key` (buttons
  `q:<id>:<i>`, summaries `d:<details key>`) and the scroll position, rewrites, restores open details, focus
  (`preventScroll`) and scroll (html:201-207).
- Measured: focused an answer button, scrolled to 200, sampled 7 times over 14 s: the original node was
  replaced after ~10 s, `document.activeElement` still had the same key every time, `scrollY` stayed 200.
- Not done: the brief's "do not replace the whole `#app` on every tick" in the literal sense; it still
  rewrites `#app` when the state changes or every 10 s, but focus, scroll and open details survive.

### 12. Stale questions: done
- An open question past its deadline draws "deciding…" with disabled buttons, both at render (html:132-135)
  and from the 1 s countdown timer (html:225). Server behaviour unchanged. Seen live in the item 5 run.

### 13. Widget answers (added mid-task by the coordinator): done, checked in a fake host only
- (a) The widget keeps `seenOpen` (every question it saw open) and `here` (what was answered from it)
  (widget:97-98). Decided ones draw under the open questions as "✅ <question> → <choice>" ("⏱ … (by default)"
  for defaults), focus question or not, even after the state drops them (`decidedLine`, widget:166, render
  widget:178-181).
- (b) While `sb_answer` is in flight the clicked button reads "Sending…" and the question's buttons are
  disabled; a failure shows "Not recorded: <reason>" next to the question (reason from the tool result's text
  or the JSON-RPC error) (widget:120-127, `opts`/`failLine`).
- (c) `ui/message` is no longer swallowed: a rejection, an `isError` result or a host that says it has no
  message support shows "Recorded on the hub. The agent will see it on its next turn." under the decided
  question, with the reason in its `title` (widget:128-134). Only for the focus question.
- (d) What `ui/initialize` returned in `hostCapabilities` is stored in `#live`'s `data-host-caps` and `title`
  (widget:205). The request is skipped only when `hostCapabilities.message` is present and falsy (widget:118).
- Rows in the widget now use the page's label function, glyphs, sort order, stacked row, pips, "You asked",
  "working 25m", "quiet for 12m", "active 2m ago", seconds countdown and "held by <label>".
- Checked with a fake host page (scratchpad `wh/host.html`, iframes a copy of the widget and answers
  JSON-RPC): click on a non-focus question showed "Sending…", then "✅ Which runner? → pytest"; a refused
  answer showed "Not recorded: the answer must be one of the options" and re-enabled its buttons; the focus
  question showed "✅ Ship it tonight? → yes" plus the fallback line with title "Method not found: ui/message";
  a question decided elsewhere after being seen open showed "⏱ Workers tonight? → 6 (by default)";
  `data-host-caps` = `{"serverTools":{}}`. Evidence: `$F/12-widget-fake-host-answers.jpg`.

## Tests

```
$ python3 -m unittest discover -s tests -q
----------------------------------------------------------------------
Ran 180 tests in 55.163s

OK (skipped=7)

$ uv run -q --with "mcp>=2.3,<3" python -m unittest discover -s tests -p "test_hub_mcp.py"
----------------------------------------------------------------------
Ran 7 tests in 1.528s

OK

$ node --check <script extracted from sbhub.html>          # OK
$ node --check <script extracted from sbhub_widget.html>   # OK
```

New tests: the two `since` tests in tests/test_hub.py; tests/test_hub_cli.py:147 now pins the 2-line title
clamp and the absence of the `body{...overflow-wrap:anywhere` rule that caused F1 (it pinned the old
`.row{flex-wrap:wrap}`); tests/test_hub_cli.py:153 pins `<html lang="en">` and the page's plain-word states.
(180 tests, not 176 + 3: the MCP file has 7 tests now, so 7 are skipped without `mcp`.)

## Chosen differently from the brief

- "Nothing needs you" shows whenever there are no alerts, even if sessions are in "Waiting for you"; "your
  turn" is treated as not an alert (item 6 says its group is quiet and counted apart), so the all-clear plus a
  quiet waiting group below it is the honest reading.
- Needs-you and your-turn sessions are drawn once, in their attention group, not again under their project;
  the project header says "+1 above". Grouping by project and sorting by attention otherwise conflict.
- Phone tap height is 42 px (brief: at least 40; the audit said 44) to keep 4 questions shorter.
- "Hub down" dims the page to 60 % opacity, below 4.5:1 for muted text, on purpose: it marks old data.
- Widget `ui/message`: the params now send `content` as an array of content blocks
  (`[{type:'text',text}]`) instead of one object. That is my reading of the MCP Apps spec, not verified against
  the spec text or a real host here; if the object form was right, revert that one line (widget:131). This may
  also be why no message reached the chat.
- Widget (d): "clearly unsupported" means `hostCapabilities.message` present and falsy. A host that simply
  omits the key still gets the request (and the fallback line if it rejects), so a host that supports
  `ui/message` without advertising it keeps working.
- `.max-width` of the page went from 900 to 1100 px and is centred (audit F16), and user text carries
  `dir="auto"`.

## Not verified

- A real phone or touch input; only 375×812 emulation.
- The widget inside a real MCP Apps host (Claude); only the fake host page. Whether that host advertises
  `message` and which `ui/message` shape it accepts is unknown.
- The page's 4xx answer error path; a pointer click in the gap between the hub going down and the page noticing.
- Screen-reader behaviour of the 2 s refresh (no live region beyond the banner's `role="alert"`).
- The widget's light-scheme quiet chip uses the host's warning colour (or `#b7791f`, about 3.3:1 on white); its
  contrast was not measured or changed, since the audit and checks covered `sbhub.html` only.
- Console: no script errors; the only console lines were `ERR_CONNECTION_REFUSED` for the state fetches while
  the hub was deliberately stopped.

Cleanup: throwaway hub and the local static server stopped, background `ask` processes gone, viewport
emulation reset to desktop. The owner's hub on 8765 is still running and was never contacted.
