# Vault links that open in Obsidian, and kepano's Obsidian skills

Date: 2026-11-10. Size: a small change.

## Why

The owner clicks vault links in the Claude Code Desktop app, and they often fail. The model writes
each link by hand, percent-encoding the whole path, and one sb instruction asks for a format that
the Desktop app sends to Firefox.

A click test in the Desktop app on 2026-11-10 gave these results:

| Format | Example | Result |
|---|---|---|
| A, full path | `obsidian://open?path=%2FUsers%2F…%2FREADME.md` | opens in Obsidian |
| B, vault and note | `obsidian://open?vault=Second%20Brain&file=wayfinder%2FREADME` | opens Firefox |
| C, file link | `file:///Users/…/Second%20Brain/wayfinder/README.md` | opens in Obsidian |
| D, short form | `obsidian:///Users/…/README.md` | opens Firefox |

## Goals

- Every vault link in a Claude Code reply opens the note in Obsidian on the desktop, in sb runs and
  in every other session.
- The model never encodes a link by hand.
- sb uses kepano's Obsidian skills for vault notes it writes outside `sbmap`.

## Non-goals

- Links that open on a phone. The owner chose desktop only on 2026-11-10.
- Changing how links are written inside the vault. Notes keep their wikilinks.

## Anti-goals

- A check that fires on replies with no vault links, or that loops.
- A check that flags paths in commands, such as `sbmap show <map>`.

## Approaches

1. **Printed links plus a check.** The owner picked this one on 2026-11-10. `sbmap` prints finished
   links, every instruction asks for format A, and a check at the end of each reply sends back any
   vault link that will not open.
2. **Printed links only.** Rejected: nothing catches a link written outside sb, and ignored written
   rules are why links fail today.
3. **The check only.** Rejected: the model still encodes by hand, so every catch costs a redo.

## Design

1. **`sbmap uri <file> [label]`** prints `[label](obsidian://open?path=<absolute path, fully
   percent-encoded>)`. The label defaults to the note's title, or to its file name. The command
   accepts a path inside the vault, absolute or relative to it.
2. **One format in every instruction.** [output.md](../../../skills/sb/reference/output.md) tells the
   model to get links from `sbmap uri`. [close.md](../../../skills/sb/verbs/close.md) drops format B.
   The Plain output style gets one line: a vault link in chat comes from `sbmap uri`, never typed.
3. **The check** is a `Stop` hook, a script that runs when a reply ends. It ships as a new mod,
   `vault-link-check`, which `install.sh` installs in every config. It reads the last
   assistant reply and flags:
   - an `obsidian://` link that is not `open?path=`;
   - a format A link whose decoded path does not exist (this catches encoding mistakes);
   - a markdown link to a vault file by plain path, absolute or relative;
   - a `[[wikilink]]` in chat.

   It ignores inline code and code blocks, and `file://` links (format C works). When it finds
   something, it blocks once with a reason that names each bad link and the `sbmap uri` command that
   fixes it. When `stop_hook_active` is set, it lets the reply through, so it can't loop.
   **What the owner sees:** the bad reply stays on screen, and a corrected one follows a few seconds
   later. A Stop hook cannot rewrite a reply that has already been shown.
4. **Kepano's skills.** Commit the `skills-lock.json` entries (`obsidian-markdown`, `obsidian-cli`,
   `obsidian-bases`, `json-canvas`, `knap`). sb's SKILL.md says: load `obsidian-markdown` before
   writing a vault note by hand (handoffs, reports, research notes), `obsidian-bases` before editing a
   `.base`, and use `obsidian-cli` for vault reads that `sbmap` doesn't cover.
5. **The terminal mod stays.** Its redraw still makes format A clickable in terminal `claude`.

## Calls I made (operator defaults, not owner rulings)

- The check runs in every session, not only sb runs. The owner was told this and didn't object.
- The check is a new mod, `vault-link-check`, not part of `obsidian-links`. No installed plugin
  mixes a mod module and a command hook in one `hooks.json`, so a separate mod is the safe choice.
  It follows `quiet-tests`' pattern (a Python hook with stdlib tests).
- `sbmap new` keeps printing only the path, because tests and callers parse it. `sbmap show` prints
  the link.
- Bare vault paths in backticks are not flagged: they are often arguments to commands.

## Left to the builder

- Which other `sbmap` outputs print a `uri` link beside the ticket (at least `show` and `new`).
- Tests: `sbmap uri` encoding (spaces, `#`, `&`, non-ASCII) and the check's flag and pass cases, in
  `tests/`.
