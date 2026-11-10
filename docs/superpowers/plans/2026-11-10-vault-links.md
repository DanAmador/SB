# Vault links that open in Obsidian: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every vault link in a Claude Code Desktop reply opens the note in Obsidian, because `sbmap` prints it and a Stop hook sends back any that won't open; sb also points at kepano's Obsidian skills.

**Architecture:** A new `sbmap uri` command builds the one working link format. A new mod, `vault-link-check`, is a Python `Stop` hook that scans the reply that just ended and blocks once with fix instructions. Instructions (sb skill, Plain output style) point at `sbmap uri`.

**Tech Stack:** Python 3 stdlib, unittest, Claude Code plugin hooks, bash (`install.sh`).

**Spec:** [docs/superpowers/specs/2026-11-10-vault-links-design.md](../specs/2026-11-10-vault-links-design.md)

## Global Constraints

- The only link format in chat is format A: `obsidian://open?path=` + the absolute path with every reserved character percent-encoded (`urllib.parse.quote(path, safe="")`).
- The vault is `$SB_VAULT`, else `~/Documents/Second Brain`.
- `file://` links to the vault are allowed (they open in Obsidian); format B (`vault=…&file=…`) and the short form `obsidian:///…` are not.
- The hook blocks at most once per reply: it never blocks when `stop_hook_active` is true.
- Inline code and fenced code blocks are never scanned.
- `sbmap new` keeps printing only the path (tests and callers parse it).
- Stdlib only; tests run with `python3 -m unittest discover tests` and `python3 mods/vault-link-check/test_check.py`.

## Review Focus

1. A vault path with `#`, `&`, `?`, `%` or non-ASCII letters (`Café.md`): `sbmap uri` encodes it so Obsidian opens it, and the hook decodes it back and finds the file. Tested in Task 1 and Task 2.
2. A reply that only *mentions* a vault path in backticks, such as `` `sbmap show sb-workflow/x` ``: the hook lets it through. Tested in Task 2.
3. A reply with no links at all, or links only to `https://` pages: the hook prints nothing and exits 0. Tested in Task 2.
4. A malformed or empty stdin, or a transcript path that doesn't exist: the hook exits 0 and never blocks (a broken check must not trap the owner). Tested in Task 2.
5. The vault set through `SB_VAULT` with or without a trailing slash: both sbmap and the hook treat it the same. Tested in Task 2.

---

### Task 1: `sbmap uri`, and `show` prints the ticket's link

**Files:**
- Modify: `skills/sb/scripts/sbmap.py` (usage docstring "read" block; new `obsidian_uri`, `cmd_uri`; `cmd_show`; `COMMANDS`)
- Test: `tests/test_uri.py`

**Interfaces:**
- Produces: `obsidian_uri(path: Path) -> str` returning `obsidian://open?path=<quote(str(path.resolve()), safe="")>`.
- Produces: CLI `sbmap uri <file> [label]`. `<file>` is absolute, or relative to the vault, or relative to the current directory (tried in that order). With the `.md` left off it still finds `<file>.md`. Prints one line: `[<label>](<obsidian_uri>)`. The label defaults to the note's `title` property, else its file name without `.md`. A file that doesn't exist exits non-zero with `sbmap: no such vault file: <file>`.
- Produces: `sbmap show` prints `link: [<NNN> <title>](<obsidian_uri>)` as its second line.

- [ ] **Step 1: Write the failing tests** in `tests/test_uri.py` (a `VaultCase`):
  - `test_relative_path_gets_full_uri`: write `wayfinder/README.md`; `sb("uri", "wayfinder/README.md").stdout.strip()` equals `"[README](obsidian://open?path=" + quote(str((self.vault / "wayfinder/README.md").resolve()), safe="") + ")"`.
  - `test_label_and_title`: a note with frontmatter `title: Route rules` prints `[Route rules](…)`; passing `"My label"` as the second argument prints `[My label](…)`.
  - `test_md_suffix_optional`: `uri wayfinder/README` prints the same link as with `.md`.
  - `test_reserved_characters`: for a file named `a #1 & b?.md` and one named `Café.md`, the URI contains no space, `#`, `&`, `?` or `/` after `path=`, and `unquote` of the part after `path=` equals the resolved absolute path.
  - `test_missing_file_fails`: `sb("uri", "nope.md", ok=False)`; stderr names `nope.md`.
  - `test_show_prints_link`: after `init` and `new` (as in `tests/test_info.py`), the second line of `show <map> 1` starts with `link: [001 ` and contains `obsidian://open?path=`.

- [ ] **Step 2: Run them to see them fail**
  Run: `python3 -m unittest tests.test_uri -v`
  Expected: FAIL (`uri` is not a command; usage text on exit).

- [ ] **Step 3: Implement** `obsidian_uri`, `cmd_uri`, the `show` line, the `COMMANDS` entry, and a usage line in the "read" block of the module docstring: `sbmap.py uri <file> [label]   the markdown link that opens a vault file in Obsidian: paste it, never type one`. Use the existing `split_fm` to read `title`.

- [ ] **Step 4: Run all sbmap tests**
  Run: `python3 -m unittest discover tests -v`
  Expected: all PASS, the six new tests included.

- [ ] **Step 5: Commit**
  ```bash
  git add skills/sb/scripts/sbmap.py tests/test_uri.py
  git commit -m "feat: sbmap uri prints the link that opens a vault file in Obsidian"
  ```

### Task 2: the `vault-link-check` mod

**Files:**
- Create: `mods/vault-link-check/check.py`
- Create: `mods/vault-link-check/hooks/hooks.json`
- Create: `mods/vault-link-check/.claude-plugin/plugin.json`
- Create: `mods/vault-link-check/test_check.py`
- Modify: `.claude-plugin/marketplace.json` (the marketplace file in `.claude-plugin/`): add `{ "name": "vault-link-check", "source": "./mods/vault-link-check" }`
- Modify: `install.sh`: `cc plugin install vault-link-check@sb-workflow` next to the `obsidian-links` line; mention it in the "claude not found" warning.

**Interfaces:**
- Consumes: the `sbmap uri` CLI from Task 1, named in the hook's fix text only (no import).
- Produces: `bad_links(text: str, vault: str, cwd: str) -> list[tuple[str, str]]`, each item `(the link as written, why it fails)`.
- Produces: `reply_text(data: dict) -> str`: `data["last_assistant_message"]` when present and a string, else the text blocks of the assistant entries in `data["transcript_path"]` (JSONL) after the last user entry that is not a tool result; `""` on any read error.
- Produces: `main(stdin, stdout) -> int`: always returns 0. When `stop_hook_active` is false and `bad_links` is not empty, writes `{"decision": "block", "reason": <text>}`. The reason lists up to 5 bad links with why each fails, then: `Rewrite each as the line printed by: python3 ~/.agents/skills/sb/scripts/sbmap.py uri "<vault file>". Send only the corrected links, not the whole reply again.`
- `hooks.json`: `{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/check.py\"", "timeout": 10}]}]}}`.
- `plugin.json`: `{ "name": "vault-link-check", "version": "0.1.0", "description": "Sends back a reply whose vault links won't open in Obsidian" }`.

What `bad_links` flags, after removing fenced code blocks and inline code spans:
1. A markdown link `](obsidian://…)` that is not `obsidian://open?path=`: "opens Firefox, not Obsidian".
2. A format A link whose decoded path does not exist: "no such file (encoding mistake?)". Format A links outside the vault are checked too.
3. A markdown link `](target)` whose target is not a URL (no `scheme:`), where `unquote(target)`, made absolute against `cwd` when relative, falls inside the vault: "a plain path; the Desktop app can't open vault files".
4. A `[[wikilink]]`: "wikilinks only work inside Obsidian".
Not flagged: `file://` links, `https://`/`http://` links, links to files outside the vault, anything inside code.

- [ ] **Step 1: Write the failing tests** in `mods/vault-link-check/test_check.py` (stdlib `unittest`, a temp dir as the vault holding `wayfinder/README.md` and `Café #1.md`; import `check` by path like `mods/quiet-tests/test_filter.py`):
  - `test_good_links_pass`: format A to both files (built with `quote(..., safe="")`), a `file://` link, and an `https://` link give `[]`.
  - `test_format_b_flagged`, `test_short_form_flagged`: one item each, reason contains `Firefox`.
  - `test_broken_encoding_flagged`: `obsidian://open?path=` + the path with `/` left unencoded and a typo in the file name gives one item, reason contains `no such file`.
  - `test_plain_paths_flagged`: `[x](/abs/vault/wayfinder/README.md)`, `[x](/abs/vault/Caf%C3%A9%20%231.md)` and a relative `[x](../Vault/wayfinder/README.md)` with `cwd` beside the vault each give one item.
  - `test_wikilink_flagged`: `see [[wayfinder/README]]` gives one item.
  - `test_code_ignored`: the same bad links inside backticks and inside a ```` ``` ```` block give `[]`.
  - `test_vault_trailing_slash`: `bad_links` gives the same answer for `vault` with and without a trailing `/`.
  - `test_main_blocks_once`: `main` with `last_assistant_message` holding a format B link writes JSON with `"decision": "block"` and the `sbmap.py uri` hint; the same input with `"stop_hook_active": true` writes nothing.
  - `test_main_reads_transcript`: no `last_assistant_message`; a JSONL transcript whose last user entry is followed by two assistant entries (one text block holding a bad link, one tool_use block) blocks. A tool-result user entry between them doesn't count as the last user entry.
  - `test_main_never_traps`: empty stdin, `not json`, and a missing `transcript_path` each return 0 and write nothing.

- [ ] **Step 2: Run them to see them fail**
  Run: `python3 mods/vault-link-check/test_check.py -v`
  Expected: FAIL (`check` module not found).

- [ ] **Step 3: Implement** `check.py` with the interfaces above, a module docstring like `quiet_tests.py`'s, and `if __name__ == "__main__": sys.exit(main(sys.stdin, sys.stdout))`. The vault comes from `SB_VAULT`, else `~/Documents/Second Brain`, normalized with `os.path.realpath`. `cwd` comes from `data["cwd"]`, else `os.getcwd()`. Write the plugin files and the marketplace and `install.sh` lines.

- [ ] **Step 4: Run the tests**
  Run: `python3 mods/vault-link-check/test_check.py -v && bash -n install.sh`
  Expected: all PASS; `bash -n` prints nothing.

- [ ] **Step 5: Install it and confirm it loads**
  Run: `claude plugin marketplace update sb-workflow; claude plugin install vault-link-check@sb-workflow && claude plugin list | grep vault-link-check`
  Expected: `vault-link-check@sb-workflow` listed as enabled.

- [ ] **Step 6: Commit**
  ```bash
  git add mods/vault-link-check .claude-plugin/marketplace.json install.sh
  git commit -m "feat: vault-link-check, a Stop hook that sends back vault links that won't open"
  ```

### Task 3: instructions use `sbmap uri`, and sb points at kepano's skills

**Files:**
- Modify: `skills/sb/reference/output.md` (the "Tickets by name" bullet)
- Modify: `skills/sb/verbs/close.md` (the "## Report" paragraph that asks for `vault=…&file=…`)
- Modify: `output-styles/plain.md` (one bullet under "## Words")
- Modify: `skills/sb/SKILL.md` (one short block near the `sbmap` bullet)
- Modify: `README.md` (Requirements: the link mod paragraph; Install: the mod paragraph)
- Commit: `skills-lock.json` (the owner's pending change that adds kepano's five skills)

- [ ] **Step 1: output.md.** Replace the hand-encoding instructions with: in chat, a ticket or note is a markdown link printed by `sbmap uri <file> [label]` (pasted, never typed); label a ticket `<name> #NNN`. In the vault, a wikilink (`sbmap link`), as now.

- [ ] **Step 2: close.md.** Replace the `obsidian://open?vault=…&file=…` sentence with: in chat, link the report with the line `sbmap uri <report>` prints.

- [ ] **Step 3: plain.md.** Add under "## Words": `- A link to a note in the Obsidian vault is the line \`python3 ~/.agents/skills/sb/scripts/sbmap.py uri "<file>"\` prints, pasted as is. Never type an \`obsidian://\` link, a plain vault path as a link, or a [[wikilink]] in chat.`

- [ ] **Step 4: SKILL.md.** Add after the `sbmap` bullet: `- **Kepano's Obsidian skills:** load \`obsidian-markdown\` before writing a vault note by hand (handoffs, reports, research notes), \`obsidian-bases\` before editing a \`.base\`, and use \`obsidian-cli\` for vault reads sbmap doesn't cover.`

- [ ] **Step 5: README.md.** Say chat links come from `sbmap uri`, that `vault-link-check` sends back a reply whose vault links won't open (the bad reply stays on screen and a corrected one follows), and that `obsidian-links` still makes them clickable in terminal `claude`. Add `sbmap uri` to the sbmap command list if the README has one.

- [ ] **Step 6: Check nothing else asks for a hand-typed link**
  Run: `grep -rn "obsidian://" skills output-styles README.md`
  Expected: only lines that mention `sbmap uri` or describe the mods.

- [ ] **Step 7: Commit**
  ```bash
  git add skills/sb/reference/output.md skills/sb/verbs/close.md output-styles/plain.md skills/sb/SKILL.md README.md skills-lock.json docs/superpowers
  git commit -m "docs: chat links come from sbmap uri; sb points at kepano's Obsidian skills"
  ```

### Task 4: try it in the Desktop app

- [ ] **Step 1:** In a new Desktop session in this repo, ask for a link to the vault's `wayfinder/README.md`. Expected: the reply holds the `sbmap uri` line, and clicking it opens Obsidian.
- [ ] **Step 2:** Ask the session to paste `[x](obsidian://open?vault=Second%20Brain&file=wayfinder%2FREADME)` as a link. Expected: the hook sends it back, and a corrected link follows.
