# Session analysis: how the owner works with coding agents (2026-10-22 to 2026-11-12)

Source: Claude Code transcripts under `~/.claude`, `~/.claude-personal`, `~/.claude-assembio`, files modified in the last 21 days. Times are Europe/Berlin (transcripts store UTC). Scripts: `/private/tmp/claude-501/-Users-danamador-Documents-Coding-sb-workflow/4177cc3d-7705-4c0f-8e57-1bd6e1e0e606/scratchpad/`. Quotes are the owner's words, shortened; names of people and shows are left out.

## 0. Scope in numbers

| item | value |
|---|---|
| jsonl files read | 2,781 |
| main sessions with activity | 510 (217 automated HomeStudio pipeline calls, 293 interactive) |
| subagent transcripts | about 1,700 (1,154 general-purpose, 458 implementer, 41 Explore, 18 scout, 6 fork) |
| account split by tokens | `.claude` 99.9%, `.claude-personal` 0.1% (pipeline plus a few tests), `.claude-assembio` 2 turns |
| `/sb` slash invocations seen | 113 (plus 2 `/mattpocock-skills:wayfinder`); first words: `tonight` 10, `draft` 10, `resume` 7, `close` 4, `chart` 2, `morning` 2, `continue` 3, bare `/sb <free text>` 30 |

`/sb chart` is rare (2). The owner's real brainstorm entry is `/sb draft` and free text after `/sb`.

Projects, ordered by tokens (main plus subagents, deduplicated):

| project | in+cache M | output M | share of in+cache | turns above 150k |
|---|---|---|---|---|
| HomeStudio | 7,137 | 25.3 | 28.2% | 60% |
| sk4te | 6,952 | 23.4 | 27.5% | 69% |
| monorepo (plus worktrees) | 4,566 (+248) | 14.1 (+0.8) | 18.0% (+1.0%) | 67% |
| semantic-graph (plus plugin-release) | 3,630 (+375) | 16.5 (+1.5) | 14.3% (+1.5%) | 57% |
| scratch workspaces (no project folder) | 1,094 | 4.5 | 4.3% | 55% |
| sb-workflow | 814 | 6.9 | 3.2% | 50% |
| fx-mini-loader | 298 | 2.9 | 1.2% | 68% |
| agent-stuff | 158 | 0.8 | 0.6% | 45% |
| automated pipeline (tmp dir) | 20.5 | 0.6 | 0.1% | 0% |
| total | 25,301 | 97.3 | 100% | 62% |

## 1. Findings

### Q1. Brainstorm sessions

Cohort: 41 "brainstorm" plus 15 "audit" main sessions (heuristic in section 8), 56 to 58 sessions.

- Every session starts heavy. First assistant turn context median is 86k tokens (p10 79k, p90 115k) for brainstorm, 88k for orchestrator, 93k for spawned sessions, against 45k for the headless pipeline. About 85k is fixed overhead before the owner's first word.
- After the first round (the owner's first message plus the agent's reply) context is already 148k median (p90 224k) for brainstorm and audit.
- Peak context: median 307k, max 860k. 45 of 56 sessions pass 150k. 9 sessions show a "continued from a previous conversation that ran out of context" message.
- Length: owner turns per brainstorm session median 7 (mean 11.0); with audits median 9 (mean 10.9). Agent turns median about 200.
- Messages: first message median 658 chars, and 15 of 58 first messages are 1,000 chars or more. Across all 576 owner messages median 182 chars, p90 871, 24 are 1,000 or more. The data cannot show speech-to-text directly. One message says so: "No. The speech to text was buggy." (sb-workflow, 11-08).
- Map or plan written: 26 of 58 sessions wrote something into the vault `wayfinder/` tree (map, ticket, research note or handoff). The first such write comes after a median of 3 owner turns (range 1 to 18), at a context median of 184k (min 112k, max 380k). So the "before a plan is written" size is about 180k, and most of that is the opening load, not the discussion.
- Questions: 634 owner-to-agent rounds in the cohort. 189 rounds (30%) contain a question in agent prose or a card, 2.7 question marks per asking round. Only 12 rounds (1.9%) used cards (`AskUserQuestion`, 55 cards in total). Across all interactive sessions: 2,724 rounds, 785 asking rounds, 67 with cards (8.5%). Prose is the dominant form.
- How the owner answers the 173 asking rounds in the cohort: 28 short yes/go style (16%), 79 real answers of 150 chars or more (46%), 66 in between (38%), 2 flagged by the strict correction regex (1%). In orchestrator sessions: 43 of 346 short affirmations (12%), 183 long (53%), 8 corrections.
- Corrections, all interactive sessions, deduplicated, short messages only (1,458): 29 start with no/wait/stop/don't, 24 contain "I mean / I said / not what I", 11 "you forgot / still not". The categories overlap, so about 4% of messages is an upper bound, not a sum.
- Looking things up (cohort, counted over the whole session): 341 vault, wiki or map reads (about 6 per session), 166 code reads, 25 codegraph calls, 197 subagent dispatches. The owner told the agent to look something up in 9 messages by regex, for example "use wayfinder with markdown set in the second brain folder so you can operate entirely locally" (sk4te, 10-23) and "that file path looks obtuse, why not just use the direct Second Brain vault" (semantic-graph, 10-24).
- Owner pushing back on content in a brainstorm: "No, I just want to continue with the cleanup" (sk4te, 10-24); "Does this handoff have the entire overnight implementation or just a fix?" (sk4te, 11-05).

### Q2. Unattended runs

- Orchestrator sessions: 54 in 3 weeks (ISO week 43: 2 starting 10-22; week 44: 16; week 45: 21; week 46 to 11-12: 15). With "tonight" in the first messages: 17 (6, 7, 4 per week). Peak overlap on 11-11: 14 sessions active in one hour.
- Most overnight starts are handoff-driven: 17 first messages read `Read <vault>/…handoff.md and do what it says`, written by the brainstorm session the evening before.
- Tickets: the `implementer` agent type appears from 11-03. 458 implementer subagents were dispatched, 341 distinct ticket ids, 34 repeat dispatches for an id already dispatched. Of 401 attached to orchestrator sessions, 397 returned `finished` (99%). Models: 249 opus, 111 sonnet, 98 not recorded. Before 11-03 the same work ran as general-purpose subagents (1,154 in all, 53 in one session).
- Queued versus landed cannot be read from transcripts. Whether a ticket landed (merged, resolved) is recorded in the vault. In main sessions `sbmap` calls: 72 `new`, 102 `claim`, 120 `resolve` (subagent calls are not in this count).
- Orchestrator context: max context median 348k, p max 902k; 83.5% of orchestrator main-session turns sit above 150k; 46 context-ran-out continuations across 54 orchestrators. The 365k to 367k ceiling shows up in 14 of the orchestrators, which looks like an auto-compaction cutoff.
- Wall span of an orchestrator session is 0.1 to 26 h (includes idle time, so not a work time).
- Stalls from usage limits, visible in transcripts: 50 assistant limit messages. Windows: 8 five-hour session windows (10-23, 10-24 x2, 10-25 x3, 10-27, 10-29), 2 organisation spend-limit windows (10-25, 10-27), 2 weekly windows (hit 11-08 on `.claude-personal`, hit 11-09 on `.claude`; reset 11-10 14:00 and 11-12 23:00). One `Usage limit reached · continuing automatically` system message on 11-10 (personal account).
- After 10-29 no five-hour limit message appears on the main account until the weekly one on 11-09. The owner's runs after 11-03 are paced explicitly instead (see below).
- Next owner message after a limit hit:
  - "I hit my usage limit while you were working, but it has reset now. Please continue from where you left off." (identical text 9 times, 10-23 to 11-10). Looks pasted or generated, I cannot tell which.
  - "Try again" 13 times (8 sessions).
  - "PLease continue once the tokens are back" (semantic-graph, 10-25); "continue, tokens are back" (monorepo, 11-02); "continue, you ran out of tokens" (sk4te audit, 11-10).
  - Gap from limit to owner's reply, where measurable: 0.3 h to 3.5 h (examples 0.3, 1.4, 2.0, 3.2, 3.5).
- Idle gaps of 2 h or more between an agent message and the owner's reply: 83 in interactive sessions, 20 of them right after the agent asked something (orchestrator 11 of 37). Examples: 8.7 h waiting on a three-item question (HomeStudio, 11-01), 13.0 h (sk4te, 10-30), 6.2 h (sk4te, 11-11).
- Owner asks "waiting for me ?" (scratch workspace, 10-31) and "Why don't you continue with the implementation? Why stop at the checkpoint?" (monorepo, 10-27).
- Pacing instructions in orchestrator sessions: "We have 4 agents running. Pace the implementation to maximize tokens so that we don't go into timeout errors" (monorepo, 10-29); "other agents are waiting until the reset, please pace with them" (agent-stuff, 11-03); "stop after the next ticket finishes, we are running out of tokens and i still need some for tomorrow" (sb-workflow, 11-09). 17 messages mention pacing, budget or the 5-hour window.
- Cannot be seen: permission prompts, crashes, a question nobody answered (only the idle gaps above), because the transcripts do not record them. 46 "[Request interrupted by user]" messages are the only explicit stop signals.

### Q3. Several sessions at once

Non-pipeline main sessions with an assistant or subagent turn in the same local hour (344 active hours):

| measure | value |
|---|---|
| hours with 2 or more sessions | 259 (75%) |
| hours with 3 or more | 177 |
| hours with 5 or more | 75 |
| peak | 18 sessions in one hour |

Night view (22:00 to 08:00 local), sessions per hour at the peak and projects involved:

| night starting | hours with 2+ | peak | projects at peak |
|---|---|---|---|
| 10-23 | 8 | 7 | HomeStudio, sk4te |
| 10-24 | 7 | 9 | semantic-graph, sk4te |
| 10-26 | 7 | 7 | HomeStudio, monorepo, sb-workflow, semantic-graph |
| 10-27 | 10 | 6 | HomeStudio, semantic-graph, sk4te |
| 10-28 | 9 | 5 | HomeStudio, sb-workflow, scratch, plugin-release, sk4te |
| 10-29 | 9 | 6 | monorepo, scratch, sk4te |
| 11-03 | 7 | 8 | agent-stuff, sb-workflow, semantic-graph, sk4te |
| 11-06 | 7 | 3 | HomeStudio, sk4te |
| 11-07 | 7 | 5 | HomeStudio, sk4te, pipeline |
| 11-08 | 8 | 5 | HomeStudio, sb-workflow, sk4te |
| 11-10 | 7 | 13 | agent-stuff, monorepo, semantic-graph, sk4te |
| 11-11 | 8 | 14 | HomeStudio, monorepo, sb-workflow, semantic-graph, sk4te |

Nights with fewer than 2 hours of overlap: 11-01, 11-04, 11-09, 11-12 (partial).

Shared usage limit, direct evidence (same reset time hit by several sessions):

| limit message (reset time) | hit on | sessions | projects |
|---|---|---|---|
| session, resets 4:40 | 10-24 | 5 | HomeStudio, semantic-graph, sk4te |
| session, resets 3:50 | 10-24 | 4 | semantic-graph, sk4te |
| session, resets 23:10 | 10-27 | 4 | HomeStudio, semantic-graph, sk4te |
| session, resets 5:20 | 10-23 | 2 | HomeStudio, sk4te |
| session, resets 13:50 / 19:00 | 10-25 | 2 each | semantic-graph, sk4te |
| session, resets 18:00 | 10-29 | 2 | HomeStudio, monorepo |

Owner's words on this: "reping all agetns that need input to continue as i ran out of tokens" (sk4te, 10-24); "ping all running agents so that they continue autonomously" (semantic-graph, 10-27); "It seems they are all waiting for the usage reset, what's the eta" (agent-stuff, 11-03); "present the lanes we can use to maximize the 5 hour limit" (scratch, 10-28).

Audit sessions (heuristic: audit, assess or ux-audit in the first message): 17 sessions, plus 2 `/ass:assess` runs on pull requests.
- Start: as `/sb draft <goal>` in an interactive session, or `/ass:assess <PR>`, or a `Background (from the session that started this one)` spawned session. The owner starts several at once: on 11-12 at 18:28 to 18:37 four near-identical "create an audit of tickets to improve the UI/streamline…" drafts started in HomeStudio, semantic-graph (x2) and sk4te; on 11-04 two identical monorepo assess sessions at 18:30; on 11-12 01:27 two identical sk4te audit drafts. Duplicates are partly the same prompt pasted in several windows.
- Length: 0.7 h to 4.8 h wall, 6 to 17 owner turns, 54 to 111 agent turns, context 209k to 397k at peak; subagents used: general-purpose 2 to 7, Explore 1 to 6.
- Output: vault notes under `wayfinder/<project>/<map>/research/*audit*.md`, `handoff.md`, `checkpoint.md`; for assess runs a PR description (written to temp files then applied) and a note in memory. 5 of the 6 audit drafts started on 11-12 wrote nothing to the vault (only the HomeStudio one did).
- Model: audit sessions ran 71% of tokens on `claude-fable-5-2`, 29% on opus. Owner on cost: "Wait how does fable fix budget !? It's more expensive" (sk4te, 11-07). Fable is used for planning, then implementation goes to opus and sonnet agents.
- No `ux-audit` skill invocation found in the user turns.

### Q4. Where tokens go

Totals, deduplicated by message id (1,918 repeated turns, 560M tokens, 2.2% removed): fresh input 0.5M, cache creation 461M, cache read 24,839M, output 97.3M. Cache reads are 98.2% of "input plus cache". Weekly: week 43 (from 10-22) 3.3B in+cache / 9.3M out; week 44 10.9B / 41.3M; week 45 6.7B / 25.3M; week 46 (to 11-12) 4.4B / 21.5M. Busiest days: 10-27 and 10-28 (2.4B and 2.6B in+cache, about 9.8M output each).

By session type (main session plus its own subagents):

| type | sessions | in+cache M | share | output M | share |
|---|---|---|---|---|---|
| orchestrator | 54 | 11,674 (main 3,700, subagents 7,974) | 46.1% | 47.1 | 48.4% |
| other | 101 | 6,692 (3,708 + 2,985) | 26.5% | 22.5 | 23.2% |
| spawned-handoff | 83 | 3,361 (1,984 + 1,376) | 13.3% | 12.2 | 12.5% |
| brainstorm | 41 | 2,873 (1,598 + 1,274) | 11.4% | 11.7 | 12.1% |
| audit | 15 | 680 (197 + 483) | 2.7% | 3.2 | 3.3% |
| automated pipeline | 217 | 21 | 0.1% | 0.6 | 0.6% |

By subagent type: general-purpose 9,229M (65.5% of subagent total), implementer 4,634M (32.9%), Explore 153M, fork 71M, scout 3M. Subagents are 55.7% of all in+cache and 68.5% of output.

By model (all turns): opus-5-5 74.7% of in+cache and 67.3% of output; sonnet-5-5 19.9% and 27.1%; opus-5 3.1% and 1.6%; fable-5-2 1.7% and 2.0%; haiku-5-5 0.4% and 1.7%; fable-5-1 0.2%. Per type, main-session share: orchestrator 97.5% opus-5-5; brainstorm 93.2% opus-5-5; spawned-handoff 76% opus-5-5 and 22% sonnet; audit 71% fable.

Past 150k context: 62.0% of all turns, 80.0% of in+cache tokens, 67.0% of output tokens, 48.8% of cache-creation tokens; 14.9% of turns are above 300k. Main sessions: orchestrator 83.5% of turns, brainstorm 82.4%, other 81.5%, spawned 78.4%, audit 79.9%. Subagents: 45 to 56% (Explore 19.5%).

Largest sessions by output: one "other" semantic-graph session 5.3M output, 29.4M cache creation; orchestrators in sk4te, sb-workflow, HomeStudio (x2), fx-mini-loader, scratch, monorepo, semantic-graph at 2.4 to 3.7M output each; one HomeStudio brainstorm 2.3M.

### Q5. Repeated friction (owner messages, short ones, deduplicated; categories overlap)

| rank | kind | count | sessions | example |
|---|---|---|---|---|
| 1 | "yes" plus an action (push, merge, commit, build, start, run) | 66 | 41 | "Yes, run it, but also make sure that the combinations are different cards" (sk4te, 11-06) |
| 2 | "[Request interrupted by user]" | 46 | 42 | (no text) |
| 3 | plain questions ("can you / how do I / why") | 45 | 33 | "Why don't you continue with the implementation? Why stop at the checkpoint?" (monorepo, 10-27) |
| 4 | "this is great, but …" (partial accept, adjust) | 42 | 33 | "This is great. But keep the cards still" (HomeStudio, 11-12) |
| 5 | taste or "doesn't feel right" corrections | 41 | 32 | "primary and secondary take too much space, we need to be more pictographic" (sk4te, 10-27) |
| 6 | ping, or ask about other or previous agents | 32 | 29 | "what's the eta to completion of all agents and give me a summary" (monorepo, 10-30) |
| 7 | plain yes / go / sounds good | 30 | 26 | "Sounds good" |
| 8 | no / wait / stop / don't | 29 | 27 | "no, the controllers is for monorepo, not the skill" (monorepo, 10-29) |
| 9 | status ("where are we", "what is open", "how long") | 26 | 24 | "How long would running the whole show take ?" (HomeStudio, 11-08) |
| 10 | "I mean / I said / not what I asked" | 24 | 23 | "i meant the comedy community brand kit" (HomeStudio, 11-08) |
| 11 | limit and tokens talk | 24 | 22 | "continue, tokens are back" (monorepo, 11-02) |
| 12 | continue / keep going / resume | 23 | 19 | "just continue working" (HomeStudio, 10-22) |
| 13 | "did you / have you …?" | 16 | 16 | "Did the codegraph lint only work on the frontend?" (monorepo, 10-30) |
| 14 | "Try again" | 13 | 8 | "Try again" |
| 15 | forgot / missed / still not | 11 | 9 | "you didn't start b c ?" (sk4te, 10-22) |
| 16 | stop asking / just do it | 5 | 5 | "why are you asking this question mid implementation ? I'm curious" (HomeStudio, 10-22) |

Also: 9 identical "I hit my usage limit while you were working…" messages. Ranks 1, 7 and 12 are approval gates, not complaints.

### Q6. What a central queue or dashboard would remove (repeated asks)

| ask | count (deduplicated, regex) | evidence |
|---|---|---|
| what can run tonight / how many hours of work / what maps are open | 43 messages, 32 sessions | "what are some tasks i can enqueue and leave running for the next couple of hours" (sk4te, 11-08) |
| ETA or state of the other running agents | 48 messages, 42 sessions | "Read all the running agents and calculate an ETA of how long they'll work" (sk4te, 10-24) |
| continue, try again, ping stalled agents after a limit | 37 messages, 24 sessions (plus 9 identical template messages) | "reping all agetns that need input to continue as i ran out of tokens" |
| pace the sessions against one token budget | 17 messages, 15 sessions | "We have 4 agents running. Pace the implementation to maximize tokens" |
| push, merge, commit instructions | 76 messages, 49 sessions | "Push the five annotation-stack merge-forwards to origin as one atomic push" |
| read a handoff file and do what it says | 17 sessions | `Read <vault>/…/handoff.md and do what it says` |
| send me links that open the map or ticket in Obsidian | 7 messages | "Share the links that open directly to obsidian for me to review, especially the map" (semantic-graph, 10-27) |
| keep chat short, put detail in docs | stated, 1 | "keep the chat on Claude as minimalistic and to the point as possible" (sb-workflow, 10-27) |

Sessions already talk to each other by hand: 72 `<cross-session-message>` messages and 624 background-agent `<task-notification>` messages arrived as owner-role turns (they sit in the user channel, so each one wakes an orchestrator).

## 2. Decision-relevant reading (my inference, not measured)

- A shared budget matters: on 10-24 (two windows) and 10-27, 4 to 5 sessions hit the same reset time. After 10-29 the owner moved to manual pacing by prompt. A scheduler that knows the 5-hour window and the weekly cap would replace sentences like the pacing ones in Q2.
- Context cost is dominated by size: 80% of tokens are in turns past 150k, and every session starts at about 86k. Fewer or leaner tools and instructions at start would cut cost on every turn of every session; cutting a brainstorm's discussion would not.
- Questions go in prose (92% of asking rounds), and the owner mostly answers at length (46 to 53%). A card queue would be a new habit, not a rewrite of an existing one. Short yes/go replies are a minority (12 to 16%), so multiple choice should leave room for free text.
- Idle gaps of 6 to 13 h after an agent question are the main visible overnight stall cause besides limits; the hub's queue of questions addresses these directly.
- The owner uses other tools: plans are written "for my antigravity agent to implement" and "for cheaper or dumber agents (such as gemini)" (HomeStudio 11-09, sk4te 11-09). Those runs are not in this data.

## 3. What the data cannot show

- Sessions in Antigravity, Codex, Gemini or the claude.ai app: no transcripts in these folders. `~/.codex`, `~/.gemini`, `~/.antigravity*` do not exist. Only three traces: the two messages above, and "i had a conversation with antigravity about these UI changes" (semantic-graph, 10-26).
- Work-account sessions: `~/.claude-assembio` holds 2 turns in 21 days, yet the owner mentions another agent that "ran out of tokens (from claude-assemblio)" (sk4te, 11-10). That agent's transcript is not here.
- Permission prompts, crashes, killed terminals: not recorded as events.
- Whether a ticket landed: not in transcripts (vault only).
- Speech-to-text use: only inferable from length and wording.
- Question cards answered by tool result: card answers are tool results and not in the owner-message counts. Cards are counted from the agent side (55 in the brainstorm cohort).

## 4. Method

- Parsed every `*.jsonl` (including `subagents/`) with mtime in the last 21 days, keeping turns with timestamp 2026-10-22 or later.
- Owner message: `type:user`, not `isMeta`, not `isSidechain` (main files), text parts only, `<system-reminder>` blocks removed, empty and tool-result-only turns dropped. Counted separately: `<task-notification>`, `<cross-session-message>`, `<ci-monitor-event>`, and compaction summaries ("This session is being continued").
- Assistant tokens: `message.usage`, one row per `message.id` (multi-block messages merged by max output). Global deduplication by message id across files (forks and resumes copy history). In+cache = input + cache read + cache creation.
- Subagent type from the sibling `*.meta.json` (`agentType`). Parent session from the folder name.
- Limits: assistant, system or API-error lines matching "hit your session/weekly limit", "spend limit", "Usage limit reached".
- Concurrency: a session counts for an hour if it or its subagents have any assistant turn in that local hour.
- Question counts: `?` in assistant text blocks per round (a round is everything between two owner messages), plus `AskUserQuestion` and `sb_ask` tool calls (questions array length).
- Owner reply classes: short affirmation = starts with yes/go/ok/sure/sounds good/proceed/merge/push etc. and 120 chars or less; long = 150 chars or more and not affirmation; correction = starts with no/nope/wait/stop/hold on/actually/not quite/I meant, or contains "not what I", "you forgot", "you didn't", "still not".

## 5. Heuristics and how they can be wrong

- Session type is a regex on the first real owner message (skipping `/clear`, `/model`, compaction summaries):
  - auto-pipeline: transcript-tool prompts ("Each clip below…", "You pick shorts…") or the tmp-dir project. Reliable.
  - spawned-handoff: starts "Background (from the session that started this one)" or "Task (from…)". Reliable; these are side sessions an orchestrator or another session opened.
  - orchestrator: "tonight", "overnight", "agents running", "orchestrat", "handoff" in the first 300 chars, or 4 or more implementer subagents. Over-counts: draft or planning sessions that mention "tonight" or read a handoff.
  - audit: "audit", "assess" or "ux-audit" in the first 300 chars. Includes `/sb draft` goals phrased as an audit and a merge task named "gameplayAudit" (2 sessions); some real audits that start with other words are in "other".
  - brainstorm: chart, wayfinder, draft, let's think, grill, design, plan, idea, "want to". Under-counts; "other" (101) contains many free-text brainstorms that did not use these words.
  - Token shares by type move with these rules; the orchestrator bucket especially.
- Lookup counts use path regexes (Second Brain, `/wiki/`, wikibrain, wayfinder) and cover the whole session if no vault write happened.
- Friction categories are regex on short messages, overlapping; counts are upper bounds per kind. "Status" misses phrases that do not use the listed words.
- Duplicate sessions (forks, pasted twice) inflate session counts; message counts in Q5 and Q6 are deduplicated by timestamp plus first 60 chars, session metrics in Q1 are not.
- Time zone: all clock times converted to Europe/Berlin with daylight saving.
- Wall span of a session includes idle time and is not work time.
