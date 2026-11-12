# sb hub page: UX audit, 2026-11-12

```
VERDICT: FAIL
Persona: solo developer with ADHD, 4-10 agent sessions across projects, often overnight, reads on laptop and phone, wants a one-glance overview.
Surfaces audited: 1 of 1 (single page; login, routes, forms: not applicable)
Interaction Manifest: complete for this app (see end of file)
Hard gates: console errors 0, warnings 0, network 5xx 0 (hub log), 403/404 0, layout collapse 3 (see F1, F3), axe Critical 0, axe Serious 2 (dark: color-contrast; both schemes: html-has-lang)
Performance (/): LCP 328 ms / CLS 0 / INP not separately measured (clicks answered within one 2 s tick) - green
Findings: Critical 1  High 6  Medium 6  Low 3
Self-critique pass: done by me against the checklist, not a fresh sub-agent (the brief said to drive from this session). Drafted 20, kept 16, generic 2, duplicate 2.
```

Evidence folder: `/private/tmp/claude-501/-Users-danamador-Documents-Coding-sb-workflow/4177cc3d-7705-4c0f-8e57-1bd6e1e0e606/scratchpad/audit/` (called `$A` below). Line numbers are `skills/sb/scripts/sbhub.html` ("html:NN") or `sbhub.py` ("py:NN").

Did the "random ID" complaint get answered? Half. On the owner's live hub (read-only look, `$A/06-LIVE-hub-readonly-raw-worker-ids.jpg`) 2 of 5 sessions have a title; the other 3 still read "HomeStudio 3959ea", "fx-mini-loader 30f047". 6 of 11 workers have no name, so their chips show raw ids like `a6f5c7511998894b6`. The Needs-you box and the Log never use the title at all (F4). Tickets and pips exist but nothing in the live data had them, so I could not see them help.

## Findings, ranked by how much they hurt this user

### F1 Critical - A normal-length title collapses into a one-letter-wide column on a phone, and a long title does it on desktop
- Did: 375 px wide, 10 realistic sessions (titles of 14-28 characters, one ticket, 9 pips, 3 worker chips). Then desktop with a 200-character no-space title.
- Happened: "Party mode audit and tickets" (28 chars, a ticket chip, 9 pips) rendered one letter per line: title box 13 px wide, row 466 px tall (every other row 55-75 px). With the 200-character title the row is 3815 px tall at both widths and the page is 5144 px long. At 375 px, 2 of 10 rows ("Party mode...", "Nightly migration" 134 px) broke; the first screen shows 4 sessions then a letter tower.
- Should: title truncates with an ellipsis (or wraps by words) and always keeps a readable minimum; the row stays 1-2 lines.
- Evidence: `$A/05-realistic-375-title-collapse.jpg`, `$A/04-stress-200char-title-vertical-stack.jpg`; JS: `b` width 13 px, row 466 px; desktop row 3815 px.
- Suspect: html:6 `overflow-wrap:anywhere` on body makes the title's minimum width one character, so html:14 `.chip{white-space:nowrap}` and html:13 `.pips{flex:none}` win the flex space and the title shrinks to nothing (html:18 `.who{min-width:0}`, html:42 row markup).
- Patch: `.who b{flex:0 1 auto;min-width:9ch;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}` and drop `overflow-wrap:anywhere` from `body` (keep it on `.grow` only if needed).

### F2 High - On a phone the Needs-you box is a wall, and long option labels are cut off at the answer buttons
- Did: 375 px, 4 open questions (one with four 50-70 character options and a 150-character question) plus 2 sessions needing me.
- Happened: the box is 478 px tall; the Sessions heading starts at y=557 of an 812 px screen. Buttons are 345-417 px wide inside a 345 px box that has `overflow:hidden`, so "Split into two pull requests and ask me again in the m..." and "Proceed with the full migration across all 40 files now" lose their ends. Two options differing only at the end would be indistinguishable. Buttons are 26 px tall (target is 44 px).
- Should: options wrap, full width, at least 44 px tall; the default is marked by more than colour.
- Evidence: `$A/02-stress-375-light-needsyou-clipped-options.jpg`; JS: button widths 417x26, 382x26, 367x26, 345x26.
- Suspect: html:16 `button{...;flex:none}` (no wrapping, no max-width), html:9 `.box{overflow:hidden}`, html:19 `.q .line`.
- Patch: `.q button{flex:1 1 100%;white-space:normal;text-align:left;min-height:44px}` below 600 px.

### F3 High - Hub down: the page keeps showing live-looking data, with one small grey phrase
- Did: stopped the hub with the page open, watched 10 s, then restarted.
- Happened: heading summary became "hub not reachable" (html:82, 12 px grey `.mute`). Everything else, including answer buttons and "1m ago" stamps, stayed on screen unchanged, and the "49m" countdown stopped moving. After the restart the page recovered by itself in about 3 s.
- Should: a full-width banner ("hub offline since 14:02, data below is old") and answer buttons disabled, since the POST is swallowed by `catch(e){}` at html:55.
- Evidence: `$A/03-hub-down-stale-page.jpg`.
- Suspect: html:82 (only writes `#sum`), html:55 (silent catch).

### F4 High - Needs-you rows and the Log name the session by raw agent id, not title or project
- Did: opened questions as `a7`; on the live hub the same code reads `q.agent`.
- Happened: "a7 Migration touches 40 files. Proceed?" while the same session is titled "Nightly migration" two inches below. In the real hub the id is a UUID or a 17-character worker id. The question row also has no project, ticket or how long the session has been waiting. Log entries ("Which test runner should the gate suite use? unittest") have no session, no time, and the default-applied ones only differ by a tiny clock icon.
- Should: question rows say "Nightly migration · HomeStudio · 🎫 Migrate 40 files" the way Sessions rows do; Log rows add "by default at 02:14" and the session title.
- Evidence: `$A/07-realistic-10-sessions-desktop.jpg` (row "a7 Migration touches 40 files"); `$A/01-stress-desktop-dark-4questions.jpg` ("s9", "s1", "s3", "s7").
- Suspect: html:67 (`esc(q.agent)`), html:73 (Log row has no agent or time). Fix: look up `s.agents[q.agent]` and reuse `name()`/`where()`/`job()`.

### F5 High - A question whose deadline passes vanishes, and questions the hub restarted past stay as dead buttons
- Did: question with 25 s deadline; watched. Then restarted the hub while 2 questions were open.
- Happened (a): at the deadline the row disappeared with no mark; the Needs-you box shrank 40 px under the pointer (a layout shift while the owner may be aiming at a button). The only trace is a Log line at the bottom of the page. Countdown showed "⏱ 1m" with 24 s left (rounds up to whole minutes; `Math.ceil`), no seconds.
- Happened (b): after the restart the hub kept both questions (state.json) and the page still offered buttons for them, but the asking processes had already taken their defaults ("Split into two pull requests...", "6" in `$A/q2.out`, `$A/q3.out`). Clicking would answer nobody. The owner would think they overrode a decision they did not.
- Should: (a) the last 60 s count in seconds and the row turns urgent; expired rows stay 30 s as "default taken: no"; (b) questions with no live asker are shown greyed as "agent already continued with X" or dropped.
- Evidence: `$A/q2.out`, `$A/q3.out`, `$A/q4.out` ("no"), `$A/stress-state.json`.
- Suspect: html:67 (`Math.ceil((q.deadline-s.now)/60)`), py:104 (default applied, question moves to Log), py:508-525 (`cmd_ask` stops polling when hub is down and prints default).

### F6 High - "Your turn" and "done" agents never reach the Needs-you box
- Did: put one session in `your turn` (agent finished, waiting for me), one `done`, one `blocked`.
- Happened: only `needs you` and `blocked` (plus open questions) count (html:60). On the live hub both main sessions are 💬 "finished its turn" and the heading says 👤 0 and shows no box. For someone who wants to know when to come back overnight, a finished agent is the main thing that needs them.
- Should: either "your turn" counts as needs-you with a lower urgency ("Ready for you: 2"), or the summary counts them separately. Absence of the box must mean "all agents are working", not "all agents stopped".
- Evidence: `$A/06-LIVE-hub-readonly-raw-worker-ids.jpg` (both sessions 💬, 👤 0).
- Suspect: html:60.

### F7 High - Dark scheme: the default answer button fails contrast (2.39:1), and the answer buttons are the main control
- Did: axe-core 4.10.2 in dark scheme.
- Happened: 1 serious `color-contrast`: white text on `#8ea2ff` (`button.def`), 2.39:1. Light scheme is fine (5.67:1). Also `html-has-lang` serious in both schemes.
- Should: dark default button uses dark text or a deeper accent; `<html lang="en">`.
- Evidence: axe output (`button[data-i="2"]`); `<html>` has no lang.
- Suspect: html:17 `button.def{color:#fff}` with html:5 `--acc:#8ea2ff`; html:1 (no `lang`).

### F8 Medium - A session that has been silent for 10+ minutes is dimmed, which reads as "unimportant", not "maybe stuck"
- Did: set one working session to 12 min, one idle to 67 min, one done to 2 h by editing the throwaway hub's state file.
- Happened: all three drop to 40% opacity with no other change. A working agent that stopped reporting 12 min ago (⏳ "sleep") looks the same as a finished one. Computed contrast at 40% opacity: light 2.49:1 (title) and 1.73:1 (grey text); dark 3.36 and 2.0. On the live hub `fx-mini-loader 30f047 "reading your message"` is dimmed at 16 min.
- Should: working + silent 10 min gets a warning chip ("⚠ quiet 12m") and stays full contrast; only done/idle fade.
- Evidence: `$A/stress-state.json`, `$A/06-LIVE-hub-readonly-raw-worker-ids.jpg`.
- Suspect: html:12 `.old{opacity:.4}`, html:34 `old()`.

### F9 Medium - Sessions are not sorted; a 💬 row sits above working rows and urgent rows sit wherever they were created
- Happened: order is insertion order. With 10 sessions, "needs you" and "blocked" rows are in the middle of the list and duplicated in the box above. Finished and idle rows are mixed with the ones running.
- Should: urgent first, then working by oldest silence, then done/idle.
- Evidence: `$A/07-realistic-10-sessions-desktop.jpg`.
- Suspect: html:62, html:69 (`tops.map(...)` no sort).

### F10 Medium - The most useful line, what the owner last asked, is only in a hover tooltip
- Happened: `asked` (the last prompt, e.g. "Okay, now that I read your transcript, I believe...") sits in the `title` of the bold name (html:42). Phones have no hover. No row shows how long it has worked: the grey "2m ago" is time since the last event, not the working time.
- Should: a second line (or tap to expand) with the last ask, 1 line truncated.
- Suspect: html:42.

### F11 Medium - Keyboard focus and hover are destroyed every 2-10 s
- Did: focused an answer button with the keyboard and waited.
- Happened: after about 4-6 s `document.activeElement` became BODY and the button was detached, because a full `innerHTML` rewrite runs on every state change and at least every 10 s (html:75, 84). A user tabbing to a button loses their place; a click that straddles a rewrite can land on a removed node (I also saw stale element refs between find and click).
- Should: re-render only changed rows, or restore focus by `data-q`/`data-i`.
- Suspect: html:75 `app.innerHTML=h`, html:84 (10 s forced refresh).

### F12 Medium - Status glyphs: pips use colour alone; 💬 and 👤 are close; ⏸ is tiny
- See question 4 below. Pip "now" (#3b5bdb) vs "done" (#2e7d4f): 1.12:1 luminance, grey-identical.
- Suspect: html:13, html:29.

### F13 Medium - Project sections repeat boilerplate and push below the fold
- See question 3. 5 projects = about 5 x 85 px, each shows branch, an unlabelled yellow number, last commit, and a closed "Maps in the vault" details, none linked to the sessions above.
- Suspect: html:70, html:51-53.

### F14 Medium - Workers with an unlisted parent become top-level rows and show their raw id
- Did: reported workers whose parent session was not reported.
- Happened: rows "aw1 aw2 aw3" with no project, shown as sessions and counted as 🖥. Live hub: 6 of 11 worker chips show 17-character ids (`aa1e172a02df1c354`).
- Should: untitled worker chips show the role or its last tool ("subagent: Read"), not the id.
- Evidence: `$A/06-LIVE-hub-readonly-raw-worker-ids.jpg`.
- Suspect: html:36 `tk()` falls back to `a.agent`; html:61-62.

### F15 Low - Empty state is the single word "none"
- Did: fresh hub. Happened: "SESSIONS / none", summary all zeros. Should: one line saying how a session appears ("Start a Claude Code session with the hub-report mod; it shows here"). Evidence: `$A/08-empty-state.jpg`. Suspect: html:69.

### F16 Low - Text direction and wide screens
- Arabic title renders inside an LTR row (no `dir="auto"`), project name sits on the wrong side. Page is capped at 900 px and left-aligned, so on a 1440 px laptop 40% of the screen is empty while the content is dense. Suspect: html:6 (`max-width:900px`), html:42.

### F17 Low - HTML-looking text is safe
- `<b>x</b>`, `<img onerror>`, `<script>` shown as literal text everywhere, nothing executed (`esc()` html:26). Recorded here as a pass, not a finding.

## Hard-gate results
| Gate | Result |
|---|---|
| Console errors / warnings | 0 / 0 (console read after each phase: load, click, hub down/up, restart; "No console logs") |
| Network 5xx / 403 / 404 | 0 (hub log has 3 start lines, no error lines); hub-down fetch failure is caught and shown as text |
| Layout collapse | 3 cases: 28-char title at 375 px (F1), 200-char title at 375 and 1440 px (F1), clipped option buttons at 375 px (F2) |
| axe critical | 0 |
| axe serious | light: 1 (`html-has-lang`). dark: 2 (`html-has-lang`, `color-contrast` on the default button). Moderate: `landmark-one-main`, `region` (25 nodes), both schemes |
| Perf on `/` | LCP 328 ms, CLS 0, DCL 5 ms; `/api/state` is 9.7 KB every 2 s |
| Horizontal scroll | none (docW = viewport at 375 and 1440) |

Viewport emulation reset to desktop; throwaway hub stopped (pid 85088). I never clicked or POSTed on the live hub on port 8765.

## Product questions

**1. How long to find "what needs me", with 10 sessions?** One fixation, about 1 second, when something needs you: the box is the first thing under the title, and it is the only bordered, tinted block (`$A/07-realistic-10-sessions-desktop.jpg`). With 10 sessions plus 3 questions and 2 blocked it is 3 rows at desktop. Weak points: the box is the same white card as every other box, only a 1 px accent border (html:19); the title bar `(n)` count helps in a tab. At 375 px with 4 questions it is 478 px and pushes sessions off screen (F2). The absence is NOT clearly good: with nothing open the box is simply missing and the owner must read the tiny `👤 0` in the heading; the "your turn" case (agents stopped, waiting) also shows no box (F6). Add a quiet "Nothing needs you" line, and count finished agents separately.

**2. Is each row self-explanatory to someone who did not start the session?** Mostly yes at desktop for sessions with a title and a ticket: title, project, ticket chip, pips, last tool, age (`$A/07-realistic-10-sessions-desktop.jpg`). It fails for untitled sessions (3 of 5 live) and for questions and workers (F4, F14). The single most missing piece: what the session is doing in words and how long it has been at it. Rank of what to add: (1) the last owner request as a visible truncated second line (already stored as `asked`, F10); (2) working time (started at), since the "ago" stamp is only last activity; (3) unattended/permission mode; (4) branch; (5) model and context size are least useful in a glance. Of the candidates in the brief I would not add model or context size first.

**3. Project provider sections.** Fold them. They answer "is the repo healthy" not "what are my agents doing", they repeat the same 3 chips plus a closed details per project, and with 5 projects they take about 430 px, more than the 10 sessions. Best move: group the sessions by project (a thin project header with branch and dirty count once), and put the test/build widgets as small chips on that header; failing tests or a locked resource should bubble up into Needs you, everything else collapsed into one "Projects" details at the bottom. Keep the log lines in a details.

**4. Pictographs without a legend.** ✅ done, ⛔ blocked, 💤 idle, ⏳ working are guessable. 👤 "needs you" vs 💬 "your turn" are the same idea (the human is next) in two glyphs; I could not tell them apart in the 18 px grayscale screenshot without the tooltip. ⏸ "waiting" has no emoji presentation and renders as a small black "II" smaller than the others. In grayscale (filter on the whole page) the shapes of ⏳ ⛔ 💤 ⏸ 👤 stay distinguishable by shape, so state glyphs mostly pass without colour; pips do not (green done vs blue current is 1.12:1 luminance, so "where is it now" disappears; pending vs done is readable). Chip colours (red for blocked, green for done) are always paired with a glyph, which is fine. Tooltips (`title`) are the only legend and do not exist on a phone: add a one-line legend under the heading, or put the state word next to the glyph for the Needs-you box only.

**5. Starting and queueing overnight runs from this page.** What fits: (a) a "Queue" box between Needs you and Sessions, in the same compact line style: glyph, project, ticket, a small start button, a drag-free up/down; it only needs one more `h2` + `.box` (html:66-70 pattern) fed by the existing ticket data. (b) Per-account usage as chips in the heading line next to 🖥 🤖 👤 🔒 (html:64): a thin bar with a number and reset time, reusing `.bar` (html:20) and the provider `progress` widget kind (html:46). (c) A start button per queued row reusing `button`/`button.def`. What does not fit yet: the layout cannot take another list on a phone until F1/F2 are fixed (a session row is already too wide at 375 px), the hub has no write endpoint for starting a session (not checked deeper than `sbhub.py` usage), and a start button on a page that re-renders every 2-10 s (F11) will mis-fire. The 900 px cap leaves room for a right column at 1440 px.

## What I could not test
- A real 4-10 session overnight run; the live hub had 5 sessions and 11 workers, read only, so ticket pips and worker "done/working" mixtures were seen only on seeded data.
- Real phone: only Chrome emulation at 375x812 (no touch, real keyboard, or phone fonts); the touch-target figures are element sizes.
- Screen-reader announcement of the 2 s refresh (no live region exists; I inferred, did not test with VoiceOver).
- INP separately; slow-network, offline-with-page-open beyond hub-down, print and reduced-motion (page has no animation).
- Login, routes, forms, destructive confirmations and second-user roles: not applicable (one static page, no auth). The answer buttons are the one irreversible action: a single tap, no confirm, no undo, 8 px from the neighbouring option (not exercised on the live hub by rule).
- The macOS notification path (`SB_HUB_NOTIFY=0`).
- A sub-agent self-critique pass (I pruned the draft myself).

## Interaction Manifest (throwaway hub, port 18990, except where marked live)
- Seeded 12 sessions, 6 workers, 5 projects, 200-char title/ticket/note, emoji, RTL, HTML text; opened 4 questions; screenshot 01.
- Waited out the 25 s deadline; read page and `q4.out` ("no").
- Clicked "unittest" via ref; `q1.out` = unittest; Log line read.
- axe-core run in dark then light; console read (0).
- Resized 375x812: measured 478 px box, buttons, row heights; screenshots 02, 05.
- Stopped hub; screenshot 03 ("hub not reachable"); restarted; ghost questions confirmed against `q2.out`, `q3.out`.
- Edited state file for silent sessions; screenshots 04, grayscale filter pass.
- Fresh hub: empty state (08); 10 realistic sessions (07); focus-loss script (7 samples, 2 s apart); clicked "Proceed" with the pointer, `q5.out` = Proceed.
- Live hub (read-only, GET only): screenshot 06 and state read.
