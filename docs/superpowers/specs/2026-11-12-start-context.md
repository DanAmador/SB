# What fills a session before the owner's first word (2026-11-12)

Measured on this repo's desktop session 72661b78 (first turn: 78,331 tokens), from the request the
transcript records (`api-request-shape`, `api-request-blob`). Sizes are characters of the recorded
JSON; the token column scales them to the 78k actually billed, so it is an estimate (JSON escapes
and schemas do not tokenize evenly).

| part | chars | ≈ tokens | share | who controls it |
|---|---|---|---|---|
| Tool definitions (48 tools) | 85,200 | 37k | 47% | partly the owner |
| · built-in (Bash, Agent, Edit, SendMessage…, 16) | 36,900 | 16k | | the harness |
| · in-app browser (19 tools) | 22,400 | 10k | | per-session connector toggle |
| · task list + wrap-up (2) | 8,000 | 3.5k | | the desktop app |
| · iOS simulator (1) | 6,900 | 3k | | per-session connector toggle |
| · visualize (2), session (4), docs (3), terminal (1) | 10,900 | 4.5k | | the desktop app / connectors |
| System prompt | 33,300 | 14k | 18% | the harness |
| Skill and agent list (about 95 skills, one line each) | 33,200 | 14k | 18% | **the owner: installed plugins and skills** |
| Names of deferred tools (about 190) | 6,700 | 3k | 4% | the owner: connectors |
| MCP server instructions (Blender ≈3.5k, docs, Atlassian, codegraph) | 9,000 | 4k | 5% | the owner: connectors |
| CLAUDE.md, memory index, git status | 5,900 | 2.5k | 3% | the owner |
| Superpowers intro + output style | 5,000 | 2k | 3% | the owner |

## What follows

- About 40% is the harness's own (system prompt, built-in tools): not cuttable.
- **The skill list is the largest part the owner controls: ≈14k tokens in every session.** Several
  skills overlap (two TDD, two debugging, two code-review, five document formats, three browser
  guides). Skills set to `disable-model-invocation` are still user-callable and leave the list.
- **Desktop-only tools cost ≈17k** (browser, simulator, visualize, task list). A ticket worker
  never uses them.
- **A headless session starts at about 45k** (the analysis measured the HomeStudio pipeline's
  `claude -p` calls), against 80 to 120k in the desktop app. So a hub queue that starts workers
  headless roughly halves each worker's fixed cost, before any trimming.
- Blender's instructions (≈1.5k tokens) and about 190 deferred tool names ride along in projects
  that never use them.

## Not measured

- Whether a headless start is 45k with this machine's full plugin set (the pipeline may run with
  its own config).
- Subagent start sizes (the analysis says subagents are 56% of input tokens).
- The token split is scaled from characters, not counted per part.

## Headless check (2026-11-12, late)

One `claude -p "Reply with the single word ok." --model haiku` in this repo, on the personal
account (`CLAUDE_CONFIG_DIR=~/.claude-personal`): **28,655 tokens** on its only turn
(6,887 cache read + 21,766 cache write + 2), against 78,331 for the desktop session in the same
repo. Not a like-for-like pair: another config folder (its own plugin set) and another model.
