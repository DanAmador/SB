# sb hub: decisions made on the owner's behalf (2026-11-12)

Branch `sb-hub`, 18 commits from `main` ff1d5e7, 159 tests passing. Each line: what was decided, why, what it costs if wrong. In the order made.

- T3 hooks call `python3 "$HOME/.agents/skills/sb/scripts/sbhub.py" hook` — install.sh links the skill there, a relative path out of the mod is fragile — cost if wrong: one line in hooks.json.
- T3 step 5 (live check, changes owner's config) is not run by the subagent; asked of the owner at the end — cost: hook field names unverified until then.
- T5 by-eye check is done by the controller in the browser pane — cost: none.
- T6 implementer adapts fixture names to the test file's own — cost: none.
- skill edit and docs committed on the branch before Task 1 so task commits by pathspec stay clean — cost: two extra commits to squash if unwanted.
- a project's own provider scripts run only for projects the owner trusted (`sbhub trust <path>`, list in $SB_HUB_HOME/trusted) — a cloned repo must not get code run just because a session opened in it — cost if wrong: one extra command per project. Carried to Task 5 with: project must be an absolute existing dir; symlinked scripts skipped; title/icon/widgets type-checked; changed-event not re-set for a project already queued.
- replace the plan's O_EXCL + 30 s staleness with fcntl.flock (kernel releases on death; file persists), O_EXCL-with-token kept only as the no-fcntl fallback — the spec's "never two holders" outranks the plan's primitive — cost if wrong: Windows path untested here.
- delete the stale-lock fallback; no-fcntl platforms use msvcrt.locking (kernel lock too) — untestable racy code is worse than a small untested kernel call — cost if wrong: Windows claim fails loudly with exit 3.
- workers ask through the hub too, never in chat; only a decision that changes what gets built or cannot be undone cheaply is asked, the rest ruled on the spot — keeps one rule and bounds nine-minute waits — cost if wrong: a worker waits on a question the owner did not care about, or rules alone on one they did.
- every ruling is `R: …, cost if wrong: …`; ticket sessions write it on the ticket, the fallback implementer in its report (operator carries it over) — cost if wrong: one hop for fallback rulings.
- a session's explicit `sbhub report --agent X` and its hook reports are merged into one row — the hook sees the Bash command, tells the hub "this session is X", and later hook events land on X — the spec's card-with-worker-rows needs one row per session — cost if wrong: duplicate rows return; the command parse is the fragile part.
- a lock whose holder is not a listed agent is dropped after 10 minutes — a crashed holder must not block every later run — cost if wrong: a lock held by an unlisted `--by` name expires early.
- Claude Code's idle notice maps to "your turn" with no macOS notification; only a permission request is "needs you" — the owner asked not to be pulled into every conversation — cost if wrong: field name unverified until the live check.
- decided questions are pruned to the last 50 — state.json and `sbhub state` stay small — cost if wrong: older decisions live only on tickets (where rulings are written anyway).
- example provider `.sb/providers/tests` cache key (HEAD + porcelain) misses a second edit to an already-modified file, so it can show a stale green — real, mine (the brief prescribed the key), not load-bearing (an example script, hub core unaffected); deferred to the owner — cost if wrong: the page shows this repo's tests green while a dirty tree is red.

## Left open

- ⚠️ The live hook check (needs `./install.sh --hub`, which changes the Claude Code config): hook field names are unverified against a real session.
- ⚠️ The Windows lock branch cannot run on this Mac.
- ⚠️ The example provider `.sb/providers/tests` can show a stale green on a dirty tree (cache key).
- Minor: an alias can outlive a removed parent's worker; a finished run shows "your turn" until its session ends; port 80 breaks the Host check.
- Out of scope by plan: late answers reaching the agent, phone access, chat widgets.
