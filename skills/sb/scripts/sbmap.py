#!/usr/bin/env python3
"""sbmap: the deterministic half of the vault's wayfinder tracker.

Reads and writes the local tracker the vault's `wayfinder/README.md` defines: a folder per map
(`map.md`, `issues/<NNN> <Title>.md`, `board.base`), every ticket's fields in Obsidian properties
(frontmatter) and every reference between tickets a wikilink, so Obsidian's graph, backlinks and
Bases see the whole route. It answers what an agent should never compute or type by eye.

  read
    sbmap.py maps [--repo <path>]       every map in the vault (or one repo's), with counts
    sbmap.py status   <map>             counts, claimed tickets, the frontier, handoff/checkpoint files
    sbmap.py frontier <map>             open tickets whose every blocker is resolved, in map order
    sbmap.py show     <map> <NNN>       succinct digest: status, type, blockers, question, done when
    sbmap.py lanes    <map> [--max 2] [--json]
                                        open tickets split into parallel lanes by their paths and
                                        blockers, the rest serial (ticket 009's rule)
    sbmap.py next     <map>             the next free ticket number for this map's repo
    sbmap.py link     <map> <NNN>       the wikilink to a ticket, to paste into prose
    sbmap.py check    <map>             lint: unknown blockers, cycles, missing Answers or Decisions,
                                        legacy fields, and (Obsidian running) broken links
    sbmap.py verify   <map>             every mermaid block parses in Obsidian's own renderer
  write
    sbmap.py init     <map> --title "<name>" --destination "<goal>" [--done-when "..."] [--repo <path>]
                                        scaffolds map.md, board.base, issues/ and initial Route
    sbmap.py new      <map> --title "<sentence>" [--type task] [--priority S..F|high|normal|low]
                            [--question "..."] [--done-when "..."]
                            [--blocked-by 622,623] [--paths src/a.py,docs/] [--comments "..."] [--no-sync]
                                        full ticket creation with properties, wikilinks & auto-sync
    sbmap.py comment  <map> <NNN> --text "<ruling or comment>"
                                        appends dated entry to ## Comments
    sbmap.py set      <map> <NNN> key=value ... [--no-sync]
                                        ticket properties (status, type, claimed_by, ...)
    sbmap.py claim    <map> <NNN> --by "<session or harness/model>" [--no-sync]
    sbmap.py block    <map> <NNN> <refs, comma separated: numbers, map folder names, or none> [--no-sync]
    sbmap.py resolve  <map> <NNN> --gist "<one line>" [--answer "..."] [--commit <sha>] [--no-sync]
                                        records ## Answer, marks resolved, adds Decisions line, syncs Route
    sbmap.py diagram  <map> [--write] [--hide-resolved]
                                        the route as mermaid; --write stamps it into map.md
    sbmap.py board    <map>             (re)writes the map's board.base (embedded in map.md), its repo's
                                        wayfinder/<repo>/board.base and wayfinder/frontier.base
    sbmap.py migrate  <map|--all> [--write]
                                        header lines -> properties, bare numbers -> wikilinks, plus
                                        the board; a dry run unless --write. Idempotent.
    sbmap.py close    <map>             refuses while a ticket is open or claimed; writes report.md
                                        from templates/map-report.md and marks the map resolved
  wiki
    sbmap.py wiki <command> ...         the compiled wiki under wiki/: `sbmap.py wiki` lists its commands

<map> is a folder name under the vault's wayfinder/ (`sk4te-single-player`) or a path.
The vault is $SB_VAULT, else ~/Documents/Second Brain, so it runs from any directory.
Standard library only, so any harness with python3 can run it. The files are the source of
truth; the Obsidian CLI adds checks when the app is running.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from datetime import date
from pathlib import Path, PurePosixPath

VAULT = Path(os.environ.get("SB_VAULT", Path.home() / "Documents" / "Second Brain"))
WAYFINDER = VAULT / "wayfinder"
START, END = "%% sb:diagram:start %%", "%% sb:diagram:end %%"  # Obsidian comments: hidden in every view
OLD_MARKERS = ("<!-- sb:diagram:start -->", "<!-- sb:diagram:end -->")
STATUSES = ("open", "claimed", "resolved", "out-of-scope")
WF_TO_OPERON_STATUS = {
    "open": "Project.Planned",
    "claimed": "Project.InProgress",
    "resolved": "Project.Finished",
    "out-of-scope": "Project.Dropped",
}
OPERON_TO_WF_STATUS = {
    "project.planned": "open",
    "project.inprogress": "claimed",
    "project.finished": "resolved",
    "project.dropped": "out-of-scope",
    "planned": "open",
    "inprogress": "claimed",
    "finished": "resolved",
    "dropped": "out-of-scope",
}
CLEARED = {"resolved", "out-of-scope"}
SHAPES = {  # mermaid node shape per ticket type
    "task": ('["', '"]'),
    "grilling": ('("', '")'),
    "research": ('[/"', '"/]'),
    "prototype": ('[["', '"]]'),
    "architecture": ('{{"', '"}}'),
}
TICKET_KEYS = ["wayfinder", "operonId", "number", "title", "project", "aliases", "status", "type",
               "priority", "created", "completed", "map", "blocked_by", "claimed_by",
               "paths", "github", "tags"]
MAP_KEYS = ["wayfinder", "project", "status", "aliases", "repo", "github", "tags"]
# Operon's priorities are letters, S highest, C its default; sbmap takes either the letter or a word
OPERON_PRIORITIES = ("S", "A", "B", "C", "D", "E", "F")
PRIORITY_WORDS = {"urgent": "S", "critical": "S", "high": "A", "normal": "C", "medium": "C", "low": "E",
                  "someday": "F"}
FINISHED = '["Project.Finished", "Project.Dropped"]'  # the statuses that clear a blocker, as Operon writes them
LEGACY = {"Status": "status", "Type": "type", "Blocked by": "blocked_by", "GitHub": "github",
          "Claimed by": "claimed_by"}


# ---- properties -----------------------------------------------------------

def split_fm(text):
    """(properties, body, had_frontmatter). Reads the YAML subset sbmap itself writes."""
    if not text.startswith("---\n"):
        return {}, text, False
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text, False
    props, key = {}, None
    for line in text[4:end].splitlines():
        item = re.match(r"^\s+-\s*(.*)$", line)
        kv = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if item and key is not None:
            props.setdefault(key, [])
            if isinstance(props[key], list):
                props[key].append(unquote(item.group(1)))
        elif kv:
            key, value = kv.group(1), kv.group(2).strip()
            if value in ("", "[]"):
                props[key] = []
            elif value.startswith("[") and value.endswith("]") and not value.startswith("[["):
                props[key] = [unquote(v) for v in value[1:-1].split(",") if v.strip()]
            else:
                props[key] = unquote(value)
    return props, text[end + 5:], True


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def scalar(v):
    v = str(v)
    if v == "" or re.search(r"[:#\[\]{}&*!|>'\"%@`,]|^[-?\s]|\s$", v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def dump_fm(props, order):
    keys = [k for k in order if k in props] + [k for k in props if k not in order]
    lines = ["---"]
    for k in keys:
        v = props[k]
        if isinstance(v, list):
            if not v:
                continue
            lines.append(f"{k}:")
            # a bare 001 or true in a list is a number or a boolean to YAML, and Obsidian flags a
            # list of text (aliases) holding one as a type mismatch
            lines += [f'  - "{x}"' if re.fullmatch(r"[-+.\d]+|true|false|null|~", str(x), re.I)
                      else f"  - {scalar(x)}" for x in v]
        elif v not in (None, ""):
            lines.append(f"{k}: {scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def legacy_fields(body):
    """Header lines (`Status: open`) between the H1 and the first section, the pre-properties form."""
    head = body.split("\n## ", 1)[0]
    found = {}
    for name, key in LEGACY.items():
        m = re.search(rf"^{name}:[ \t]*(.*)$", head, re.M)
        if m:
            found[key] = m.group(1).strip()
    return found


def strip_legacy(body):
    head, sep, rest = body.partition("\n## ")
    for name in LEGACY:
        head = re.sub(rf"^{name}:[ \t]*.*\n?", "", head, flags=re.M)
    head = re.sub(r"\n{3,}", "\n\n", head)
    return (head.rstrip("\n") + "\n" if sep else head) + sep + rest


def write_atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def md_target(name):
    """A file name as a markdown link target, encoded the way Obsidian writes its own: spaces only."""
    return name.replace(" ", "%20")


def sources(listing):
    """Obsidian's comma-joined source paths; a comma inside a file name is not a separator, and
    the part after one holds no `/`."""
    out = []
    for part in listing.split(", "):
        if out and "/" not in part:
            out[-1] += ", " + part
        else:
            out.append(part.strip())
    return out


def wikilink(path, alias):
    target = rel(path)
    target = target[:-3] if target.endswith(".md") else target
    return f"[[{target}|{alias}]]"


def link_target(ref):
    """The file a `[[target|alias]]` points at, or None."""
    m = re.fullmatch(r"\s*\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]\s*", ref)
    if not m:
        return None
    p = VAULT / m.group(1)
    return p if p.suffix == ".md" else p.with_name(p.name + ".md")


# ---- model ----------------------------------------------------------------

class Ticket:
    def __init__(self, path):
        self.path = path
        self.num = int(re.match(r"(\d+)", path.name).group(1))
        self.text = path.read_text(encoding="utf-8")
        self.props, self.body, self.has_fm = split_fm(self.text)
        fields = dict(self.props) if self.has_fm else legacy_fields(self.body)
        # the title is a property; tickets from before it was one carry it as their H1
        self.title = str(fields.get("title") or (re.search(r"^# (.+)$", self.body, re.M) or [None, path.stem])[1]).strip()
        raw_status = str(fields.get("status") or "open").lower()
        self.raw_status = fields.get("status") or "open"
        self.status = OPERON_TO_WF_STATUS.get(raw_status, raw_status)
        self.type = str(fields.get("type") or "task").lower()
        raw = fields.get("blocked_by") or []
        self.blocked_by = raw if isinstance(raw, list) else [b.strip() for b in raw.split(",") if b.strip()]
        self.claimed_by = fields.get("claimed_by") or ""
        raw = fields.get("paths") or []
        self.paths = raw if isinstance(raw, list) else split_list(raw)
        # `## Answer` is the convention; tickets moved from GitHub carry `## Resolved in ...`
        # or the resolution as their last comment.
        self.has_answer = bool(re.search(r"^## (Answer|Resolved|Comments)\b", self.text, re.M))

    @property
    def id(self):
        return f"{self.num:03d}"

    def link(self, alias=None):
        return wikilink(self.path, alias or self.id)

    def save(self, props, body=None):
        self.props, self.has_fm = props, True
        if body is not None:
            self.body = body
        self.text = dump_fm(props, TICKET_KEYS) + self.body.lstrip("\n")
        self.has_answer = bool(re.search(r"^## (Answer|Resolved|Comments)\b", self.text, re.M))
        write_atomic(self.path, self.text)


class Map:
    def __init__(self, folder):
        self.folder = folder
        self.md_path = folder / "map.md"
        self.md = self.md_path.read_text(encoding="utf-8") if self.md_path.exists() else ""
        self.props, self.body, self.has_fm = split_fm(self.md)
        fields = self.props if self.has_fm else legacy_fields(self.body)
        self.title = (re.search(r"^# (.+)$", self.body, re.M) or [None, folder.name])[1].strip()
        raw_status = str(fields.get("status") or "open").lower()
        self.raw_status = fields.get("status") or "open"
        self.status = OPERON_TO_WF_STATUS.get(raw_status, raw_status)
        self.github = str(fields.get("github") or "")
        issues = folder / "issues"
        self.tickets = {}
        for p in sorted(issues.glob("*.md")) if issues.exists() else []:
            if re.match(r"\d+", p.name):
                t = Ticket(p)
                self.tickets[t.num] = t

    @property
    def rel_folder(self):
        try:
            return self.folder.resolve().relative_to(WAYFINDER.resolve())
        except ValueError:
            return Path(self.folder.name)

    @property
    def rel_name(self):
        return str(self.rel_folder)

    @property
    def effort_slug(self):
        parts = self.rel_folder.parts
        return "-".join(parts) if len(parts) > 1 else self.folder.name

    @property
    def repo(self):
        parts = self.rel_folder.parts
        if len(parts) > 1:
            return parts[0]
        return self.folder.name.split("-", 1)[0]

    def link(self, alias=None):
        return wikilink(self.md_path, alias or self.title)

    def ticket(self, num):
        t = self.tickets.get(int(num))
        if t is None:
            sys.exit(f"sbmap: no ticket {num} in {self.folder.name}")
        return t

    def resolve_ref(self, ref):
        """A blocked_by entry or a bare reference -> a Ticket, a Map, or None."""
        ref = str(ref).strip()
        target = link_target(ref)
        if target is None and ref.endswith(".md"):
            target = (self.folder / "issues" / ref).resolve()
        if target is not None:
            if not target.exists():
                return None
            return Map(target.parent) if target.name == "map.md" else Ticket(target)
        if re.fullmatch(r"#?\d+", ref):
            n = int(ref.lstrip("#"))
            return self.tickets.get(n) or sibling_ticket(self, n)
        folder = WAYFINDER / ref
        if (folder / "map.md").exists():
            return Map(folder)
        if "-" in ref:
            f2 = WAYFINDER / ref.replace("-", "/", 1)
            if (f2 / "map.md").exists():
                return Map(f2)
        f3 = self.folder.parent / ref
        if (f3 / "map.md").exists():
            return Map(f3)
        return None

    def blocker(self, ref):
        """(label, cleared, ticket-or-None) for one blocked_by entry."""
        x = self.resolve_ref(ref)
        if isinstance(x, Map):
            return f"map: {x.title}", x.status == "resolved", None
        if isinstance(x, Ticket):
            return f"{x.id} {x.title}", x.status in CLEARED, x
        return str(ref), False, None

    def order(self):
        """Tickets in map order: first mention of their file in map.md, then by number."""
        def key(t):
            i = self.md.find(t.path.stem)
            return (0, i, t.num) if i >= 0 else (1, 0, t.num)
        return sorted(self.tickets.values(), key=key)

    def frontier(self):
        return [t for t in self.order()
                if t.status == "open" and all(self.blocker(b)[1] for b in t.blocked_by)]

    def save(self, props, body):
        write_atomic(self.md_path, dump_fm(props, MAP_KEYS) + body.lstrip("\n"))
        self.__init__(self.folder)


def sibling_ticket(m, num):
    """A number not in this map: shared across repo maps."""
    hits = [f for f in WAYFINDER.glob(f"{m.repo}/**/issues/*.md")
            if re.match(rf"0*{num}-", f.name)]
    if not hits:
        hits = [f for f in WAYFINDER.glob(f"{m.repo}-*/issues/*.md")
                if re.match(rf"0*{num}-", f.name)]
    return Ticket(hits[0]) if len(hits) == 1 else None


def load(arg):
    p = Path(arg).expanduser()
    if p.is_dir() and (p / "map.md").exists():
        return Map(p)
    if p.name == "map.md" and p.exists():
        return Map(p.parent)
    folder = p if p.is_dir() else WAYFINDER / arg
    if folder.name == "map.md":
        folder = folder.parent
    if (folder / "map.md").exists():
        return Map(folder)
    if "-" in arg:
        dash_p = WAYFINDER / arg.replace("-", "/", 1)
        if (dash_p / "map.md").exists():
            return Map(dash_p)
    for f in WAYFINDER.glob("**/map.md"):
        if "backups" in f.parts:
            continue
        rel_str = str(f.parent.relative_to(WAYFINDER))
        slug = rel_str.replace("/", "-")
        if f.parent.name == arg or rel_str == arg or slug == arg or f.parent.name.endswith(f"-{arg}"):
            return Map(f.parent)
    sys.exit(f"sbmap: no map.md in {folder}")


def all_maps():
    maps = []
    for f in sorted(WAYFINDER.glob("**/map.md")):
        if "backups" in f.parts or ".system" in f.parts:
            continue
        maps.append(Map(f.parent))
    return maps


def obsidian(*args, timeout=15):
    """Run the Obsidian CLI against this vault; None when it is missing, closed or fails."""
    exe = shutil.which("obsidian")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, f"vault={VAULT.name}", *args], capture_output=True, text=True,
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.strip()
    if r.returncode != 0 or out.startswith("Error"):
        return None
    return out


def rel(path):
    """The vault-relative path Obsidian speaks; the absolute path for a map outside the vault."""
    p = Path(path).resolve()
    try:
        return str(p.relative_to(VAULT.resolve()))
    except ValueError:
        return str(p)


def split_list(value):
    return [x.strip() for x in str(value).split(",") if x.strip()]


def opt(args, name, default=None):
    if name in args:
        idx = args.index(name)
        if idx + 1 < len(args):
            return args[idx + 1]
    return default


# ---- read commands --------------------------------------------------------

def belongs(m, repo):
    """A map is a repo's when its folder prefix is the repo's name or its map.md names the repo."""
    repo = Path(repo).expanduser().resolve()
    return (m.repo == repo.name or str(repo) in m.md or f"`{repo.name}`" in m.md
            or str(m.props.get("repo", "")) == str(repo))


def trail(m):
    """Handoff and checkpoint files beside the maps that name this map or its repo prefix."""
    candidates = list(WAYFINDER.glob("*.md"))
    if (WAYFINDER / m.repo).is_dir():
        candidates += list((WAYFINDER / m.repo).glob("*.md"))
    return sorted(p for p in set(candidates)
                  if re.search(r"-(handoff|checkpoint)\.md$", p.name)
                  and (p.name.startswith(m.effort_slug) or p.name.startswith(m.repo + "-")
                       or m.effort_slug in p.read_text(encoding="utf-8")
                       or m.folder.name in p.read_text(encoding="utf-8")))


def counts(m):
    c = {}
    for t in m.tickets.values():
        c[t.status] = c.get(t.status, 0) + 1
    return ", ".join(f"{v} {k}" for k, v in sorted(c.items()))


def cmd_maps(args):
    repo = opt(args, "--repo")
    for m in all_maps():
        if repo and not belongs(m, repo):
            continue
        print(f"{m.rel_name:32} {m.status:9} {len(m.frontier()):2} on frontier · {counts(m)}")
        print(f"{'':32} {m.title}")


def cmd_status(args):
    m = load(args[0])
    print(f"# {m.title}  (status: {m.status})")
    print("counts: " + counts(m))
    claimed = [t for t in m.order() if t.status == "claimed"]
    if claimed:
        print("claimed (someone's, or a stale claim from a dead session):")
        for t in claimed:
            print(f"  {t.id} {t.title}  [{t.claimed_by or 'claimant unknown'}]")
    print("frontier:")
    for t in m.frontier():
        print(f"  {t.id} [{t.type}] {t.title}")
    if not m.frontier():
        print("  (empty)")
    files = trail(m)
    print("handoff/checkpoint: " + (", ".join(p.name for p in files) if files else "none"))


def cmd_frontier(args):
    m = load(args[0])
    for t in m.frontier():
        print(f"{t.id}\t{t.type}\t{t.title}\t{t.path}")


def overlap(a, b):
    """Two ticket path lists share a file: one path is the other or a folder holding it."""
    return any(x.parts[:len(y.parts)] == y.parts or y.parts[:len(x.parts)] == x.parts
               for x in map(PurePosixPath, a) for y in map(PurePosixPath, b))


def plan_lanes(m, most=2):
    """The lane split ticket 009 decided: open tickets in map order, each placed once its blockers
    are cleared or placed. A ticket joins the lane it conflicts with (shared paths or a blocker),
    opens a lane while there are fewer than `most`, else joins the shortest; one that conflicts with
    two lanes or the serial tail, or has no paths, goes serial, after every lane."""
    lanes, serial, placed = [], [], {}
    waiting = [t for t in m.order() if t.status == "open"]
    progress = True
    while waiting and progress:
        progress = False
        for t in list(waiting):
            blocks = [m.blocker(b) for b in t.blocked_by]
            if not all(cleared or (x and x.num in placed) for _, cleared, x in blocks):
                continue
            mine = {x.num for _, cleared, x in blocks if x and not cleared}
            clash = lambda group: any(u.num in mine or overlap(u.paths, t.paths) for u in group)
            hit = [lane for lane in lanes if clash(lane)]
            if not t.paths or clash(serial) or len(hit) > 1:
                serial.append(t)
            elif hit:
                hit[0].append(t)
            elif len(lanes) < most:
                lanes.append([t])
            else:
                min(lanes, key=len).append(t)
            placed[t.num] = t
            waiting.remove(t)
            progress = True
    return lanes, serial


def cmd_lanes(args):
    m = load(args[0])
    lanes, serial = plan_lanes(m, int(opt(args, "--max", "2")))
    out = {"lanes": [{"lane": chr(65 + i), "tickets": [t.num for t in lane],
                      "paths": sorted({p for t in lane for p in t.paths})} for i, lane in enumerate(lanes)],
           "serial": [t.num for t in serial],
           "needs_paths": [t.num for t in serial if not t.paths]}
    if "--json" in args:
        print(json.dumps(out))
        return
    for i, lane in enumerate(lanes):
        print(f"lane {chr(65 + i)}: {', '.join(out['lanes'][i]['paths'])}")
        for t in lane:
            print(f"  {t.id} {t.title}")
    if serial:
        print("serial, after every lane:")
        for t in serial:
            print(f"  {t.id} {t.title}" + ("  (needs paths)" if not t.paths else ""))


def next_number(m):
    files = list(WAYFINDER.glob(f"{m.repo}/**/issues/*.md")) + list(WAYFINDER.glob(f"{m.repo}-*/issues/*.md"))
    nums = [int(re.match(r"\d+", f.name).group()) for f in files
            if re.match(r"\d+", f.name)]
    return (max(nums) if nums else 0) + 1


def cmd_next(args):
    print(f"{next_number(load(args[0])):03d}")


def cmd_link(args):
    m = load(args[0])
    print(m.ticket(args[1]).link("#" + m.ticket(args[1]).id))


def cmd_show(args):
    m = load(args[0])
    t = m.ticket(args[1])
    print(f"#{t.num}: {t.title}")
    blockers = ", ".join(t.blocked_by) if t.blocked_by else "none"
    claimed = f" | claimed: {t.claimed_by}" if t.claimed_by else ""
    print(f"status: {t.status} | type: {t.type} | priority: {t.props.get('priority', 'C')}{claimed}")
    print(f"blocked by: {blockers}")

    sections = {}
    curr_sec, curr_lines = None, []
    for line in t.body.splitlines():
        if line.startswith("## "):
            if curr_sec:
                sections[curr_sec] = "\n".join(curr_lines).strip()
            curr_sec = line[3:].strip()
            curr_lines = []
        elif curr_sec is not None:
            curr_lines.append(line)
    if curr_sec:
        sections[curr_sec] = "\n".join(curr_lines).strip()

    for sec in ["Question", "Done when", "Answer", "Comments"]:
        if sec in sections and sections[sec]:
            print(f"\n## {sec}\n{sections[sec]}")


def cmd_check(args):
    m = load(args[0])
    problems = []
    if not m.has_fm:
        problems.append("map.md: legacy header lines; run `sbmap migrate`")
    d = m.body.find("## Decisions so far")
    decisions = m.body[d: (m.body.find("\n## ", d + 4) + 1 or len(m.body))] if d >= 0 else ""
    for t in m.order():
        if not t.has_fm:
            problems.append(f"{t.id}: legacy header lines; run `sbmap migrate`")
        for b in t.blocked_by:
            label, _, bt = m.blocker(b)
            if bt is None and not label.startswith("map: "):
                problems.append(f"{t.id}: blocker '{b}' names no ticket or map")
            elif bt is not None and bt.status == "out-of-scope" and t.status == "open":
                problems.append(f"{t.id}: blocked by out-of-scope {bt.id}; drop the edge or rule {t.id} out too")
            elif t.has_fm and link_target(str(b)) is None:
                problems.append(f"{t.id}: blocker '{b}' is not a wikilink; `sbmap block` writes them")
        if t.status == "resolved" and not t.has_answer:
            problems.append(f"{t.id}: resolved with no '## Answer'")
        if t.status == "resolved" and t.path.stem not in decisions and md_target(t.path.stem) not in decisions:
            problems.append(f"{t.id}: resolved but missing from the map's Decisions so far")
        if t.status not in STATUSES:
            problems.append(f"{t.id}: unknown status '{t.status}'")
        if t.type not in SHAPES:
            problems.append(f"{t.id}: unknown type '{t.type}'")
    # cycles, within the map
    graph = {}
    for t in m.tickets.values():
        graph[t.num] = [x.num for x in (m.resolve_ref(b) for b in t.blocked_by)
                        if isinstance(x, Ticket) and x.num in m.tickets]
    seen, stack = set(), set()

    def visit(n, path):
        if n in stack:
            problems.append("cycle: " + " -> ".join(f"{x:03d}" for x in path + [n]))
            return
        if n in seen:
            return
        seen.add(n); stack.add(n)
        for b in graph.get(n, []):
            visit(b, path + [n])
        stack.discard(n)
    for n in graph:
        visit(n, [])
    # broken links, from Obsidian's own link index
    unresolved = obsidian("unresolved", "verbose", "format=tsv")
    folder = rel(m.folder) + "/"
    if unresolved is None:
        print("(Obsidian not reachable: broken links not checked)")
    else:
        for line in unresolved.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                for s in sources(parts[2]):
                    if not s.startswith(folder):
                        continue
                    # Obsidian lists links to folders as unresolved; a folder that exists is fine
                    if ((VAULT / s).parent / parts[0]).exists():
                        continue
                    problems.append(f"{s[len(folder):]}: broken link to '{parts[0]}'")
    for p in problems:
        print(p)
    print(f"{len(problems)} problem(s) in {m.folder.name}")
    sys.exit(1 if problems else 0)


VERIFY_JS = """(async () => {
  const blocks = %s;
  const m = window.mermaid;
  if (!m) return JSON.stringify({unavailable: true});
  const out = [];
  for (const b of blocks) {
    try { await m.parse(b); out.push("ok"); }
    catch (e) { out.push(String((e && e.message) || e).split("\\n").slice(0, 3).join(" ")); }
  }
  return JSON.stringify(out);
})()"""


def cmd_verify(args):
    m = load(args[0])
    blocks = []
    for f in [m.md_path] + [t.path for t in m.order()]:
        text = f.read_text(encoding="utf-8")
        for i, b in enumerate(re.findall(r"```mermaid\n(.*?)```", text, re.S)):
            blocks.append((f"{rel(f)[len(rel(m.folder)) + 1:]} #{i + 1}", b))
    if not blocks:
        print("no mermaid blocks")
        return
    out = obsidian("eval", "code=" + VERIFY_JS % json.dumps([b for _, b in blocks]), timeout=30)
    if out is None:
        sys.exit("sbmap: Obsidian not reachable; mermaid unverified")
    result = json.loads(out.removeprefix("=> "))
    if isinstance(result, dict):
        sys.exit("sbmap: Obsidian has not loaded mermaid yet; open any note with a mermaid block once, then re-run")
    bad = 0
    for (where, _), r in zip(blocks, result):
        if r != "ok":
            bad += 1
            print(f"{where}: {r}")
    print(f"{len(blocks) - bad}/{len(blocks)} mermaid blocks parse in Obsidian")
    sys.exit(1 if bad else 0)


# ---- write commands -------------------------------------------------------

def blocked_links(m, refs):
    out = []
    for ref in refs:
        x = m.resolve_ref(ref)
        if x is None:
            sys.exit(f"sbmap: '{ref}' names no ticket or map")
        out.append(x.link())
    return out


def operon_priority(value):
    v = str(value or "normal").strip()
    if v.upper() in OPERON_PRIORITIES:
        return v.upper()
    if v.lower() in PRIORITY_WORDS:
        return PRIORITY_WORDS[v.lower()]
    sys.exit(f"sbmap: priority must be one of {', '.join(OPERON_PRIORITIES)} or {', '.join(PRIORITY_WORDS)}")


def make_operon_id(effort_slug, num):
    """Operon requires operonId to be exactly 7 lowercase alphanumeric characters [a-z0-9]{7}."""
    return hashlib.sha256(f"{effort_slug}-{num}".encode("utf-8")).hexdigest()[:7]


def ticket_props(m, t_num, status="open", type_="task", priority="C", created=None, completed=None, blocked=(), extra=None):
    operon_id = make_operon_id(m.effort_slug, t_num)
    aliases = [f"#{t_num:03d}", f"{t_num:03d}"]
    created_date = created or date.today().isoformat()
    wf_status = OPERON_TO_WF_STATUS.get(status.lower(), status.lower())
    op_status = WF_TO_OPERON_STATUS.get(wf_status, status)
    tags = [
        "wayfinder/ticket",
        f"wayfinder/map/{m.effort_slug}",
        f"project/{m.repo}",
        f"status/{wf_status}",
        f"type/{type_}"
    ]
    props = {
        "wayfinder": "ticket",
        "operonId": operon_id,
        "number": t_num,
        "project": m.repo,
        "aliases": aliases,
        "status": op_status,
        "type": type_,
        "priority": operon_priority(priority),
        "created": created_date,
        "map": m.link(),
        "blocked_by": list(blocked),
        "tags": tags
    }
    if completed:
        props["completed"] = completed
    props.update(extra or {})
    return props


def cmd_init(args):
    folder_str = args[0]
    folder = WAYFINDER / folder_str if not Path(folder_str).is_absolute() else Path(folder_str)
    if (folder / "map.md").exists():
        sys.exit(f"sbmap: {folder / 'map.md'} already exists")
    title = opt(args, "--title") or sys.exit("sbmap: --title is required")
    destination = opt(args, "--destination") or sys.exit("sbmap: --destination is required")
    done_when = opt(args, "--done-when", "")
    repo_arg = opt(args, "--repo")

    if not repo_arg:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if r.returncode == 0:
            repo_arg = r.stdout.strip()
        else:
            repo_arg = str(Path.cwd())

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "issues").mkdir(exist_ok=True)

    try:
        rel_folder = folder.resolve().relative_to(WAYFINDER.resolve())
    except ValueError:
        rel_folder = Path(folder.name)
    parts = rel_folder.parts
    slug = "-".join(parts) if len(parts) > 1 else folder.name
    project = parts[0] if len(parts) > 1 else folder.name.split("-", 1)[0]

    props = {
        "wayfinder": "map",
        "project": project,
        "status": "Project.Planned",
        "repo": repo_arg,
        "tags": [f"wayfinder/map/{slug}", f"project/{project}"]
    }

    dest_body = destination.replace("\\n", "\n").strip()
    dw_body = done_when.replace("\\n", "\n").strip()
    dw_section = f"\n\n### Done when\n\n{dw_body}\n" if dw_body else "\n"

    body = (
        f"# {title}\n\n"
        f"## Destination\n\n"
        f"{dest_body}"
        f"{dw_section}\n"
        f"## Route\n\n"
        f"%% sb:diagram:start %%\n"
        f"```mermaid\nflowchart TD\n```\n"
        f"%% sb:diagram:end %%\n\n"
        f"## Notes\n\n"
        f"- Repo: `{repo_arg}`\n\n"
        f"## Decisions so far\n\n"
        f"## Not yet specified\n\n"
        f"## Out of scope\n"
    )

    map_file = folder / "map.md"
    write_atomic(map_file, dump_fm(props, MAP_KEYS) + body)
    m = Map(folder)
    write_board(m)
    cmd_diagram([folder_str, "--write"])
    print(f"initialized map: {map_file}")


def file_title(title):
    """The title as a file name: Operon shows the file name, so it is the title, less the
    characters Obsidian refuses in a name or a link."""
    name = " ".join(re.sub(r'[\\/:*?"<>|#^\[\]]', " ", title).split())
    return name if len(name) <= 100 else name[:100].rsplit(" ", 1)[0]


def cmd_new(args):
    m = load(args[0])
    title = opt(args, "--title") or sys.exit("sbmap: --title is required")
    type_ = opt(args, "--type", "task")
    priority = operon_priority(opt(args, "--priority", "normal"))
    if type_ not in SHAPES:
        sys.exit(f"sbmap: type must be one of {', '.join(SHAPES)}")
    refs = [r for r in (opt(args, "--blocked-by", "") or "").split(",") if r.strip()]
    question = opt(args, "--question", "")
    done_when = opt(args, "--done-when", "")
    comments = opt(args, "--comments", "") or opt(args, "--ruling", "")
    n = next_number(m)
    path = m.folder / "issues" / f"{n:03d} {file_title(title)}.md"
    path.parent.mkdir(exist_ok=True)
    props = ticket_props(m, n, status="open", type_=type_, priority=priority, blocked=blocked_links(m, refs),
                         extra={"title": title})
    if opt(args, "--paths"):
        props["paths"] = split_list(opt(args, "--paths"))

    q_text = question.replace("\\n", "\n").strip() if question else ""
    dw_text = done_when.replace("\\n", "\n").strip() if done_when else ""
    body = f"## Question\n\n{q_text}\n\n## Done when\n\n{dw_text}\n\n## Comments\n"
    if comments:
        c_text = comments.replace("\\n", "\n").strip()
        body += f"\n- **{date.today().isoformat()}**: {c_text}\n"

    write_atomic(path, dump_fm(props, TICKET_KEYS) + body)
    print(path)
    if "--no-sync" not in args:
        cmd_diagram([args[0], "--write"])


def cmd_comment(args):
    m = load(args[0])
    t = m.ticket(args[1])
    text = opt(args, "--text") or opt(args, "--ruling") or sys.exit("sbmap: --text or --ruling is required")
    c_text = text.replace("\\n", "\n").strip()
    body = t.body
    today = date.today().isoformat()
    entry = f"- **{today}**: {c_text}"
    idx = body.find("## Comments")
    if idx >= 0:
        nxt = body.find("\n## ", idx + 11)
        if nxt < 0:
            body = body.rstrip() + f"\n\n{entry}\n"
        else:
            body = body[:nxt].rstrip() + f"\n\n{entry}\n\n" + body[nxt:].lstrip()
    else:
        body = body.rstrip() + f"\n\n## Comments\n\n{entry}\n"
    t.save(t.props, body)
    print(f"added comment to {t.id}")


def cmd_set(args):
    no_sync = "--no-sync" in args
    kv_args = [a for a in args[2:] if a != "--no-sync"]
    m = load(args[0])
    t = m.ticket(args[1])
    props = dict(t.props) if t.has_fm else None
    if props is None:
        sys.exit("sbmap: legacy ticket; run `sbmap migrate` first")
    for kv in kv_args:
        k, _, v = kv.partition("=")
        if k == "status":
            wf_stat = OPERON_TO_WF_STATUS.get(v.lower(), v.lower())
            if wf_stat not in STATUSES:
                sys.exit(f"sbmap: status must be one of {', '.join(STATUSES)}")
            v = WF_TO_OPERON_STATUS.get(wf_stat, v)
            tags = [tag for tag in props.get("tags", []) if not tag.startswith("status/")]
            tags.append(f"status/{wf_stat}")
            props["tags"] = sorted(tags)
            if wf_stat == "resolved" and "completed" not in props:
                props["completed"] = date.today().isoformat()
        if k == "blocked_by":
            sys.exit("sbmap: use `sbmap block` for blockers")
        if k == "priority":
            v = operon_priority(v)
        if k == "paths":
            v = split_list(v)
        props[k] = v
    curr_wf = OPERON_TO_WF_STATUS.get(str(props.get("status", "")).lower(), str(props.get("status", "")).lower())
    if curr_wf != "claimed":
        props.pop("claimed_by", None)
    t.save(props)
    print(f"{t.id}: " + ", ".join(kv_args))
    if not no_sync:
        cmd_diagram([args[0], "--write"])


def cmd_claim(args):
    by = opt(args, "--by") or sys.exit("sbmap: --by is required")
    m = load(args[0])
    t = m.ticket(args[1])
    if t.status == "claimed":
        sys.exit(f"sbmap: {t.id} is already claimed by {t.claimed_by or 'someone'}")
    stamp = date.today().isoformat() + " " + time.strftime("%H:%M")
    no_sync = ["--no-sync"] if "--no-sync" in args else []
    cmd_set([args[0], args[1], "status=claimed", f"claimed_by={by}, {stamp}"] + no_sync)


def cmd_block(args):
    m = load(args[0])
    t = m.ticket(args[1])
    refs = [] if args[2] == "none" else [r for r in args[2].split(",") if r.strip()]
    props = dict(t.props)
    props["blocked_by"] = blocked_links(m, refs)
    t.save(props)
    print(f"{t.id} blocked by: {', '.join(props['blocked_by']) or 'nothing'}")
    if "--no-sync" not in args:
        cmd_diagram([args[0], "--write"])


def cmd_resolve(args):
    m = load(args[0])
    t = m.ticket(args[1])
    gist = opt(args, "--gist") or sys.exit("sbmap: --gist is required")
    commit = opt(args, "--commit")
    answer = opt(args, "--answer")
    if answer:
        ans_text = answer.replace("\\n", "\n").strip()
        body = t.body
        if "## Answer" in body:
            idx = body.find("## Answer")
            nxt = body.find("\n## ", idx + 9)
            if nxt < 0:
                body = body[:idx].rstrip() + f"\n\n## Answer\n\n{ans_text}\n"
            else:
                body = body[:idx].rstrip() + f"\n\n## Answer\n\n{ans_text}\n\n" + body[nxt:].lstrip()
        else:
            idx = body.find("## Comments")
            if idx >= 0:
                body = body[:idx].rstrip() + f"\n\n## Answer\n\n{ans_text}\n\n" + body[idx:]
            else:
                body = body.rstrip() + f"\n\n## Answer\n\n{ans_text}\n"
        t.save(t.props, body)
        t = m.ticket(args[1])

    if not re.search(r"^## Answer\b", t.text, re.M):
        sys.exit(f"sbmap: {t.id} has no '## Answer' yet; provide --answer or write it first")

    cmd_set([args[0], args[1], "status=resolved", "--no-sync"])
    line = f"- [{t.title}](issues/{md_target(t.path.name)}): {gist}" + (f", `{commit}`" if commit else "")
    m = load(args[0])
    body = m.body
    i = body.find("## Decisions so far")
    if i < 0:
        body = body.rstrip() + "\n\n## Decisions so far\n\n" + line + "\n"
    else:
        nxt = body.find("\n## ", i + 4)
        nxt = len(body) if nxt < 0 else nxt
        body = body[:nxt].rstrip() + "\n" + line + "\n" + body[nxt:]
    m.save(m.props if m.has_fm else migrate_map_props(m), body)
    print(f"resolved {t.id}; Decisions line added")
    if "--no-sync" not in args:
        cmd_diagram([args[0], "--write"])


# ---- the Route (mermaid) --------------------------------------------------

def label(text, limit=46):
    text = re.sub(r"[*_`]", "", text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text.replace('"', "#quot;")


def diagram(m, hide_resolved=False):
    frontier = {t.num for t in m.frontier()}
    lines = ["```mermaid", '%%{init: {"flowchart": {"useMaxWidth": true}}}%%', "flowchart TD"]
    classes = {"done": [], "claimed": [], "frontier": [], "blocked": [], "out": [], "ext": []}
    shown = {t.num for t in m.tickets.values() if not (hide_resolved and t.status in CLEARED)}
    externals = {}
    edges = []
    for t in m.order():
        if t.num not in shown:
            continue
        a, b = SHAPES.get(t.type, SHAPES["task"])
        # Obsidian makes an internal-link node a link to the note its label names
        lines.append(f'    t{t.id}{a}{t.path.stem}{b}')
        cls = ("done" if t.status == "resolved" else "out" if t.status == "out-of-scope"
               else "claimed" if t.status == "claimed" else "frontier" if t.num in frontier else "blocked")
        classes[cls].append(f"t{t.id}")
        for ref in t.blocked_by:
            text, cleared, bt = m.blocker(ref)
            if bt is not None and bt.num in m.tickets and bt.path.parent == t.path.parent:
                if bt.num in shown:
                    edges.append(f"    t{bt.id} --> t{t.id}")
                continue
            key = "x" + format(zlib.crc32(text.encode()), "08x")
            if key not in externals:
                externals[key] = text
                lines.append(f'    {key}(["{label(text)}"])')
                classes["done" if cleared else "ext"].append(key)
            edges.append(f"    {key} -.-> t{t.id}")
    lines += edges
    lines += [
        "    classDef done fill:#d3f9d8,stroke:#2b8a3e,color:#2b8a3e",
        "    classDef claimed fill:#fff3bf,stroke:#e67700,color:#7a4100",
        "    classDef frontier fill:#d0ebff,stroke:#1864ab,stroke-width:3px,color:#0b3d6e",
        "    classDef blocked fill:#f1f3f5,stroke:#868e96,color:#495057",
        "    classDef out fill:#f8f9fa,stroke:#adb5bd,stroke-dasharray:4 3,color:#adb5bd",
        "    classDef ext fill:#fff,stroke:#868e96,stroke-dasharray:4 3,color:#495057",
    ]
    for cls, ids in classes.items():
        if ids:
            lines.append(f"    class {','.join(ids)} {cls}")
    tickets = [f"t{t.id}" for t in m.order() if t.num in shown]
    if tickets:
        lines.append(f"    class {','.join(tickets)} internal-link")
    lines.append("```")
    legend = ("Blue, thick border: the frontier. Amber: claimed. Green: resolved. Grey: blocked. "
              "Dashed: out of scope or another map. Shape is the type: box task, rounded grilling, "
              "slanted research, double box prototype, hexagon architecture. Click a ticket to open it.")
    if hide_resolved:
        legend += " Resolved tickets hidden."
    return "\n".join([START, "", "\n".join(lines), "",
                      f"*{legend} Generated by sbmap; edit the tickets, not this block.*", END])


def insert_section(body, heading, content, before=("## Notes", "## Decisions so far")):
    """Put `## heading` + content before the first of `before`, or at the end."""
    section = f"## {heading}\n\n{content}\n\n"
    for b in before:
        i = body.find("\n" + b)
        if i >= 0:
            return body[: i + 1] + section + body[i + 1:]
    return body.rstrip() + "\n\n" + section


def cmd_diagram(args):
    m = load(args[0])
    block = diagram(m, hide_resolved="--hide-resolved" in args)
    if "--write" not in args:
        print(block)
        return
    m = load(args[0])  # re-read: a peer may have written since
    body = m.body.replace(OLD_MARKERS[0], START).replace(OLD_MARKERS[1], END)
    if START in body and END in body:
        body = body[: body.index(START)] + block + body[body.index(END) + len(END):]
    else:
        body = insert_section(body, "Route", block)
    if m.has_fm:
        m.save(m.props, body)
    else:
        write_atomic(m.md_path, body)
    print(f"wrote the route diagram into {m.md_path}")


# ---- the board (Bases) ----------------------------------------------------

BOARD = """filters:
  and:
    - file.inFolder("{issues}")
    - wayfinder == "ticket"
formulas:
  open_blockers: if(blocked_by, blocked_by.filter(!{finished}.contains(value.asFile().properties.status)).length, 0)
  ready: status == "Project.Planned" && formula.open_blockers == 0
properties:
  file.name:
    displayName: Ticket
  formula.open_blockers:
    displayName: Open blockers
  blocked_by:
    displayName: Blocked by
  claimed_by:
    displayName: Claimed by
views:
  - type: table
    name: Frontier
    filters:
      and:
        - formula.ready
    order:
      - file.name
      - type
      - blocked_by
    sort:
      - property: file.name
        direction: ASC
  - type: table
    name: All tickets
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - type
      - blocked_by
      - formula.open_blockers
      - claimed_by
    sort:
      - property: file.name
        direction: ASC
  - type: cards
    name: Board
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - type
      - formula.open_blockers
"""

ALL_FRONTIERS = """filters:
  and:
    - file.inFolder("wayfinder")
    - wayfinder == "ticket"
formulas:
  open_blockers: if(blocked_by, blocked_by.filter(!{finished}.contains(value.asFile().properties.status)).length, 0)
  ready: status == "Project.Planned" && formula.open_blockers == 0
properties:
  file.name:
    displayName: Ticket
  formula.open_blockers:
    displayName: Open blockers
views:
  - type: table
    name: Every frontier
    filters:
      and:
        - formula.ready
    groupBy:
      property: map
      direction: ASC
    order:
      - file.name
      - type
    sort:
      - property: file.name
        direction: ASC
  - type: table
    name: Claimed now
    filters:
      and:
        - status == "Project.InProgress"
    order:
      - file.name
      - map
      - claimed_by
  - type: table
    name: Frontier by project
    filters:
      and:
        - formula.ready
    groupBy:
      property: project
      direction: ASC
    order:
      - file.name
      - map
      - type
      - priority
"""

REPO_BOARD = """filters:
  and:
    - file.inFolder("{repo}")
    - wayfinder == "ticket"
formulas:
  open_blockers: if(blocked_by, blocked_by.filter(!{finished}.contains(value.asFile().properties.status)).length, 0)
  ready: status == "Project.Planned" && formula.open_blockers == 0
properties:
  file.name:
    displayName: Ticket
  formula.open_blockers:
    displayName: Open blockers
  claimed_by:
    displayName: Claimed by
views:
  - type: table
    name: Frontier
    filters:
      and:
        - formula.ready
    groupBy:
      property: map
      direction: ASC
    order:
      - file.name
      - type
      - priority
    sort:
      - property: file.name
        direction: ASC
  - type: table
    name: In progress
    filters:
      and:
        - status == "Project.InProgress"
    order:
      - file.name
      - map
      - claimed_by
  - type: cards
    name: Board
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - map
      - type
      - formula.open_blockers
"""


def write_board(m):
    write_atomic(m.folder / "board.base", BOARD.replace("{finished}", FINISHED).format(issues=rel(m.folder / "issues")))
    write_atomic(WAYFINDER / "frontier.base", ALL_FRONTIERS.replace("{finished}", FINISHED))
    repo_board = ""
    if len(m.rel_folder.parts) > 1:
        path = WAYFINDER / m.repo / "board.base"
        write_atomic(path, REPO_BOARD.replace("{finished}", FINISHED).replace("{repo}", rel(WAYFINDER / m.repo)))
        repo_board = f"This repo's maps: [[{rel(path)}]]. "
    embed = f"![[{rel(m.folder / 'board.base')}#Frontier]]"
    every = "Every map's frontier at once: [[wayfinder/frontier.base]]."
    m = Map(m.folder)
    if embed not in m.body:
        body = insert_section(m.body, "Board", embed + "\n\nThe live board (Bases): views *Frontier*, *All tickets*, *Board*. "
                              + repo_board + every)
        m.save(m.props if m.has_fm else migrate_map_props(m), body)
    elif repo_board and repo_board not in m.body and every in m.body:
        m.save(m.props if m.has_fm else migrate_map_props(m), m.body.replace(every, repo_board + every, 1))


def cmd_board(args):
    m = load(args[0])
    write_board(m)
    print(f"wrote {m.folder / 'board.base'}, wayfinder/{m.repo}/board.base and wayfinder/frontier.base")


# ---- migration ------------------------------------------------------------

CODE = re.compile(r"```.*?```|`[^`\n]*`|\[\[[^\]]*\]\]|\[[^\]]*\]\([^)]*\)|<[^>\n]*>|https?://\S+", re.S)


def number_index(repo):
    """number -> every ticket of this repo's maps carrying it."""
    idx = {}
    files = list(WAYFINDER.glob(f"{repo}/**/issues/*.md")) + list(WAYFINDER.glob(f"{repo}-*/issues/*.md"))
    for f in files:
        mm = re.match(r"(\d+)-", f.name)
        if mm:
            idx.setdefault(int(mm.group(1)), []).append(f)
    return idx


def github_maps():
    """GitHub issue number -> map, for maps moved from GitHub."""
    out = {}
    for m in all_maps():
        g = re.search(r"/issues/(\d+)", m.github or m.body.split("\n## ", 1)[0])
        if g:
            out[int(g.group(1))] = m
    return out


def link_numbers(text, repo, here=None, self_path=None):
    """`#NNN` and `ticket NNN` that name exactly one ticket (this map's first) -> wikilinks."""
    idx, maps = number_index(repo), github_maps()

    def target(n):
        if n in maps and maps[n].repo == repo:
            return maps[n].md_path if maps[n].md_path != self_path else None
        hits = idx.get(n, [])
        local = [h for h in hits if here is not None and h.parent.parent == here]
        pick = local or hits
        if len(pick) == 1 and pick[0] != self_path:
            return pick[0]
        return None

    def sub_hash(mm):
        p = target(int(mm.group(2)))
        return mm.group(1) + (wikilink(p, "#" + mm.group(2)) if p else "#" + mm.group(2))

    def sub_word(mm):
        p = target(int(mm.group(2)))
        return mm.group(1) + (wikilink(p, mm.group(2)) if p else mm.group(2))

    out, last = [], 0
    for c in CODE.finditer(text):
        seg = text[last:c.start()]
        seg = re.sub(r"(^|[^\w/&#\[])#(\d{2,4})\b", sub_hash, seg)
        seg = re.sub(r"(\b(?:[Tt]ickets?|[Ii]ssues?) )(\d{3})\b(?![-–]\d)", sub_word, seg)
        out.append(seg)
        out.append(c.group(0))
        last = c.end()
    seg = text[last:]
    seg = re.sub(r"(^|[^\w/&#\[])#(\d{2,4})\b", sub_hash, seg)
    seg = re.sub(r"(\b(?:[Tt]ickets?|[Ii]ssues?) )(\d{3})\b(?![-–]\d)", sub_word, seg)
    out.append(seg)
    return "".join(out)


def guess_repo(m):
    """The checkout a map works on: a path it names, else a repo folder named in it or by its prefix."""
    code = Path(os.environ.get("SB_CODE", Path.home() / "Documents" / "Coding"))
    if not code.is_dir():
        return ""
    found = re.search(rf"{re.escape(str(code))}/([\w.-]+)", m.md)
    names = [found.group(1)] if found else []
    names += sorted((d.name for d in code.iterdir() if d.is_dir() and (d / ".git").exists()
                     and re.search(rf"(?<![\w-]){re.escape(d.name)}(?![\w-])", m.md)), key=len, reverse=True)
    for name in names + [m.repo]:
        if (code / name).is_dir():
            return str(code / name)
    return ""


def migrate_map_props(m):
    f = legacy_fields(m.body)
    props = {"wayfinder": "map", "project": m.repo, "status": f.get("status", "open").lower(), "aliases": [m.title],
             "repo": guess_repo(m), "tags": ["wayfinder/map", f"project/{m.repo}"]}
    gh = f.get("github") or (re.search(r"^GitHub:\s*(\S+)", m.body, re.M) or [None, ""])[1]
    if gh:
        props["github"] = gh
    return props


def migrate_map(m, write):
    changes = []
    tickets = []
    for t in m.order():
        props = dict(t.props) if t.has_fm else {}
        needed = False
        if not t.has_fm:
            f = legacy_fields(t.body)
            raw = [b.strip() for b in f.get("blocked_by", "").split(",") if b.strip()]
            links = []
            for r in raw:
                x = m.resolve_ref(r)
                links.append(x.link() if x is not None else r)
            extra = {k: f[k] for k in ("claimed_by", "github") if f.get(k)}
            props = ticket_props(m, t.num, f.get("status", "open").lower(), f.get("type", "task").lower(),
                                 blocked=links, extra=extra)
            changes.append(f"{t.id}: properties from header lines ({len(links)} blocker link(s))")
            needed = True
        else:
            if "operonId" not in props or not re.fullmatch(r"[a-z0-9]{7}", str(props.get("operonId", ""))):
                props["operonId"] = make_operon_id(m.effort_slug, t.num)
                needed = True
            if "aliases" not in props:
                props["aliases"] = [f"#{t.num:03d}", f"{t.num:03d}"]
                needed = True
            done = []
            if props.get("project") != m.repo:
                props["project"] = m.repo
                done.append(f"project {m.repo}")
            pr = str(props.get("priority", ""))
            letter = operon_priority(pr) if pr.upper() in OPERON_PRIORITIES or pr.lower() in PRIORITY_WORDS else "C"
            if pr != letter:
                props["priority"] = letter
                done.append(f"priority {pr or 'none'} -> {letter}")
            if "created" not in props:
                mtime = t.path.stat().st_mtime
                props["created"] = date.fromtimestamp(mtime).isoformat()
                needed = True
            if t.status == "resolved" and "completed" not in props:
                mtime = t.path.stat().st_mtime
                props["completed"] = date.fromtimestamp(mtime).isoformat()
                needed = True
            curr_map_link = m.link()
            if props.get("map") != curr_map_link:
                props["map"] = curr_map_link
                needed = True
            tags = set(props.get("tags") or ["wayfinder/ticket"])
            tags.add("wayfinder/ticket")
            tags.add(f"wayfinder/map/{m.effort_slug}")
            tags.add(f"project/{m.repo}")
            tags.add(f"status/{t.status}")
            tags.add(f"type/{t.type}")
            new_tags = sorted(tags)
            if new_tags != props.get("tags"):
                props["tags"] = new_tags
                needed = True
            if done:
                changes.append(f"{t.id}: " + ", ".join(done))
                needed = True
            elif needed:
                changes.append(f"{t.id}: backfilled operonId, aliases, created, map or tags")

        body = strip_legacy(t.body) if not t.has_fm else t.body
        linked = link_numbers(body, m.repo, m.folder, t.path)
        n = len(re.findall(r"\[\[", linked)) - len(re.findall(r"\[\[", body))
        if n:
            changes.append(f"{t.id}: {n} number reference(s) -> wikilinks")
        if write and (needed or not t.has_fm or linked != t.body):
            tickets.append((t, props, linked))
    mprops = dict(m.props) if m.has_fm else migrate_map_props(m)
    if m.has_fm and not mprops.get("aliases"):
        mprops["aliases"] = [m.title]
        changes.append("map.md: aliases (its title, for link autocomplete)")
    if mprops.get("project") != m.repo or f"project/{m.repo}" not in (mprops.get("tags") or []):
        mprops["project"] = m.repo
        mprops["tags"] = sorted(set(mprops.get("tags") or []) | {f"project/{m.repo}"})
        changes.append(f"map.md: project {m.repo}")
    if not m.has_fm:
        changes.append(f"map.md: properties (status {mprops['status']}, repo {mprops['repo'] or '?'})")
    mbody = strip_legacy(m.body) if not m.has_fm else m.body
    mlinked = link_numbers(mbody, m.repo, m.folder, m.md_path)
    n = len(re.findall(r"\[\[", mlinked)) - len(re.findall(r"\[\[", mbody))
    if n:
        changes.append(f"map.md: {n} number reference(s) -> wikilinks")
    if write:
        for t, props, body in tickets:
            t.save(props, body)
        if not m.has_fm or mlinked != m.body or mprops != m.props:
            m.save(mprops, mlinked)
        write_board(Map(m.folder))
        changes.append("board.base written and embedded")
    return changes


def migrate_root_docs(repo, write):
    """Handoffs and checkpoints beside the maps: numbers that name one ticket become links."""
    changes = []
    candidates = list(WAYFINDER.glob(f"{repo}-*.md"))
    if (WAYFINDER / repo).is_dir():
        candidates += list((WAYFINDER / repo).glob("*.md"))
    for p in sorted(set(candidates)):
        text = p.read_text(encoding="utf-8")
        linked = link_numbers(text, repo)
        n = len(re.findall(r"\[\[", linked)) - len(re.findall(r"\[\[", text))
        if n:
            changes.append(f"{p.name}: {n} number reference(s) -> wikilinks")
            if write:
                write_atomic(p, linked)
    return changes


def cmd_migrate(args):
    write = "--write" in args
    maps = all_maps() if args[0] == "--all" else [load(args[0])]
    repos = []
    for m in maps:
        print(f"## {m.folder.name}")
        for c in migrate_map(m, write):
            print("  " + c)
        if m.repo not in repos:
            repos.append(m.repo)
    for r in repos:
        for c in migrate_root_docs(r, write):
            print("  " + c)
    print("written" if write else "dry run: nothing written (add --write)")


REPORT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "map-report.md"


def drop_section(body, heading):
    i = body.find(f"\n## {heading}\n")
    if i < 0:
        return body
    nxt = body.find("\n## ", i + 4)
    return body[:i + 1] + (body[nxt + 1:] if nxt >= 0 else "")


def wiki_module():
    """The wiki's tools: the wikibrain skill (github.com/DanAmador/wikiBrain), pinned in skills-lock.json
    and installed beside this skill by install.sh; WIKIBRAIN_DIR overrides where its scripts are."""
    for d in (os.environ.get("WIKIBRAIN_DIR"), Path.home() / ".agents/skills/wikibrain/scripts",
              Path.home() / ".claude/skills/wikibrain/scripts"):
        if d and (Path(d) / "wikibrain.py").exists():
            os.environ.setdefault("SB_VAULT", str(VAULT))
            sys.path.insert(0, str(d))
            import wikibrain
            return wikibrain
    sys.exit("sbmap: the wikibrain skill is missing: run install.sh (it is pinned in skills-lock.json)")


def cmd_close(args):
    sbwiki = wiki_module()
    m = load(args[0])
    report = m.folder / "report.md"
    if report.exists():
        sys.exit(f"sbmap: {rel(report)} already exists; edit it, never rewrite it")
    waiting = [t for t in m.order() if t.status in ("open", "claimed")]
    if waiting:
        for t in waiting:
            print(f"  {t.id} {t.title}  [{t.status}{': ' + t.claimed_by if t.claimed_by else ''}]")
        sys.exit(f"sbmap: {len(waiting)} ticket(s) still open or claimed; resolve them or rule them out of scope")
    here = rel(m.folder) + "/"
    findings = sorted((n for n in sbwiki.articles()
                       if any(sbwiki.entry_key(e).startswith(here) for e in n.refs("sources"))),
                      key=lambda n: n.title.lower())
    _, body, _ = split_fm(REPORT_TEMPLATE.read_text(encoding="utf-8"))
    body = body.replace("<the map's title>", m.title)
    if findings:
        placeholder = next(line for line in body.splitlines() if line.startswith("- [ ] <One sentence.>"))
        body = body.replace(placeholder, "\n".join(f"- [ ] <One sentence.> {n.link()}" for n in findings))
    else:
        body = drop_section(drop_section(body, "Findings"), "Also learned")
    props = {"wayfinder": "report", "type": "report", "map": m.link(), "closed": date.today().isoformat(),
             "findings": [n.link() for n in findings], "tags": ["wayfinder/report"]}
    write_atomic(report, dump_fm(props, list(props)) + body.lstrip("\n"))
    mprops = dict(m.props) if m.has_fm else migrate_map_props(m)
    mprops["status"] = WF_TO_OPERON_STATUS["resolved"]
    m.save(mprops, m.body)
    print(rel(report))
    print(f"{m.title}: resolved; {len(findings)} article(s) in findings")


def cmd_wiki(args):
    wiki_module().main(args)


COMMANDS = {"maps": cmd_maps, "status": cmd_status, "frontier": cmd_frontier, "lanes": cmd_lanes, "show": cmd_show,
            "next": cmd_next, "link": cmd_link, "check": cmd_check, "verify": cmd_verify,
            "init": cmd_init, "new": cmd_new, "set": cmd_set, "claim": cmd_claim,
            "comment": cmd_comment, "ruling": cmd_comment, "block": cmd_block,
            "resolve": cmd_resolve, "diagram": cmd_diagram, "board": cmd_board, "migrate": cmd_migrate,
            "close": cmd_close, "wiki": cmd_wiki}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS or (sys.argv[1] not in ("maps", "wiki") and len(sys.argv) < 3):
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]](sys.argv[2:])
