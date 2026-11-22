"""The hub queue's rules as pure functions: classify, order, move, brief, verdict.

Tickets are the dicts `sbmap tickets --json` prints. Nothing here reads the vault or the hub's state.
"""
import heapq
import os
import re
import subprocess
from pathlib import Path

PRIORITY = "SABCDEF"
SBMAP = Path(__file__).resolve().parent / "sbmap.py"
CHECK_TIMEOUT = 20 * 60
EX_TEMPFAIL = 75  # a check exits it when the tool it needs did not answer: it could not run, it did not fail
NOT_RUN = "check could not run"
SETUP_WRONG = "the check is set up wrong"
# a check line starting with this runs in the checkout itself once the ticket's work landed there, under the repo's
# Unity lock (sbhub TicketRun._land): sk4te's compile asks the one open Unity, which has the checkout open
AFTER_LANDING = "after-landing: "
# two more kinds that run in the checkout after landing, as Unity commands rather than shell (sbhub.unity_check):
# `unity: <command> [args]` queues in the Editor's own command queue and takes no hub lock; `unity-session: <command>`
# takes the repo's Unity lock for that one command (a recompile, Play). Both keep their mark so the hub knows the kind.
UNITY = "unity: "
UNITY_SESSION = "unity-session: "


def is_unity_line(cmd):
    """True for a `unity:` or `unity-session:` check line."""
    return cmd.startswith(UNITY) or cmd.startswith(UNITY_SESSION)


def after_landing(checks):
    """The check lines that run in the checkout once the ticket landed: after-landing commands without the mark,
    and the Unity lines with theirs."""
    return [c[len(AFTER_LANDING):].strip() if c.startswith(AFTER_LANDING) else c
            for c in checks if c.startswith(AFTER_LANDING) or is_unity_line(c)]


def before_landing(checks):
    """The check lines that run before landing (every line not marked after-landing, unity or unity-session)."""
    return [c for c in checks if not c.startswith(AFTER_LANDING) and not is_unity_line(c)]


def key(t):
    return f"{t['map']}#{int(t['num'])}"


def _blocker_key(t, b):
    return f"{t['map']}#{int(b)}" if isinstance(b, int) else None


def _rank(t):
    p = t.get("priority") or "C"
    return PRIORITY.index(p) if p in PRIORITY else PRIORITY.index("C")


def classify(t, queued, tickets=()):
    """(state, reason) of one open ticket; `queued` is the set of queued keys, `tickets` names the blockers."""
    if t["status"] == "claimed":
        return "claimed", f"claimed by {t.get('claimed_by') or 'another session'}"
    if t["type"] in ("grilling", "architecture"):
        if t.get("ruling"):
            return "not ready", "ruled: a session files the work from your answer"
        return "waits for you", f"a {t['type']} ticket needs you"
    if t.get("check") == "owner":
        return "waits for you", "you check this one: a worker cannot"
    if not t["has_done_when"]:
        return "not ready", "no done-when"
    # no check commands on any layer: it still runs, and the Opus review of its Done when is its only check
    for b in t["blocked_by_open"]:
        if _blocker_key(t, b) not in queued:
            return "blocked", f"after {_title(t, b, tickets)}"
    return "ready", "ready"


def _title(t, b, tickets):
    """A blocker's title if `tickets` has it, else its reference."""
    for o in tickets:
        if o["map"] == t["map"] and isinstance(b, int) and int(o["num"]) == b:
            return o["title"]
    return f"ticket {b}" if isinstance(b, int) else str(b)


def map_of(k):
    """The map of a queue key (`<map>#<num>`); a job's key is its own map."""
    return k.rsplit("#", 1)[0] if "#" in k else k


def map_list(maps, keys):
    """`maps` with every map of `keys` it lacks added after it, in the order their first keys appear: a single
    ticket whose map is not queued is a map of one at its place."""
    out = list(dict.fromkeys(maps or ()))
    for k in keys:
        if "#" in k and map_of(k) not in out:
            out.append(map_of(k))
    return out


def _live_deps(tickets, queued):
    """(live, deps): the queued tickets that can run, and for each the keys it waits on."""
    by = {key(t): t for t in tickets}
    live = {k: by[k] for k in queued if k in by}
    # drop what waits on something neither resolved nor queued, and what waits on a dropped ticket
    changed = True
    while changed:
        changed = False
        for k, t in list(live.items()):
            if any(_blocker_key(t, b) not in live for b in t["blocked_by_open"]):
                del live[k]
                changed = True
    return live, {k: {_blocker_key(t, b) for b in t["blocked_by_open"]} for k, t in live.items()}


def chains(tickets, queued):
    """For each runnable queued key, how many queued tickets wait on it directly or through others, each once."""
    live, deps = _live_deps(tickets, queued)
    out = {}
    for k in live:
        seen, todo = set(), [k]
        while todo:
            x = todo.pop()
            for o, d in deps.items():
                if x in d and o not in seen:
                    seen.add(o)
                    todo.append(o)
        out[k] = len(seen)
    return out


def order(tickets, queued, maps=()):
    """Queued keys in run order: map by map in `maps` order (a map it does not name comes after, where its first
    key is), and inside a map blockers first, then the longest chain of tickets freed (directly or through
    others), then priority, then map order and number."""
    live, deps = _live_deps(tickets, queued)
    unblocks = chains(tickets, queued)
    pos = {k: i for i, k in enumerate(queued)}
    place = {m: i for i, m in enumerate(map_list(maps, queued))}

    def rank(k):
        t = live[k]
        return (place[map_of(k)], -unblocks[k], _rank(t), int(t.get("map_order") or 0), int(t["num"]), pos[k])

    waiting = {k: set(d) for k, d in deps.items()}
    heap = [(rank(k), k) for k, d in waiting.items() if not d]
    heapq.heapify(heap)
    out = []
    while heap:
        _, k = heapq.heappop(heap)
        out.append(k)
        for o, d in waiting.items():
            if k in d:
                d.discard(k)
                if not d:
                    heapq.heappush(heap, (rank(o), o))
    if len(out) != len(live):
        raise ValueError("dependency cycle among " + ", ".join(sorted(set(live) - set(out))))
    return out


HOLDING = ("running", "landed", "review", "recheck", "unclean", "handed")  # at work or not judged yet: its map stays current


def map_queueable(tickets, name, live):
    """(keys, left_out) for queueing every open ticket of map `name`: what waits on an earlier ticket of the map
    comes too and starts when that one lands. Left out, each as (key, reason): claimed tickets, ones that need the
    owner or have no done-when or checks, and ones waiting on what is neither resolved nor queued (another map
    that is not queued, or a ticket left out)."""
    rows = [t for t in tickets if t["map"] == name and key(t) not in live]
    take = {key(t): t for t in rows}
    changed = True
    while changed:
        changed = False
        for k, t in list(take.items()):
            if classify(t, set(live) | set(take), tickets)[0] != "ready":
                del take[k]
                changed = True
    left = [(key(t), "{}: {}".format(*classify(t, set(live) | set(take), tickets))) for t in rows
            if key(t) not in take]
    return [key(t) for t in rows if key(t) in take], left


def stuck_on(k, by, live, items=None):
    """(key, words) of the ticket queued key `k` is stuck behind: its first open blocker that is neither resolved
    nor queued nor at work, followed through the queued ones; `k` itself when nothing blocks it."""
    seen = set()
    while k not in seen:
        seen.add(k)
        t = by.get(k)
        if t is None:
            return k, "no longer open"
        nxt = None
        for b in t["blocked_by_open"]:
            bk = _blocker_key(t, b)
            if bk is None:
                return k, "after {}".format(b)
            if bk not in live:
                state = next((i["state"] for i in items or () if i["key"] == bk), None)
                return bk, {"failed": "failed", "skipped": "skipped", "done": "not resolved"}.get(state, "not queued")
            nxt = nxt or bk
        if nxt is None:
            return k, classify(t, live)[1]
        k = nxt
    return k, "a dependency cycle"


def current_maps(items, by, maps, live, repo_of=None):
    """({repo: map}, {map: [stuck queued keys]}): in each repo, the first map in `maps` order with a ticket at work
    (running, in review or waiting on a recheck) or a queued one the hub can act on now: one that starts, or one it
    skips (gone, claimed, not ready). A queued ticket waiting on a queued ticket of its map is neither; one waiting
    on what is neither queued nor at work is stuck. The maps before a repo's current one, and every map of a repo
    with no current one, give their queued tickets as stuck. Repos are independent. `by`: key -> fresh row."""
    repo_of = repo_of or (lambda i: (by.get(i["key"]) or {}).get("repo") or i.get("repo"))
    tickets = [i for i in items if i["kind"] == "ticket" and "#" in i["key"]]
    order_ = map_list(maps, [i["key"] for i in tickets])
    acting, queued = {}, {}  # (repo, map) -> True when it has work or something to act on; its queued keys
    for i in tickets:
        rm = (repo_of(i), map_of(i["key"]))
        if i["state"] in HOLDING:
            acting[rm] = True
        elif i["state"] == "queued":
            queued.setdefault(rm, []).append(i["key"])
            t = by.get(i["key"])
            waits = t is not None and any(_blocker_key(t, b) not in live for b in t["blocked_by_open"])  # stuck
            if t is None or not waits and (not t["blocked_by_open"] or classify(t, live)[0] != "ready"):
                acting[rm] = True
    current, stuck = {}, {}
    for repo in dict.fromkeys(r for r, _ in list(acting) + list(queued)):
        for m in order_:
            if acting.get((repo, m)):
                current[repo] = m
                break
            if queued.get((repo, m)):
                stuck.setdefault(m, []).extend(queued[(repo, m)])
    return current, stuck


def move(order_keys, k, to_index, tickets):
    """The owner's drag, clamped to after k's blockers and before the tickets that wait on k."""
    by = {key(t): t for t in tickets}
    rest = [x for x in order_keys if x != k]
    t = by.get(k)
    blockers = {_blocker_key(t, b) for b in t["blocked_by_open"]} if t else set()
    lo = max((i + 1 for i, x in enumerate(rest) if x in blockers), default=0)
    hi = min((i for i, x in enumerate(rest)
              if x in by and k in {_blocker_key(by[x], b) for b in by[x]["blocked_by_open"]}),
             default=len(rest))
    rest.insert(max(lo, min(to_index, hi)), k)
    return rest


# A Done-when item that starts "In Play" (`In Play: ...`, also `In Play, ...` as older tickets wrote it) is checked in
# the Unity Editor: the worker leaves it, and the map's Opus review plays it on main under the repo's Unity lock
PLAY = re.compile(r"^In Play\b\s*[:,]?\s*", re.I)
NOT_PLAYED = "not played yet"  # the review's word for an In Play line it could not play: neither met nor not met
_ITEM = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)")


def _numbered(text):
    """One line written as `1. a 2. b 3. c`, cut at each next number in turn; any other line whole."""
    if not re.match(r"\s*1[.)]\s", text):
        return [text]
    cuts, n = [0], 2
    while True:
        m = re.compile(r"(?<=\s){}[.)]\s".format(n)).search(text, cuts[-1] + 1)
        if not m:
            break
        cuts.append(m.start())
        n += 1
    return [text[a:b].strip() for a, b in zip(cuts, cuts[1:] + [len(text)])]


def done_items(done_when):
    """A ticket's Done when as its items, list marks removed: one per `- `/`1. ` line (a line without a mark goes
    on with the item before it), and `1. a 2. b` written on one line cut into its numbers."""
    lines = []
    for line in (done_when or "").splitlines():
        if not line.strip():
            continue
        if _ITEM.match(line) or not lines:
            lines.append(line.strip())
        else:
            lines[-1] += " " + line.strip()
    return [_ITEM.sub("", i, count=1).strip() for line in lines for i in _numbered(line) if i.strip()]


def play_lines(done_when):
    """The Done-when items checked in Play (they start `In Play`), as written."""
    return [i for i in done_items(done_when) if PLAY.match(i)]


PLAY_BRIEF = ("Played by the review, leave it: the Opus review plays these on main, in the one Unity Editor, after your "
              "work lands, and you are not judged on them. Do not try to play them, and do not hold back your commit "
              "for them; build what they need, and say under `## Play checks` in your report how to see each one:")


BRIEF_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "session-brief.md"
# the worker brief's checks line when no layer gives a command (the template says "These commands must all exit 0")
NO_CHECKS_BRIEF = ("- none: this ticket has no check commands. After you finish, an Opus reviewer reads your change "
                   "and judges each Done when item met or not met, and only that decides if it is done: check every "
                   "item yourself before you commit (run it, look at the result) and say how under ## Self-checks.")


def brief(t, map_plain_words, run_folder, repo, branch):
    """The worker's prompt: templates/session-brief.md with each {name} filled from the ticket alone.
    A line whose value is empty (no paths, say) is dropped; a name the template uses and this does not fill is a bug."""
    num = int(t["num"])
    sbmap = f"python3 {SBMAP}"
    values = {
        "background": map_plain_words, "repo": repo, "branch": branch, "sbmap": sbmap, "map": t["map"],
        "num": str(num), "num3": f"{num:03d}", "title": t["title"], "why": t["why"], "question": t["question"],
        "out": t["out"] or "anything outside the ticket", "paths": ", ".join(t["paths"]),
        "done_when": t["done_when"], "checks": "\n".join(f"- {c}" for c in t["checks"]) or NO_CHECKS_BRIEF,
        "run_folder": str(run_folder),
        "play": "\n".join([PLAY_BRIEF] + ["- " + p for p in play_lines(t["done_when"])])
        if play_lines(t["done_when"]) else "",
    }
    return _fill(BRIEF_TEMPLATE, values)


REVIEW_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "review-brief.md"
REVIEW_TICKET_TEMPLATE = REVIEW_TEMPLATE.with_name("review-ticket.md")
VERDICTS = ("finished", "partly", "not met")
DIFF_MAX = 60000  # characters of the commit's diff handed to the review inline; the rest it reads with git
NO_CHANGE = re.compile(r"^#{1,6}\s*No change needed\s*$", re.M | re.I)


def _fill(template, values):
    """A brief template with each {name} filled; a line whose value is empty is dropped, an unknown name raises."""
    text = re.sub(r"\A<!--.*?-->\n+", "", Path(template).read_text(encoding="utf-8"), flags=re.S)
    out = []
    for line in text.split("\n"):
        names = re.findall(r"\{(\w+)\}", line)
        unknown = [n for n in names if n not in values]
        if unknown:
            raise KeyError(f"{Path(template).name} names {unknown[0]}, which the hub cannot fill")
        if any(not values[n] for n in names):
            continue
        out.append(re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], line))
    return "\n".join(out).rstrip("\n") + "\n"


def review_section(ticket_text, repo, shas, diff, report_path, report_text, review_file, redo=None, second=None,
                   diff_max=DIFF_MAX, play=(), media=None):
    """One ticket's part of the second pass's prompt (templates/review-ticket.md): the ticket as `sbmap show` prints
    it, the diff of its commits `shas` (oldest first; cut at `diff_max`, the review reads the rest itself), the
    worker's report and the file its review goes in. `redo`: the item's review-driven try (its first try's commit,
    verdict and review), whose second try made `second` (None: no commit): both tries are judged together. `play`:
    its Done when's In Play lines, which the review plays on main; `media`: the folder their screenshots go in."""
    shas = [s for s in ([shas] if isinstance(shas, str) else shas or []) if s]
    if len(diff) > diff_max:
        diff = diff[:diff_max] + f"\n... cut at {diff_max} characters: read the rest with git show"
    first = (redo or {}).get("commit")
    if len(shas) > 1:
        commit_line = f"Commits {first} (the first try) and {second} (the second try), in {repo}."
    elif shas:
        commit_line = f"Commit {shas[0]}, in {repo}."
        if redo:
            commit_line += (" It is the first try's: the second try made no commit." if shas[0] == first else
                            " The first try made no commit.")
    else:
        commit_line = "The worker made no commit: its report says no change was needed, or it was research."
    values = {
        "ticket": ticket_text.strip() or "(sbmap could not show the ticket)", "repo": str(repo),
        "second_try": (f"This is the ticket's second and last try. The first was judged {redo.get('verdict')} by an "
                       f"earlier review ({redo.get('review') or 'not kept'}) and the second built on it: judge both "
                       f"tries' commits together, as one piece of work, against the Done when.") if redo else "",
        "commit_line": commit_line,
        "diff_cmd": "`git -C {} show {}`".format(repo, " ".join(shas)) if shas else "",
        "diff": diff.strip() or "(no change)", "report_path": str(report_path),
        "report": report_text.strip() or "(the worker wrote no report)", "review_file": str(review_file),
        "play": "### Its In Play lines\n\n{}\n\nIts screenshots go in: {}\n".format(
            "\n".join("- " + p for p in play), media or "the ticket's media folder") if play else "",
    }
    return _fill(REVIEW_TICKET_TEMPLATE, values).rstrip("\n")


PLAY_HELD = """## The In Play lines: you play them on main

Some tickets list In Play lines. The hub took the repo's Unity lock `{lock}` for you: while you run, nobody else
drives the one Unity Editor, which has the main folder ({repo}) open with every landed ticket's work in it. Never take
or free that lock yourself; the hub frees it when you end. Follow the repo's AGENTS.md for the Editor: recompile and
wait for it, read the console, then for each In Play line enter Play, do what it says, measure what it promises, and
stop Play. Edit no file and commit nothing; stop Play before you end. In that line of the review, record what you saw:
the numbers you measured, and the screenshots you saved in the ticket's media folder (named under it). A line you
played and saw work is `met`; one you saw fail is `not met`, with what you saw. One you could not play (the Editor did
not answer, the case cannot be reached) is `{not_played}`, with why."""

PLAY_BUSY = """## The In Play lines: not played yet

Some tickets list In Play lines, but {why}, so the Editor is not yours: do not touch it. Write each In Play line as
`{not_played}`, never `not met`, and judge every other item as usual."""

PLAY_VERDICT = ("A line `{}` counts neither for nor against the ticket: when every other item is met, the verdict is "
                "finished, and the hub puts the ticket on the owner's list of checks to play.").format(NOT_PLAYED)


def review_brief(sections, repo, unity=None):
    """The second pass's prompt for one map's run: templates/review-brief.md with each landed ticket's
    `review_section` in it, one review file per ticket. `unity`: {lock, held, who} when a ticket has In Play lines:
    `held`, the hub holds the repo's Unity lock for the review, which plays them; else `who` holds it, and the review
    marks them not played yet (no `who`: it runs outside the hub's queue and holds no lock)."""
    sections = list(sections)
    play = ""
    if unity:
        why = ("the repo's Unity lock `{}` has been held by {} for over ten minutes".format(unity.get("lock"),
                                                                                          unity["who"])
               if unity.get("who") else "this review runs outside the hub's queue, without the repo's Unity lock")
        play = "\n" + (PLAY_HELD if unity.get("held") else PLAY_BUSY).format(
            lock=unity.get("lock"), repo=repo, why=why, not_played=NOT_PLAYED)
    values = {"repo": str(repo), "count": str(len(sections)), "s": "" if len(sections) == 1 else "s",
              "tickets": "\n\n".join(sections), "play": play, "play_verdict": PLAY_VERDICT if unity else ""}
    return _fill(REVIEW_TEMPLATE, values)


def not_played(findings):
    """The review's item lines it could not play (`not played yet`, or an older review's `not played`)."""
    return [f for f in findings if re.search(r"\bnot played\b", f, re.I)]


def review_verdict(text):
    """The verdict a review file ends with (`Verdict: finished|partly|not met`, its last such line), else None."""
    found = re.findall(r"^\W*verdict\W*:?\W*(finished|partly|not met)\W*$", text or "", re.M | re.I)
    return found[-1].lower() if found else None


def review_findings(text):
    """The review's `- ` lines, one per Done-when item, for the ticket's comment."""
    return [l.strip() for l in (text or "").splitlines() if l.strip().startswith("- ")]


def _under(f, paths):
    return any(f == p.rstrip("/") or f.startswith(p.rstrip("/") + "/") for p in paths)


TEST_DIRS = {"test", "tests", "__tests__"}


def _owned_test(f, paths):
    """A test the ticket may add or change beside its own files: a test-named file in the folder of an owned
    file (or of an owned folder), or any file in a test/, tests/ or __tests__/ folder that sits in a folder
    holding an owned path. Configs and helpers outside such folders stay outside."""
    parts = f.split("/")
    owned = [p.rstrip("/") for p in paths]
    name = parts[-1]
    if ".test." in name or ".spec." in name or name.startswith("test_") or re.search(r"_test\.\w+$", name):
        if "/".join(parts[:-1]) in {o.rpartition("/")[0] for o in owned}:
            return True
    for i, d in enumerate(parts[:-1]):
        if d.lower() in TEST_DIRS:
            parent = "/".join(parts[:i])
            if not parent or any(o.startswith(parent + "/") for o in owned):
                return True
    return False


def verdict(t, repo, base_sha, run=subprocess.run, report=None, first_base=None, unity=None):
    """(passed, reason, sha): `passed` is None when a check exited 75 (could not run: neither passed nor failed, the
    commit stands). A trailered commit after base_sha and every check green. Files changed outside the
    ticket's paths are allowed (a change may need them) and named in the reason. A research ticket that made no
    commit passes on its written report alone (`report`, the worker's report file). A retry starts from HEAD, so an
    earlier try's commit sits behind base_sha: when nothing new carries the trailer, `first_base` (the item's first
    base) is searched too, and a trailered commit there stands as the ticket's commit."""
    num = int(t["num"])
    # a ticket moved to another map keeps its commit: the trailer may name the map it was on (same project, same number)
    wanted = re.compile(rf"Ticket: {re.escape(t['map'].split('/')[0])}/[^/\s]+/0*{num}")
    r = run(["git", "-C", str(repo), "log", f"{base_sha}..HEAD", "--format=%H%x00%B%x01"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"cannot read the commits after {base_sha[:12]}: {(r.stderr or '').strip()[:200]}", None
    log = r.stdout
    entries = [e.strip("\n").split("\x00", 1) for e in log.split("\x01") if e.strip()]
    sha = next((s.strip() for s, body in entries if any(wanted.fullmatch(l.strip()) for l in body.splitlines())), None)
    if not sha and first_base and first_base != base_sha:
        r2 = run(["git", "-C", str(repo), "log", f"{first_base}..HEAD", "--format=%H%x00%B%x01"],
                 capture_output=True, text=True)
        if r2.returncode == 0:
            es = [e.strip("\n").split("\x00", 1) for e in r2.stdout.split("\x01") if e.strip()]
            sha = next((s.strip() for s, body in es if any(wanted.fullmatch(l.strip()) for l in body.splitlines())), None)
    if not sha and t.get("type") == "research" and report and Path(report).is_file() and Path(report).stat().st_size:
        return True, "research: no commit needed, the findings are in the worker's report", None
    if not sha and report and Path(report).is_file() and NO_CHANGE.search(Path(report).read_text(encoding="utf-8",
                                                                                                  errors="replace")):
        return True, "no change needed: the worker made no commit and says why in its report", None
    if not entries and not sha:
        return False, f"no commit after {base_sha[:9]}", None
    if not sha:
        return False, f"no commit carries the trailer Ticket: {t['map']}/{num:03d}", None
    outside = ""
    if t["paths"]:
        files = run(["git", "-C", str(repo), "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha],
                    capture_output=True, text=True).stdout.split("\n")
        stray = [f for f in files if f and not _under(f, t["paths"]) and not _owned_test(f, t["paths"])]
        if stray:
            outside = "; it also changed files outside the ticket's list: " + ", ".join(stray[:10]) + (
                f" and {len(stray) - 10} more" if len(stray) > 10 else "")
    changed = run(["git", "-C", str(repo), "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha],
                  capture_output=True, text=True).stdout.strip()
    failed = _run_checks(t["checks"], repo, run, changed, unity)
    if not failed:
        return True, "commit and checks all good" + outside, sha
    if SETUP_WRONG in failed:  # never reaches Unity from here: no retry, no clean copy
        where = {"ticket": "the ticket's own `checks`", "map": "the map's `checks`",
                 "repo": "the repo's .sb/checks"}.get(t.get("checks_from"), "the ticket, its map or the repo")
        return False, failed + "\nFix the line in {}: this check runs in the ticket's own folder, where Unity " \
                               "never answers; call it with a `unity:` or `after-landing:` line, which runs on the main folder.".format(where), sha
    if failed.startswith(NOT_RUN):
        return None, failed, sha
    # Others' uncommitted work in the shared folder can break a check the commit itself passes: only then, try the
    # checks once more on a clean copy of the commit. A clean folder never pays for this.
    dirty = run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
                capture_output=True, text=True).stdout.split("\n")
    dirty = [l[3:] for l in dirty if l.strip()]
    if not dirty:
        return False, failed, sha
    clean = _clean_copy(repo, sha, run)
    if clean is None:
        return False, failed, sha
    try:
        again = _run_checks(t["checks"], clean, run, changed, unity)
    finally:
        _drop_clean_copy(repo, clean, run)
    if again:
        return (None if again.startswith(NOT_RUN) else False), again, sha
    shown = ", ".join(dirty[:5]) + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
    return True, ("commit and checks all good; the checks passed on a clean copy of the commit, because "
                  f"other uncommitted work in the shared folder breaks them there ({shown})" + outside), sha


NO_INSTANCE = re.compile(r"EDITOR_NOT_RUNNING|No Pipeline instance found for project", re.I)


def unreachable_unity(cwd, text):
    """True when a check's output says Unity has no instance for `cwd` and `cwd` is a linked worktree (a ticket's own
    copy of the repo): no Editor ever opens it, so trying again changes nothing."""
    return bool(NO_INSTANCE.search(text or "")) and (Path(str(cwd)) / ".git").is_file()


def _run_checks(checks, cwd, run, changed="", unity=None):
    """None when every check exits 0, else the first failure in words (starting NOT_RUN when it exited 75).
    SB_CHANGED holds the files the ticket's commit changed, one per line, so a check can test only what they reach
    (`codegraph affected --stdin`, see reference/hub.md). A Unity line goes to `unity(line, cwd, run)` (the hub's
    runner, same answer as this); with none it could not run."""
    env = {**os.environ, "SB_CHANGED": changed}
    for cmd in checks:
        if is_unity_line(cmd):
            failed = unity(cmd, cwd, run) if unity else f"{NOT_RUN}: {cmd} (only the hub runs Unity lines)"
            if failed:
                return failed
            continue
        if cmd.startswith(AFTER_LANDING):  # a ticket worked in the checkout itself: it already is where it lands
            cmd = cmd[len(AFTER_LANDING):].strip()
        try:
            r = run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=CHECK_TIMEOUT, env=env)
        except subprocess.TimeoutExpired:
            return f"check timed out after 20 minutes: {cmd}"
        if r.returncode != 0:
            tail = "\n".join(((r.stdout or "") + (r.stderr or "")).splitlines()[-20:])
            if unreachable_unity(cwd, tail):
                return f"check failed: {cmd}\n{SETUP_WRONG}: Unity has no instance for {cwd}\n{tail}"
            if r.returncode == EX_TEMPFAIL:
                return f"{NOT_RUN}: {cmd} exited {EX_TEMPFAIL} (the tool it needs did not answer)\n{tail}"
            return f"check failed: {cmd}\n{tail}"
    return None


def _clean_copy(repo, sha, run):
    """A detached worktree of sha beside nothing in the shared folder, with the folder's installed packages
    (node_modules up to two levels down) linked in so the checks need no install. None when git refuses."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="sb-clean-")) / "tree"
    r = run(["git", "-C", str(repo), "worktree", "add", "--detach", "--quiet", str(d), sha],
            capture_output=True, text=True)
    if r.returncode != 0:
        return None
    repo = Path(repo)
    for nm in [repo / "node_modules", *repo.glob("*/node_modules"), *repo.glob("*/*/node_modules")]:
        target = d / nm.relative_to(repo)
        if nm.is_dir() and target.parent.is_dir() and not target.exists():
            target.symlink_to(nm, target_is_directory=True)
    return d


def _drop_clean_copy(repo, d, run):
    run(["git", "-C", str(repo), "worktree", "remove", "--force", str(d)], capture_output=True, text=True)
    import shutil
    shutil.rmtree(d.parent, ignore_errors=True)
