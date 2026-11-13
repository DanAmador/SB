"""The hub queue's rules as pure functions: classify, order, move, brief, verdict.

Tickets are the dicts `sbmap tickets --json` prints. Nothing here reads the vault or the hub's state.
"""
import heapq
import re
import subprocess
from pathlib import Path

PRIORITY = "SABCDEF"
SBMAP = Path(__file__).resolve().parent / "sbmap.py"
CHECK_TIMEOUT = 20 * 60


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
        return "waits for you", f"a {t['type']} ticket needs you"
    if not t["has_done_when"]:
        return "not ready", "no done-when"
    if not t["checks"]:
        return "not ready", "no check commands"
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


def order(tickets, queued):
    """Queued keys in run order: blockers first, then priority, then most unblocked, then map order."""
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
    deps = {k: {_blocker_key(t, b) for b in t["blocked_by_open"]} for k, t in live.items()}
    unblocks = {k: sum(k in d for d in deps.values()) for k in live}
    pos = {k: i for i, k in enumerate(queued)}

    def rank(k):
        t = live[k]
        return (_rank(t), -unblocks[k], int(t.get("map_order") or 0), pos[k])

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


BRIEF_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "session-brief.md"


def brief(t, map_plain_words, run_folder, repo, branch):
    """The worker's prompt: templates/session-brief.md with each {name} filled from the ticket alone.
    A line whose value is empty (no paths, say) is dropped; a name the template uses and this does not fill is a bug."""
    num = int(t["num"])
    sbmap = f"python3 {SBMAP}"
    values = {
        "background": map_plain_words, "repo": repo, "branch": branch, "sbmap": sbmap, "map": t["map"],
        "num": str(num), "num3": f"{num:03d}", "title": t["title"], "why": t["why"], "question": t["question"],
        "out": t["out"] or "anything outside the ticket", "paths": ", ".join(t["paths"]),
        "done_when": t["done_when"], "checks": "\n".join(f"- {c}" for c in t["checks"]), "run_folder": str(run_folder),
    }
    text = re.sub(r"\A<!--.*?-->\n+", "", BRIEF_TEMPLATE.read_text(encoding="utf-8"), flags=re.S)
    out = []
    for line in text.split("\n"):
        names = re.findall(r"\{(\w+)\}", line)
        unknown = [n for n in names if n not in values]
        if unknown:
            raise KeyError(f"session-brief.md names {unknown[0]}, which the hub cannot fill")
        if any(not values[n] for n in names):
            continue
        out.append(re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], line))
    return "\n".join(out).rstrip("\n") + "\n"


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


def verdict(t, repo, base_sha, run=subprocess.run, report=None):
    """(passed, reason, sha): a trailered commit after base_sha and every check green. Files changed outside the
    ticket's paths are allowed (a change may need them) and named in the reason. A research ticket that made no
    commit passes on its written report alone (`report`, the worker's report file)."""
    num = int(t["num"])
    wanted = {f"Ticket: {t['map']}/{num}", f"Ticket: {t['map']}/{num:03d}"}
    r = run(["git", "-C", str(repo), "log", f"{base_sha}..HEAD", "--format=%H%x00%B%x01"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"cannot read the commits after {base_sha[:12]}: {(r.stderr or '').strip()[:200]}", None
    log = r.stdout
    entries = [e.strip("\n").split("\x00", 1) for e in log.split("\x01") if e.strip()]
    sha = next((s.strip() for s, body in entries if wanted & {l.strip() for l in body.splitlines()}), None)
    if not sha and t.get("type") == "research" and report and Path(report).is_file() and Path(report).stat().st_size:
        return True, "research: no commit needed, the findings are in the worker's report", None
    if not entries:
        return False, f"no commit after {base_sha[:9]}", None
    if not sha:
        return False, f"no commit carries the trailer Ticket: {t['map']}/{num:03d}", None
    outside = ""
    if t["paths"]:
        files = run(["git", "-C", str(repo), "diff", "--name-only", f"{base_sha}..{sha}"],
                    capture_output=True, text=True).stdout.split("\n")
        stray = [f for f in files if f and not _under(f, t["paths"]) and not _owned_test(f, t["paths"])]
        if stray:
            outside = "; it also changed files outside the ticket's list: " + ", ".join(stray[:10]) + (
                f" and {len(stray) - 10} more" if len(stray) > 10 else "")
    failed = _run_checks(t["checks"], repo, run)
    if not failed:
        return True, "commit and checks all good" + outside, sha
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
        again = _run_checks(t["checks"], clean, run)
    finally:
        _drop_clean_copy(repo, clean, run)
    if again:
        return False, again, sha
    shown = ", ".join(dirty[:5]) + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
    return True, ("commit and checks all good; the checks passed on a clean copy of the commit, because "
                  f"other uncommitted work in the shared folder breaks them there ({shown})" + outside), sha


def _run_checks(checks, cwd, run):
    """None when every check exits 0, else the first failure in words."""
    for cmd in checks:
        try:
            r = run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=CHECK_TIMEOUT)
        except subprocess.TimeoutExpired:
            return f"check timed out after 20 minutes: {cmd}"
        if r.returncode != 0:
            tail = "\n".join(((r.stdout or "") + (r.stderr or "")).splitlines()[-20:])
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
