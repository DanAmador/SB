"""sb's half of the wiki. wikibrain reads no tracker, so what the wiki needs of sb's maps happens here,
around every `sbmap wiki <command>` (sbmap passes itself as `sb`, the wikibrain module as `wb`):

- a ticket or research note is a source: `wayfinder` is one of $WIKIBRAIN_SOURCES (sbmap sets it), and
  `<map>#NNN` in a ref becomes the ticket's path; only a resolved ticket may be cited;
- `check` adds the sources that are open tickets or other tracker notes, and bare #NNN in wiki prose;
- `backlog` adds research notes and resolved research tickets no article cites;
- `tend` without --repos verifies the repos the maps name;
- `migrate` relinks wayfinder/ too, and `dump` keeps the `tickets` property in the vault.
"""
import re
import sys
from datetime import date
from pathlib import Path

TICKET_REF = re.compile(r"([\w./-]+)#(\d+)")
TICKET_FILE = re.compile(r"\d+[- ]")
BARE = re.compile(r"(?:^|[^\w/&#\[])#(\d{2,4})\b")


def run(args, sb, wb):
    """wikibrain's command with sb's part before and after it; exits as the command does."""
    name, args = (args[0] if args else None), [ticket_refs(a, sb) for a in args]
    if name == "backlog":
        return backlog(args, sb, wb)
    if name == "tend" and "--repos" not in args:
        args += ["--repos", ",".join(map_repos(sb))]
    if name == "migrate" and "--also" not in args:
        args += ["--also", "wayfinder"]
    if name == "dump" and len(args) > 1:
        args = vault_only(args, sb)
    code = 0
    try:
        wb.main(args)
    except SystemExit as e:
        if name != "check":
            raise
        code = e.code
    if name == "check":
        problems = check(sb, wb)
        for p in problems:
            print(p)
        print(f"{len(tracker_backlog(sb, wb))} more on the backlog from the maps")
        if problems:
            print(f"{len(problems)} problem(s) from the maps")
        sys.exit(1 if code or problems else 0)


def ticket_refs(arg, sb):
    """`arg` with each `<map>#NNN` in it turned into the ticket's vault path; any other arg as it was.
    Exits on a ticket that is not resolved: the wiki cites only what a map has settled."""
    head, eq, value = arg.partition("=") if re.match(r"\w+[+-]?=", arg) else ("", "", arg)
    out, found = [], False
    for ref in re.findall(r"\[\[.*?\]\]|[^,]+", value):
        m = TICKET_REF.fullmatch(ref.strip())
        t = m and ticket(sb, m.group(1), m.group(2))
        if t:
            if t.status != "resolved":
                sys.exit(f"sbmap: {m.group(0).strip()} is a ticket that is not resolved ({t.status})")
            ref, found = sb.rel(t.path)[:-3], True
        out.append(ref)
    return head + eq + ",".join(out) if found else arg


def ticket(sb, map_name, num):
    """The ticket `<map>#<num>` names, or None when no map answers to the name (prose with a #)."""
    try:
        return sb.load(map_name).ticket(num)
    except SystemExit:
        return None


def tracker_class(path, sb):
    """'ticket', 'research', or 'other' for a note under wayfinder/; None outside it."""
    parts = Path(sb.rel(path)).parts
    if parts[:1] != ("wayfinder",):
        return None
    up = Path(path).parent
    if TICKET_FILE.match(Path(path).name) and (up.name == "issues" or up.name == "done" and up.parent.name == "issues"):
        return "ticket"
    return "research" if "research" in parts[:-1] else "other"


def check(sb, wb):
    """What wikibrain cannot see: tracker sources that are not evidence, and #NNN with no map."""
    w, problems = wb.wiki_dir(), []
    for n in wb.articles():
        lab = n.path.relative_to(w).as_posix()
        for e in n.refs("sources"):
            p = wb.target_of(wb.entry_key(e))
            cls = p and tracker_class(p, sb)
            if cls == "ticket" and sb.Ticket(p).status != "resolved":
                problems.append(f"{lab}: {sb.rel(p)[:-3]} is a ticket that is not resolved")
            elif cls == "other":
                problems.append(f"{lab}: {sb.rel(p)[:-3]} is not a research note or a resolved ticket")
    for n in wb.wiki_notes():
        prose = wb.outside_code(n.body, lambda seg: seg)
        bare = re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]\([^)]*\)|https?://\S+", " ", prose)
        for m in BARE.finditer(bare):
            problems.append(f"{n.path.relative_to(w).as_posix()}: bare #{m.group(1)} (`sbmap link` prints the ticket's link)")
    return problems


def backlog(args, sb, wb):
    """wikibrain's backlog plus the maps' research notes and resolved research tickets."""
    project, limit = sb.opt(args, "--project"), int(sb.opt(args, "--limit", 10))
    items = sorted(wb.backlog(project) + tracker_backlog(sb, wb, project))
    for created, key, p in items[:limit]:
        print(f"{key} · {created} · {wb.describe(p)[2]}")
    print(f"{len(items)} on the backlog" + (f", {limit} shown" if len(items) > limit else ""))


def tracker_backlog(sb, wb, project=None):
    """(created, key, path) for each research note and resolved research ticket no article cites."""
    done, items = wb.cited() | wb.no_material(), []
    for p in sorted(sb.WAYFINDER.rglob("*.md")) if sb.WAYFINDER.is_dir() else []:
        cls = "backups" not in p.parts and tracker_class(p, sb)
        if cls == "ticket":
            t = sb.Ticket(p)
            if t.status != "resolved" or t.type != "research":
                continue
        elif cls != "research":
            continue
        key, where = sb.rel(p)[:-3], Path(sb.rel(p)).parts[1]
        if key in done or project and where not in (project, wb.GENERAL):
            continue
        created = str(wb.Note(p).props.get("created") or date.fromtimestamp(p.stat().st_mtime).isoformat())
        items.append((created[:10], key, p))
    return items


def map_repos(sb):
    """The clones the maps name in their `repo` property, each once."""
    out = []
    for m in sb.all_maps():
        p = Path(str(m.props.get("repo") or "")).expanduser()
        if p.is_absolute() and (p / ".git").exists() and str(p) not in out:
            out.append(str(p))
    return out


def vault_only(args, sb):
    """`dump` args whose vault-only properties include `tickets`, keeping what the clone remembers."""
    import wikisync  # beside wikibrain, on the path wiki_module set
    given = sb.opt(args, "--vault-only")
    have = given if given is not None else wikisync.setting(Path(args[1]).expanduser(), "vaultOnly", None, "")
    keys = [k for k in have.split(",") if k.strip()]
    if "tickets" in keys and given is None:
        return args
    keys = ",".join(dict.fromkeys(keys + ["tickets"]))
    if given is None:
        return args + ["--vault-only", keys]
    i = args.index("--vault-only")
    return args[:i + 1] + [keys] + args[i + 2:]
