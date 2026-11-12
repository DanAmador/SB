# Headless worker spike: one ticket through `claude -p` in auto mode

Date 2026-11-13. Task 1 of the hub-queue plan. Every line below is observed unless marked inference. No product code changed.

## Setup (observed)

- Temp git repo (README.md, one commit), temp vault via `SB_VAULT`, temp hub home, `SB_HUB_NOTIFY=0`, hub on port 55936 (not 8765, not ~/.sb-hub, not the real vault). Hub stopped afterwards.
- Ticket: `sbmap init spike`, then `sbmap new spike` made ticket 001, type task, "Add a `greet(name)` function to `hello.py` returning `Hello, <name>`", Done when `python3 -c 'import hello; assert hello.greet("a")=="Hello, a"'` exits 0, paths hello.py. sbmap stripped the `<` and `>` from the file name (`001 Add a ... returning `Hello, name `.md`); `show spike 001` still found it by number.
- Command: `CLAUDE_CONFIG_DIR=~/.claude-personal SB_HUB_PORT=55936 SB_HUB_NOTIFY=0 SB_HUB_HOME=<tmp> SB_VAULT=<vault> perl -e 'alarm 900; exec @ARGV' ~/.local/bin/claude -p "<brief>" --permission-mode auto --model sonnet --output-format json`, cwd the temp repo.
- Two starts. The first died with exit 127 in 0 s before any model call: macOS has no `timeout`. I fixed it with a perl alarm wrapper (the 15-minute cap). Only the second start reached the model: one paid run.

## The brief sent (observed)

The session-brief template filled by hand. It named: the repo path and branch `main`; `~/.claude/agents/implementer.md`; a run board file I wrote (one contract line, the done-when as the check); the ticket by `python3 ~/.claude/skills/sb/scripts/sbmap.py show spike 001` (script path spelled out; the brief said `SB_VAULT` is in the environment); the title, why, the do line (`def greet(name): return f"Hello, {name}"` in `hello.py`), leave-alone (every other file), done-when; commit once by pathspec with `Ticket: spike/001` as the last line; do not resolve; rulings via `sbmap comment`; start and end `sbhub.py report --agent spike-worker --role worker --parent spike-run --ticket greet` (script path spelled out, no port in the command); report to `run/001.md`; two-line last message. No `sbhub ask` clause (no blocking decision expected).

## Result (observed)

- Exit code 0. Wall time 20 s by shell clock (JSON `duration_ms` 16285, `duration_api_ms` 10554). `num_turns` 4, `is_error` false, `subtype` "success", `terminal_reason` "completed", `stop_reason` "end_turn", `permission_denials` `[]`. stderr empty.
- `total_cost_usd` 0.1162 (claude-sonnet-5-5, `costBasis` "list").
- Commit landed in the temp repo: `08ce97f feat: add greet(name) to hello.py`, body last line `Ticket: spike/001`. Working tree clean afterwards, only hello.py added, not pushed. The Done-when command exits 0 when I ran it.
- The worker wrote `run/001.md` (commit, check, files).
- `sbmap` was reachable: `python3 ~/.claude/skills/sb/scripts/sbmap.py show spike 001` printed the ticket digest, using `SB_VAULT` from the env. The worker's first Bash call exited 1 (it wrote `echo ======`, which zsh took as a command); it re-ran without it. It made no `sbmap comment` (no rulings), so the ticket's Comments stayed empty.

## JSON keys (observed)

Top level: `type` "result", `subtype` str, `is_error` bool, `api_error_status` null, `result` str (the final message: two lines, what works and the report path), `stop_reason` str, `terminal_reason` str, `session_id` str (uuid), `uuid` str, `num_turns` int, `duration_ms` int, `duration_api_ms` int, `total_cost_usd` float, `permission_denials` list (empty), `safety_stops` int 0, `fast_mode_state` "off", `credential_expires_at` str, plus timing fields (`ttft_ms`, `time_to_request_ms`, several `*_detail` objects).
`usage`: `input_tokens` 8, `cache_creation_input_tokens` 22516, `cache_read_input_tokens` 157945, `output_tokens` 1037, `service_tier` "standard", `iterations` list, plus `server_tool_use`, `cache_creation`, `speed`.
`modelUsage`: object keyed by model id, each with `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `costUSD`, `contextWindow` 1000000, `maxOutputTokens` 128000.
`subagent_stats`: counts, all 0.
`usage.iterations` held one entry (the last API call: 45566 cache-read, 557 cache-creation, 2 input tokens), not one per turn.

## First turn's context size

The JSON does not give the first call alone. Usage sums four calls; 22516 tokens were written to cache once, and the last call read 45.6k. Inference: the first call's context was about 22.5k tokens (all new), so a cold headless start in this config carries about 22k tokens before the brief's own work.

## Auto mode (observed)

Nothing refused: `permission_denials` empty, `safety_stops` 0, every Bash call ran (cat, sbmap, python, git add, git commit, sbhub report, heredoc file write). A refusal would presumably show as entries in `permission_denials`; not observed, so its shape is unknown.

## Plugins and the hub (observed, one open question)

- Plugins load headless under `CLAUDE_CONFIG_DIR=~/.claude-personal`: the transcript lists the `plugin:hub-report:sbhub` MCP tools, and the tokeneconomizer hooks ran (SessionStart, PostToolUse, PostToolUseFailure, Stop, exit 0).
- The hub's `/api/state` after the run had `agents` empty: no `spike-worker`, no session row. Its `providers` held the temp repo's path, so something reported that project to the hub. Inference: the hub-report SessionStart hook reached it, and SessionEnd then removed the session (SessionEnd maps to state "gone"). The transcript has no `hook_success` entry for the hub-report hooks (`sbhub.py hook` prints nothing), so their firing is not directly confirmed.
- The worker's two `sbhub.py report --agent spike-worker` calls exited with no error output but left no agent on my hub. The same command run by me afterwards with `SB_HUB_PORT=55936` from the repo dir registered an agent at once. So the worker's calls did not reach port 55936. Cause not determined: the Bash tool env may drop `SB_HUB_PORT`, or its sandbox may block localhost; `report` exits 0 silently when the hub is unreachable. No second run was made to find out.
- For Task 5: do not count on a worker's `sbhub report` reaching the hub, and do not judge the run from agent rows after exit. Put `SB_HUB_PORT=<port>` inline in the brief's report command, or have the launcher record start and end itself. The launcher can check the commit and trailer in code; both were there.

## Limits

Not observed. Task 5's limit pattern list stays the strings the session analysis quotes.

## Status

The commit landed with the trailer and auto mode blocked nothing, so no ruling is needed before Task 5 on that. Open: whether worker-side hub reports and the hub-report hooks reach a hub on a non-default port from a headless session.
