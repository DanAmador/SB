"""sbmap wiki: the vault's compiled knowledge, `reference/wiki.md` made executable.

  read
    sbmap.py wiki index [--write]           every topic and article, one line each; --write restamps index.md
    sbmap.py wiki find <terms…> [--raw] [--limit N]
                                            notes matching any term, scored: title/aliases 3, summary 2, body 1
    sbmap.py wiki show <note> [--full]      digest: properties, Overview, headings, Outdated/Disputed callouts
    sbmap.py wiki link <note>               the wikilink to paste into prose
    sbmap.py wiki backlog [--limit N]       raw notes no article cites and the log has not marked no-material
  write
    sbmap.py wiki init                      creates whatever of the layout is missing; never overwrites
    sbmap.py wiki raw <topic> --title "…" --source "…" [--author "…"] [--published YYYY-MM-DD|Unknown]
                          --from <file|->   keeps a source as a raw note
    sbmap.py wiki new <topic>/<slug> --title "…" --type concept|entity|synthesis --summary "…"
                          --sources <refs> [--related <refs>] [--aliases "a, b"] [--about "…"]
    sbmap.py wiki set <note> key=value … [key+=<refs>] [key-=<refs>]
    sbmap.py wiki log <learn|ask|tend> --subject "…" [--disposition "…"] [--raw <refs>] [--updated <refs>]
    sbmap.py wiki check [--fix]             lint; exits non-zero on any format or link problem

<note> is a vault path, `<topic>/<slug>` or a wikilink. <refs> are comma-separated vault paths,
wikilinks, or `<map>#<NNN>` for a ticket; each is written as a full-path wikilink.
"""
import re
import sys
from datetime import date
from pathlib import Path

import sbmap as sb

WIKI_KEYS = ["wiki", "type", "status", "title", "source", "author", "published", "created", "summary",
             "updated", "reviewed", "archived", "sources", "related", "supersedes", "superseded_by",
             "disputes", "aliases", "tags"]
KINDS = {"article", "synthesis", "raw", "topic", "index", "log"}
TYPES = {"article": {"concept", "entity"}, "synthesis": {"synthesis"}, "raw": {"source"},
         "topic": {"topic"}}
STATUSES = ("current", "outdated", "disputed")
REF_KEYS = ("sources", "related", "supersedes", "superseded_by", "disputes")
RECIPROCAL = {"disputes": "disputes", "supersedes": "superseded_by", "superseded_by": "supersedes"}
DATE_KEYS = ("updated", "reviewed", "archived", "created", "published")
ROOT_FILES = ("index.md", "log.md", "README.md")
INDEX_START, INDEX_END = "%% sb:index:start %%", "%% sb:index:end %%"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DATED = re.compile(r"\d+-")
DISPUTED = re.compile(r"^> \[!question\] Disputed", re.M)
OUTDATED = re.compile(r"^> \[!warning\] Outdated\b(.*)$", re.M)
LINK = re.compile(r"(!?)\[\[([^\]|#]*)(#[^\]|]*)?(?:\|([^\]]*))?\]\]")


def wiki_dir():
    return sb.VAULT / "wiki"


def today():
    return date.today().isoformat()


def die(msg):
    sys.exit(f"sbmap wiki: {msg}")


# ---- notes ----------------------------------------------------------------

class Note:
    def __init__(self, path):
        self.path = Path(path)
        self.text = self.path.read_text(encoding="utf-8")
        self.props, self.body, self.has_fm = sb.split_fm(self.text)
        self.kind = str(self.props.get("wiki", ""))

    @property
    def title(self):
        m = re.search(r"^# (.+)$", self.body, re.M)
        return m.group(1).strip() if m else str(self.props.get("title") or self.path.stem)

    @property
    def rel(self):
        return sb.rel(self.path)

    def refs(self, key):
        v = self.props.get(key) or []
        return v if isinstance(v, list) else [v]

    def link(self):
        return sb.wikilink(self.path, self.title)

    def save(self, props=None, body=None):
        if props is not None:
            self.props = props
        if body is not None:
            self.body = body
        self.text = sb.dump_fm(self.props, WIKI_KEYS) + self.body.lstrip("\n")
        sb.write_atomic(self.path, self.text)


def target_of(target):
    """The file a link target names (with or without `.md`), or None."""
    target = target.strip().strip("/")
    if not target:
        return None
    p = sb.VAULT / target
    if p.is_file():
        return p
    q = p.with_name(p.name + ".md")
    return q if q.is_file() else None


def link_path(ref):
    """The file a `[[target|alias]]` names, or None."""
    m = LINK.fullmatch(str(ref).strip())
    return target_of(m.group(2)) if m else None


def note_path(arg):
    """A note under wiki/: a vault path, `<topic>/<slug>`, or a wikilink."""
    arg = str(arg).strip()
    p = link_path(arg) if arg.startswith("[[") else None
    if p is None:
        arg = arg.removeprefix(str(sb.VAULT) + "/")
        p = target_of(arg) or target_of("wiki/" + arg)
    if p is None:
        die(f"'{arg}' names no note")
    return p


def resolve_ref(ref):
    """One <ref> -> (path, its full-path wikilink). Exits on a ref that names no note."""
    ref = ref.strip()
    m = re.fullmatch(r"(.+)#(\d+)", ref)
    if m and not ref.startswith("[["):
        t = sb.load(m.group(1)).ticket(m.group(2))
        return t.path, t.link("#" + t.id)
    if ref.startswith("[["):
        p = link_path(ref)
    else:
        ref = ref.removeprefix(str(sb.VAULT) + "/")
        p = target_of(ref) or target_of("wiki/" + ref)
    if p is None:
        die(f"'{ref}' names no note")
    if "/wayfinder/" in "/" + sb.rel(p) and re.match(r"\d+-", p.name) and p.parent.name == "issues":
        t = sb.Ticket(p)
        return p, t.link("#" + t.id)
    return p, Note(p).link()


def split_refs(s):
    return [r.strip() for r in re.findall(r"\[\[.*?\]\]|[^,]+", s or "") if r.strip()]


def wiki_notes():
    """Every note under wiki/ but raw/, index, log and README."""
    w = wiki_dir()
    if not w.is_dir():
        return []
    return [Note(p) for p in sorted(w.rglob("*.md"))
            if p.relative_to(w).parts[0] != "raw" and p.relative_to(w).as_posix() not in ROOT_FILES]


def articles():
    return [n for n in wiki_notes() if n.kind in ("article", "synthesis")]


def slug_taken(slug):
    w = wiki_dir()
    return w.is_dir() and any(p.stem == slug for p in w.rglob("*.md")
                              if p.relative_to(w).as_posix() not in ROOT_FILES)


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    m = re.match(r"((?:\d+-)+)(.+)", s)  # a leading date or number moves to the end
    if m:
        s = m.group(2) + "-" + m.group(1).strip("-")
    return s[:60].rstrip("-")


# ---- raw classes ----------------------------------------------------------

def raw_class(path):
    """'raw', 'clipping', 'research', 'ticket', or None for a note that is not a source."""
    parts = Path(sb.rel(path)).parts
    if parts[:2] == ("wiki", "raw"):
        return "raw"
    if parts[:1] == ("Clippings",):
        return "clipping"
    if parts[:1] == ("wayfinder",) and "research" in parts[:-1]:
        return "research"
    if parts[:1] == ("wayfinder",) and len(parts) > 1 and parts[-2] == "issues" and re.match(r"\d+-", parts[-1]):
        return "ticket"
    return None


def source_problem(kind, path):
    """Why `path` may not be a `sources` entry of a note of `kind`, or None."""
    cls = raw_class(path)
    if cls is None:
        if kind == "synthesis" and Note(path).kind == "article":
            return None
        return f"{sb.rel(path)[:-3]} is not a raw note" + (" or an article" if kind == "synthesis" else "")
    if cls == "ticket" and sb.Ticket(path).status != "resolved":
        return f"{sb.rel(path)[:-3]} is a ticket that is not resolved"
    return None


def ref_links(refs_arg, kind=None, key="sources"):
    out = []
    for ref in split_refs(refs_arg):
        p, link = resolve_ref(ref)
        if key == "sources" and kind:
            why = source_problem(kind, p)
            if why:
                die(why)
        if link not in out:
            out.append(link)
    return out


# ---- the index ------------------------------------------------------------

def topics():
    w = wiki_dir()
    return sorted(d.name for d in w.iterdir() if d.is_dir() and d.name != "raw") if w.is_dir() else []


def esc(s):
    return str(s).replace("|", "\\|")


def topic_rows(topic):
    notes = [n for n in articles() if n.path.parent.name == topic]
    return sorted(notes, key=lambda n: (n.kind == "synthesis", n.title.lower()))


def folder_note(topic):
    p = wiki_dir() / topic / f"{topic}.md"
    return Note(p) if p.exists() else None


def index_block():
    lines = [INDEX_START, ""]
    for t in topics():
        fn = folder_note(t)
        lines.append(f"## {t}")
        lines.append("")
        if fn and fn.props.get("summary"):
            lines += [str(fn.props["summary"]), ""]
        rows = topic_rows(t)
        if rows:
            lines += ["| Article | Type | Summary | Updated |", "|---|---|---|---|"]
            for n in rows:
                when = n.props.get("archived") if n.kind == "synthesis" else n.props.get("updated")
                lines.append(f"| {esc(n.link())} | {n.props.get('type', '')} | "
                             f"{esc(n.props.get('summary', ''))} | {when or ''} |")
            lines.append("")
    lines += ["*Generated by sbmap from the articles' properties; edit the articles, not this block.*",
              INDEX_END]
    return "\n".join(lines)


def stamped_index():
    """index.md's text with a fresh block, or None when there is no index.md."""
    p = wiki_dir() / "index.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    block = index_block()
    if INDEX_START in text and INDEX_END in text:
        return text[:text.index(INDEX_START)] + block + text[text.index(INDEX_END) + len(INDEX_END):]
    return text.rstrip("\n") + "\n\n" + block + "\n"


def write_index():
    text = stamped_index()
    if text is not None:
        sb.write_atomic(wiki_dir() / "index.md", text)


def cmd_index(args):
    if not wiki_dir().is_dir():
        print("no wiki/ yet: `sbmap wiki init`")
        return
    if "--write" in args:
        write_index()
        print(f"wrote the index into {wiki_dir() / 'index.md'}")
        return
    for t in topics():
        fn = folder_note(t)
        print(f"## {t}" + (f": {fn.props.get('summary')}" if fn and fn.props.get("summary") else ""))
        for n in topic_rows(t):
            status = n.props.get("status") or n.kind
            print(f"  {n.rel[:-3]} · {n.props.get('type', '')} · {status} · {n.props.get('summary', '')}")
    if not topics():
        print("(the wiki is empty)")


# ---- init -----------------------------------------------------------------

INDEX_MD = f"""---
wiki: index
---
# Wiki index

Every topic and article in the vault's wiki, from their properties. Agents read it with
`sbmap wiki index`.

{INDEX_START}
{INDEX_END}

![[wiki/wiki.base#Needs attention]]
"""

LOG_MD = """---
wiki: log
---
# Wiki log

Append-only, newest last, written by `sbmap wiki log`.
"""

README_MD = """# The wiki

Compiled knowledge: articles under `<topic>/`, their sources under `raw/`. Start at `index.md`.
The format and the commands: the `sb` skill's `reference/wiki.md` (`sbmap wiki`).
"""

WIKI_BASE = """filters:
  and:
    - file.inFolder("wiki")
    - 'wiki == "article" || wiki == "synthesis"'
properties:
  file.name:
    displayName: Article
views:
  - type: table
    name: To review
    filters:
      and:
        - wiki == "article"
        - '!reviewed || reviewed < updated'
    order:
      - file.name
      - summary
      - updated
      - reviewed
    sort:
      - property: updated
        direction: DESC
  - type: table
    name: By topic
    filters:
      and:
        - wiki == "article"
    groupBy:
      property: file.folder
      direction: ASC
    order:
      - file.name
      - type
      - status
      - summary
  - type: table
    name: Needs attention
    filters:
      and:
        - wiki == "article"
        - status != "current"
    order:
      - file.name
      - status
      - summary
      - updated
  - type: table
    name: Recently updated
    filters:
      and:
        - wiki == "article"
    order:
      - file.name
      - updated
      - summary
    sort:
      - property: updated
        direction: DESC
  - type: table
    name: Synthesis
    filters:
      and:
        - wiki == "synthesis"
    order:
      - file.name
      - archived
      - summary
    sort:
      - property: archived
        direction: DESC
"""


def cmd_init(args):
    w = wiki_dir()
    (w / "raw").mkdir(parents=True, exist_ok=True)
    made = []
    for name, text in (("index.md", INDEX_MD), ("log.md", LOG_MD), ("README.md", README_MD),
                       ("wiki.base", WIKI_BASE)):
        if not (w / name).exists():
            sb.write_atomic(w / name, text)
            made.append(name)
    write_index()
    print("created " + (", ".join(made) if made else "nothing: the layout is complete"))


# ---- new ------------------------------------------------------------------

def make_topic(topic, about):
    if topic == "raw" or not SLUG.fullmatch(topic):
        die(f"topic '{topic}' must be kebab-case and not 'raw'")
    if folder_note(topic):
        return
    if not about:
        die(f"'{topic}' is a new topic: --about \"<what it covers>\" writes its folder note")
    if slug_taken(topic):
        die(f"slug '{topic}' is taken")
    (wiki_dir() / topic).mkdir(parents=True, exist_ok=True)
    heading = topic.replace("-", " ").capitalize()
    n = Note.__new__(Note)
    n.path, n.body = wiki_dir() / topic / f"{topic}.md", f"# {heading}\n\n{about.strip()}\n"
    n.save({"wiki": "topic", "type": "topic", "summary": about.strip(), "tags": ["wiki/topic"]})


def cmd_new(args):
    if not args or "/" not in args[0]:
        die("usage: wiki new <topic>/<slug> --title … --type … --summary … --sources …")
    topic, slug = args[0].split("/", 1)
    title = sb.opt(args, "--title") or die("--title is required")
    type_ = sb.opt(args, "--type") or die("--type is required")
    summary = sb.opt(args, "--summary") or die("--summary is required")
    if type_ not in ("concept", "entity", "synthesis"):
        die("--type must be concept, entity or synthesis")
    if not SLUG.fullmatch(slug) or len(slug) > 60:
        die(f"slug '{slug}' must be kebab-case, at most 60 characters")
    if DATED.match(slug):
        die(f"slug '{slug}' starts with digits and a dash, which Semantra reads as a ticket number")
    if topic == "raw":
        die("'raw' is reserved for sources: `wiki raw`")
    if slug_taken(slug):
        die(f"slug '{slug}' is taken")
    kind = "synthesis" if type_ == "synthesis" else "article"
    sources = ref_links(sb.opt(args, "--sources", ""), kind)
    if not sources:
        die("--sources is required")
    related = ref_links(sb.opt(args, "--related", ""), key="related")
    make_topic(topic, sb.opt(args, "--about"))
    props = {"wiki": kind, "type": type_}
    if kind == "article":
        props.update(status="current", summary=summary, updated=today())
    else:
        props.update(summary="[Archived] " + summary.removeprefix("[Archived] "), archived=today())
    props.update(sources=sources, related=related,
                 aliases=[a.strip() for a in (sb.opt(args, "--aliases") or "").split(",") if a.strip()],
                 tags=[f"wiki/{type_}"])
    n = Note.__new__(Note)
    n.path = wiki_dir() / topic / f"{slug}.md"
    n.save(props, f"# {title}\n\n## Overview\n\n{summary.removeprefix('[Archived] ')}\n")
    write_index()
    print(n.rel)


# ---- read -----------------------------------------------------------------

def cmd_link(args):
    print(Note(note_path(args[0])).link())


def sections(body):
    """[(heading line or None, text)] in order."""
    out, head, lines = [], None, []
    for line in body.splitlines():
        if re.match(r"#{1,6} ", line):
            out.append((head, "\n".join(lines).strip()))
            head, lines = line, []
        else:
            lines.append(line)
    out.append((head, "\n".join(lines).strip()))
    return out


def callouts(body):
    return re.findall(r"^> \[!(?:warning|question)\].*(?:\n>.*)*", body, re.M)


def cmd_show(args):
    n = Note(note_path(args[0]))
    print(f"# {n.title}  ({n.rel})")
    for k in WIKI_KEYS:
        if k in n.props and k != "tags" and n.props[k] not in ("", []):
            v = n.props[k]
            print(f"{k}: " + (", ".join(v) if isinstance(v, list) else str(v)))
    if "--full" in args:
        print("\n" + n.body.strip())
        return
    overview = ""
    for head, text in sections(n.body):
        if head is None or head.startswith("# "):
            continue
        print("\n" + head)
        if head == "## Overview" and text:
            overview = text
            print(text)
    for c in callouts(n.body):
        if c not in overview:
            print("\n" + c)


def raw_notes():
    """Every note an article may cite: wiki/raw, Clippings, research notes, resolved tickets."""
    out = []
    for folder in (wiki_dir() / "raw", sb.VAULT / "Clippings", sb.WAYFINDER):
        if folder.is_dir():
            out += [p for p in sorted(folder.rglob("*.md")) if "backups" not in p.parts
                    and raw_class(p) and (raw_class(p) != "ticket" or sb.Ticket(p).status == "resolved")]
    return out


def describe(path):
    """(type, status, summary) for one line of output."""
    if raw_class(path) == "ticket":
        t = sb.Ticket(path)
        return t.type + " ticket", t.status, t.title
    n = Note(path)
    if raw_class(path):
        return "source", "-", n.title
    return n.props.get("type", ""), n.props.get("status") or n.kind, n.props.get("summary", "")


def cmd_find(args):
    limit = int(sb.opt(args, "--limit", 10))
    terms = [a.lower() for i, a in enumerate(args)
             if not a.startswith("--") and (i == 0 or args[i - 1] != "--limit")]
    if not terms:
        die("find needs at least one term")
    paths = [n.path for n in wiki_notes()] + (raw_notes() if "--raw" in args else [])
    scored = []
    for p in paths:
        n = Note(p)
        names = (n.title + " " + " ".join(n.refs("aliases"))).lower()
        summary, body = str(n.props.get("summary", "")).lower(), n.body.lower()
        score = sum(3 * (t in names) + 2 * (t in summary) + (t in body) for t in terms)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], sb.rel(x[1])))
    for score, p in scored[:limit]:
        type_, status, summary = describe(p)
        print(f"{sb.rel(p)[:-3]} · {type_} · {status} · {score} · {summary}")
    if not scored:
        print("no matches")
    elif len(scored) > limit:
        print(f"({len(scored) - limit} more; --limit)")


# ---- raw ------------------------------------------------------------------

def cmd_raw(args):
    topic = args[0] if args and not args[0].startswith("--") else die("usage: wiki raw <topic> …")
    if topic == "raw" or not SLUG.fullmatch(topic):
        die(f"topic '{topic}' must be kebab-case and not 'raw'")
    title = sb.opt(args, "--title") or die("--title is required")
    source = sb.opt(args, "--source") or die("--source is required")
    src = sb.opt(args, "--from") or die("--from <file|-> is required")
    if re.match(r"https?://", source):
        for p in raw_notes():
            if raw_class(p) in ("raw", "clipping") and Note(p).props.get("source") == source:
                print(sb.rel(p))
                die(f"{source} is already kept as {sb.rel(p)}")
    text = sys.stdin.read() if src == "-" else Path(src).expanduser().read_text(encoding="utf-8")
    base = slugify(title) or "source"
    slug, i = base, 1
    while slug_taken(slug):
        i += 1
        slug = f"{base}-{i}"
    props = {"wiki": "raw", "type": "source", "title": title, "source": source,
             "author": sb.opt(args, "--author", ""), "published": sb.opt(args, "--published", "Unknown"),
             "created": today(), "tags": ["wiki/source"]}
    path = wiki_dir() / "raw" / topic / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    sb.write_atomic(path, sb.dump_fm(props, WIKI_KEYS) + text)
    print(sb.rel(path))


# ---- set ------------------------------------------------------------------

def entry_key(entry):
    """What a list entry points at, comparable across alias and `.md` spellings."""
    m = LINK.fullmatch(str(entry).strip())
    t = m.group(2).strip() if m else str(entry).strip()
    return t[:-3] if t.endswith(".md") else t


def status_after_supersession(n):
    if n.refs("superseded_by"):
        return "outdated"
    return "disputed" if DISPUTED.search(n.body) else "current"


def cmd_set(args):
    n = Note(note_path(args[0]))
    props = dict(n.props)
    others = {}  # path -> Note, the far ends of reciprocal links

    def far(path):
        if path not in others:
            others[path] = Note(path)
        return others[path]

    for kv in args[1:]:
        m = re.fullmatch(r"([A-Za-z_]\w*)([+-]?)=(.*)", kv, re.S)
        if not m:
            die(f"'{kv}' is not key=value, key+=refs or key-=refs")
        key, op, value = m.groups()
        if key in REF_KEYS:
            new = [resolve_ref(r) for r in split_refs(value)]
            if key == "sources":
                for p, _ in new:
                    why = op != "-" and source_problem(n.kind, p)
                    if why:
                        die(why)
            old = list(n.refs(key)) if key not in props else list(props.get(key) or [])
            have = {entry_key(e) for e in old}
            if op == "+":
                result = old + [link for _, link in new if entry_key(link) not in have]
            elif op == "-":
                drop = {entry_key(link) for _, link in new}
                result = [e for e in old if entry_key(e) not in drop]
            else:
                result = [link for _, link in new]
            props[key] = result
            if key in RECIPROCAL:
                back, me = RECIPROCAL[key], n.link()
                before, after = {entry_key(e) for e in old}, {entry_key(e) for e in result}
                for k in (before ^ after):
                    p = target_of(k)
                    if p is None:
                        continue
                    o = far(p)
                    lst = [e for e in o.refs(back) if entry_key(e) != entry_key(me)]
                    if k in after:
                        lst.append(me)
                    o.props = {**o.props, back: lst}
        elif key in ("aliases", "tags"):
            items = [a.strip() for a in value.split(",") if a.strip()]
            old = list(props.get(key) or [])
            props[key] = (old + [i for i in items if i not in old] if op == "+"
                          else [o for o in old if o not in items] if op == "-" else items)
        elif op:
            die(f"'{key}' is not a list: use {key}=value")
        else:
            if key == "status" and value not in STATUSES:
                die(f"status must be one of {', '.join(STATUSES)}")
            if value == "today" and key in DATE_KEYS:
                value = today()
            props[key] = value
    n.props = props
    supersession = any(re.match(r"supersede", a) for a in args[1:])
    for note in [n] + list(others.values()):
        if supersession and note.kind == "article":
            note.props = {**note.props, "status": status_after_supersession(note)}
        note.save()
    write_index()
    print(f"{n.rel}: " + " ".join(args[1:]) + (f" (and {', '.join(o.rel for o in others.values())})"
                                                if others else ""))


# ---- log ------------------------------------------------------------------

def try_note(arg):
    try:
        return Note(note_path(arg))
    except SystemExit:
        return None


def cmd_log(args):
    kind = args[0] if args else ""
    if kind not in ("learn", "ask", "tend"):
        die("usage: wiki log <learn|ask|tend> --subject \"…\"")
    subject = sb.opt(args, "--subject") or die("--subject is required")
    m = re.fullmatch(r"(Archived: )?(.+)", subject)
    if not subject.startswith("no material: "):
        n = try_note(m.group(2))
        if n is not None:
            subject = (m.group(1) or "") + n.link()
    lines = [f"## [{today()}] {kind} | {subject}"]
    if sb.opt(args, "--disposition"):
        lines.append(f"- Disposition: {sb.opt(args, '--disposition')}")
    for flag, name in (("--raw", "Raw"), ("--updated", "Updated")):
        if sb.opt(args, flag):
            lines.append(f"- {name}: " + ", ".join(link for _, link in map(resolve_ref, split_refs(sb.opt(args, flag)))))
    p = wiki_dir() / "log.md"
    if not p.exists():
        die("no wiki/log.md: `sbmap wiki init`")
    sb.write_atomic(p, p.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + "\n".join(lines) + "\n")
    print(lines[0])


# ---- backlog --------------------------------------------------------------

def cited():
    """Every note some article or synthesis page names in `sources`."""
    return {entry_key(e) for n in articles() for e in n.refs("sources")}


def no_material():
    p = wiki_dir() / "log.md"
    if not p.exists():
        return set()
    found = re.findall(r"^## \[[^\]]*\] learn \| no material: (.+?)\s*$", p.read_text(encoding="utf-8"), re.M)
    return {entry_key(f) for f in found}


def backlog():
    done = cited() | no_material()
    out = []
    for p in raw_notes():
        key = sb.rel(p)[:-3]
        if key in done or (raw_class(p) == "ticket" and sb.Ticket(p).type != "research"):
            continue
        created = str(Note(p).props.get("created") or date.fromtimestamp(p.stat().st_mtime).isoformat())
        out.append((created[:10], key, p))
    return sorted(out)


def cmd_backlog(args):
    limit = int(sb.opt(args, "--limit", 10))
    items = backlog()
    for created, key, p in items[:limit]:
        print(f"{key} · {created} · {describe(p)[2]}")
    print(f"{len(items)} on the backlog" + (f", {limit} shown" if len(items) > limit else ""))


# ---- grounding ------------------------------------------------------------
# Candidate literals, ported from the karpathy-llm-wiki skill's scripts/check_evidence.py:
#
#   MIT License
#
#   Copyright (c) 2026 Yuhan Lei
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in all
#   copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#   SOFTWARE.
#
# Closed candidate set: quotes of 15+ characters (double-quoted spans and plain blockquotes), ISO
# dates, and numbers that are grouped (10,000), dotted (2.1.80), suffixed (42K, 99.9%) or 4+ digits.
# Changed here: callouts are prose, not quotes, and their own date is not evidence; wikilinks read
# as their alias.

NUMBER_TOKEN = re.compile(r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)*(?:\s*[KMB%](?![A-Za-z]))?"
                          r"|\d+(?:\.\d+)*(?:\s*[KMB%](?![A-Za-z]))?)(?![A-Za-z])")
ISO_DATE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")
QUOTED = re.compile(r'"([^"\n]*)"')
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def plain(text):
    """Whitespace collapsed, curly quotes straight: both sides of every comparison."""
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    return re.sub(r"\s+", " ", text).strip()


def unfenced(text):
    out, fence = [], None
    for line in text.splitlines():
        m = FENCE.match(line)
        if fence:
            if m and m.group(1)[0] == fence:
                fence = None
            continue
        if m:
            fence = m.group(1)[0]
            continue
        out.append(line)
    return out


def denoise(line):
    line = re.sub(r"`[^`\n]*`", " ", line)
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
    return LINK.sub(lambda m: m.group(4) or m.group(2), line)


def keep_number(token):
    token = token.strip()
    return bool(re.search(r"[KMB%]$", token)) or "," in token or "." in token or len(token) >= 4


def literals(line):
    found = [("date", m.group(0)) for m in ISO_DATE.finditer(line)]
    masked = ISO_DATE.sub(lambda m: " " * len(m.group(0)), line)
    return found + [("number", m.group(0)) for m in NUMBER_TOKEN.finditer(masked) if keep_number(m.group(0))]


def candidates(body):
    out, quote, para, callout = [], [], [], False

    def flush(buf, as_quote):
        if not buf:
            return
        joined = plain(" ".join(buf))
        if as_quote and len(joined) >= 15:
            out.append(("quote", joined))
        elif not as_quote:
            out.extend(("quote", m.group(1)) for m in QUOTED.finditer(joined) if len(m.group(1).strip()) >= 15)
        buf.clear()

    for line in unfenced(plain_quotes(body)):
        s = line.strip()
        if s.startswith(">"):
            flush(para, False)
            content = denoise(s.lstrip(">").strip())
            if content.startswith("[!"):
                callout = True
                continue
            out.extend(literals(content))
            (para if callout else quote).append(content)
            continue
        flush(quote, True)
        if callout:
            flush(para, False)
            callout = False
        if not s:
            flush(para, False)
            continue
        line = denoise(line)
        out.extend(literals(line))
        para.append(line)
    flush(quote, True)
    flush(para, False)
    seen, unique = set(), []
    for kind, value in out:
        value = value.strip().strip(".,;:()[]")
        if value and (kind, value) not in seen:
            seen.add((kind, value))
            unique.append((kind, value))
    return unique


def plain_quotes(text):
    return text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")


def holds(haystack, kind, value):
    if kind == "quote":
        return value in haystack
    right = r"(?!-\d{2})" if kind == "date" and len(value) == 7 else ""
    return re.search(r"(?<![\d.,])" + re.escape(value) + right + r"(?![A-Za-z0-9]|[.,]\d|%)", haystack) is not None


def suspects(n):
    sources = [target_of(entry_key(e)) for e in n.refs("sources")]
    texts = [plain("\n".join(unfenced(sb.split_fm(p.read_text(encoding="utf-8"))[1]))) for p in sources if p]
    if not texts:
        return []
    return [v for kind, v in candidates(n.body) if not any(holds(t, kind, plain(v)) for t in texts)]


# ---- check ----------------------------------------------------------------

REQUIRED = {"article": ("summary", "updated", "status", "sources"), "synthesis": ("summary", "archived", "sources"),
            "topic": ("summary",), "raw": ("title", "source")}
SKIP_DIRS = {".obsidian", ".trash", "backups"}


def by_name(name):
    """Every vault file with this name, outside Obsidian's own folders."""
    return [p for p in sb.VAULT.rglob(name) if not SKIP_DIRS & set(p.relative_to(sb.VAULT).parts)]


CODE_SPAN = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def outside_code(text, fn, keep_code=False):
    """fn applied to the text between code spans; the spans kept, or blanked for searching."""
    out, last = [], 0
    for m in CODE_SPAN.finditer(text):
        out += [fn(text[last:m.start()]), m.group(0) if keep_code else " " * len(m.group(0))]
        last = m.end()
    return "".join(out + [fn(text[last:])])


def cmd_check(args):
    fix = "--fix" in args
    w = wiki_dir()
    if not w.is_dir():
        die("no wiki/ yet: `sbmap wiki init`")
    problems, fixed = [], []

    def lab(p):
        return p.relative_to(w).as_posix()

    every = [p for p in sorted(w.rglob("*.md")) if lab(p) not in ROOT_FILES]
    # slugs and places
    stems = {}
    for p in every:
        stems.setdefault(p.stem, []).append(lab(p))
        parts = p.relative_to(w).parts
        if DATED.match(p.stem):
            problems.append(f"{lab(p)}: slug starts with digits and a dash")
        if len(parts) == 1:
            problems.append(f"{lab(p)}: outside a topic folder")
        elif (parts[0] == "raw" and len(parts) > 3) or (parts[0] != "raw" and len(parts) > 2):
            problems.append(f"{lab(p)}: deeper than wiki/<topic>/" + (" (raw/<topic>/ for sources)" if parts[0] == "raw" else ""))
    for stem, where in stems.items():
        if len(where) > 1:
            problems.append(f"slug '{stem}' is taken twice: {', '.join(where)}")
    for t in topics():
        if not (w / t / f"{t}.md").exists():
            problems.append(f"{t}: no folder note ({t}/{t}.md)")

    for p in every:
        n = Note(p)
        kind = "raw" if p.relative_to(w).parts[0] == "raw" else n.kind
        if kind not in TYPES:
            problems.append(f"{lab(p)}: unknown wiki '{n.kind}'")
            continue
        if kind == "raw":
            if n.kind != "raw":
                problems.append(f"{lab(p)}: a source without wiki: raw")
        elif n.props.get("type") not in TYPES[kind]:
            problems.append(f"{lab(p)}: unknown type '{n.props.get('type', '')}' for {kind}")
        for key in REQUIRED[kind]:
            if not n.props.get(key):
                problems.append(f"{lab(p)}: missing {key}")
        if kind == "raw":
            continue
        if kind == "article":
            status = n.props.get("status")
            if status and status not in STATUSES:
                problems.append(f"{lab(p)}: unknown status '{status}'")
            elif status and status != status_after_supersession(n):
                problems.append(f"{lab(p)}: status is {status}; the rule makes it {status_after_supersession(n)}")
        for m in OUTDATED.finditer(n.body):
            if not re.match(r"\s*\(\d{4}-\d{2}-\d{2}\)", m.group(1)):
                problems.append(f"{lab(p)}: Outdated callout without its date")
        me = sb.rel(p)[:-3]
        for key, back in RECIPROCAL.items():
            for e in n.refs(key):
                q = target_of(entry_key(e))
                if q and me not in {entry_key(x) for x in Note(q).refs(back)}:
                    problems.append(f"{lab(q) if q.is_relative_to(w) else sb.rel(q)}: missing {back} back to {me}")
        for e in n.refs("sources"):
            q = target_of(entry_key(e))
            why = q and source_problem(kind, q)
            if why:
                problems.append(f"{lab(p)}: {why}")

        # links: in properties and prose
        changed = False

        def repair(m, key=None):
            nonlocal changed
            target = m.group(2).strip()
            if not target or "/" not in target:
                if target:
                    problems.append(f"{lab(p)}: wikilink by bare file name: {m.group(0)}")
                return m.group(0)
            if target_of(target):
                return m.group(0)
            name = Path(target).name
            hits = by_name(name if "." in name else name + ".md")
            if len(hits) == 1:
                new = sb.rel(hits[0])
                new = new[:-3] if new.endswith(".md") else new
                if fix:
                    changed = True
                    fixed.append(f"{lab(p)}: link moved to {new}")
                    return f"{m.group(1)}[[{new}{m.group(3) or ''}" + (f"|{m.group(4)}" if m.group(4) is not None else "") + "]]"
                problems.append(f"{lab(p)}: link moved: {m.group(0)} -> {new}")
                return m.group(0)
            if key == "related":
                if fix:
                    changed = True
                    fixed.append(f"{lab(p)}: dropped dead related {target}")
                    return None
                problems.append(f"{lab(p)}: related link to a note that no longer exists: {target}")
                return m.group(0)
            problems.append(f"{lab(p)}: broken link: {m.group(0)}")
            return m.group(0)

        props = dict(n.props)
        for key, v in n.props.items():
            if isinstance(v, list):
                kept = []
                for e in v:
                    m = LINK.fullmatch(str(e).strip())
                    r = repair(m, key) if m else e
                    if r is not None:
                        kept.append(r)
                props[key] = kept
        prose = outside_code(n.body, lambda seg: seg)
        body = outside_code(n.body, lambda seg: LINK.sub(lambda m: repair(m), seg), keep_code=True)
        for m in re.finditer(r"\[[^\]]*\]\((?!https?://|mailto:)([^)\s]+?\.md)\)", prose):
            problems.append(f"{lab(p)}: markdown link to a vault note: {m.group(0)} (a full-path wikilink belongs here)")
        bare = re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]\([^)]*\)|https?://\S+", " ", prose)
        for m in re.finditer(r"(?:^|[^\w/&#\[])#(\d{2,4})\b", bare):
            problems.append(f"{lab(p)}: bare #{m.group(1)} (`sbmap link` prints the ticket's link)")
        if changed:
            n.save(props, body)

    index = w / "index.md"
    if index.exists() and stamped_index() != index.read_text(encoding="utf-8"):
        if fix:
            write_index()
            fixed.append("index.md: restamped")
        else:
            problems.append("index.md: the index block is out of date")

    for f in fixed:
        print("fixed " + f)
    for pr in problems:
        print(pr)
    sus = [(n, suspects(n)) for n in articles() if n.kind == "article"]
    sus = [(n, v) for n, v in sus if v]
    if sus:
        print("grounding suspects (judge each against its sources; never counted):")
        for n, values in sus:
            print(f"  {lab(n.path)}: " + " · ".join(values))
    print(f"{len(backlog())} on the backlog")
    print(f"{len(problems)} problem(s) in wiki/")
    sys.exit(1 if problems else 0)


COMMANDS = {"index": cmd_index, "find": cmd_find, "show": cmd_show, "link": cmd_link,
            "backlog": cmd_backlog, "init": cmd_init, "raw": cmd_raw, "new": cmd_new, "set": cmd_set,
            "log": cmd_log, "check": cmd_check}


def main(args):
    if not args or args[0] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[args[0]](args[1:])
