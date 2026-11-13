"""The hub queue's rules as pure functions: classify, order, move, brief, verdict.

Tickets are the dicts `sbmap tickets --json` prints. Nothing here reads the vault or the hub's state.
"""
import heapq
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


def brief(t, map_plain_words, run_folder, repo, branch):
    """The worker's prompt, from the ticket alone (templates/session-brief.md, minus what a ticket cannot fill)."""
    num = int(t["num"])
    sbmap = f"python3 {SBMAP}"
    lines = [
        f"Background: {map_plain_words}",
        "",
        f"Implement one ticket, alone, in {repo} on {branch}, unattended.",
        f"Read the ticket first: {sbmap} show {t['map']} {num:03d}",
        "",
        f"{t['title']}.",
        f"Why: {t['why']}",
        f"Do: {t['question']}",
        f"Leave alone: {t['out'] or 'anything outside the ticket'}",
    ]
    if t["paths"]:
        lines.append("Files you own: " + ", ".join(t["paths"]) + ". Touch no other file.")
    lines += ["", f"Done when: {t['done_when']}", "These commands must all exit 0 when you finish:"]
    lines += [f"- {c}" for c in t["checks"]]
    lines += [
        "",
        "- Commit once by pathspec, with this as the last line of the message:",
        f"  Ticket: {t['map']}/{num:03d}",
        "  Do not resolve the ticket; the operator does.",
        f"- Write every ruling you make on the ticket: {sbmap} comment {t['map']} {num:03d} "
        "--text \"R: the ruling, cost if wrong: what it costs\"",
        f"- Write your report to {run_folder}/{num}.md: the commit, each check with its counts, "
        "what you could not verify, rulings, files. Say nothing along the way. "
        "Your last message, two lines: what works now and how to see it; the report's path.",
    ]
    return "\n".join(lines) + "\n"


def _under(f, paths):
    return any(f == p.rstrip("/") or f.startswith(p.rstrip("/") + "/") for p in paths)


def verdict(t, repo, base_sha, run=subprocess.run):
    """(passed, reason, sha): a trailered commit after base_sha, every file changed since base_sha up to it
    inside the ticket's paths (trailered or not), every check green."""
    num = int(t["num"])
    wanted = {f"Ticket: {t['map']}/{num}", f"Ticket: {t['map']}/{num:03d}"}
    r = run(["git", "-C", str(repo), "log", f"{base_sha}..HEAD", "--format=%H%x00%B%x01"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"cannot read the commits after {base_sha[:12]}: {(r.stderr or '').strip()[:200]}", None
    log = r.stdout
    entries = [e.strip("\n").split("\x00", 1) for e in log.split("\x01") if e.strip()]
    if not entries:
        return False, f"no commit after {base_sha[:9]}", None
    sha = next((s.strip() for s, body in entries if wanted & {l.strip() for l in body.splitlines()}), None)
    if not sha:
        return False, f"no commit carries the trailer Ticket: {t['map']}/{num:03d}", None
    if t["paths"]:
        files = run(["git", "-C", str(repo), "diff", "--name-only", f"{base_sha}..{sha}"],
                    capture_output=True, text=True).stdout.split("\n")
        stray = [f for f in files if f and not _under(f, t["paths"])]
        if stray:
            return False, "commits since the start touch files outside the ticket's paths: " + ", ".join(stray), sha
    for cmd in t["checks"]:
        try:
            r = run(cmd, shell=True, cwd=str(repo), capture_output=True, text=True, timeout=CHECK_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, f"check timed out after 20 minutes: {cmd}", sha
        if r.returncode != 0:
            tail = "\n".join(((r.stdout or "") + (r.stderr or "")).splitlines()[-20:])
            return False, f"check failed: {cmd}\n{tail}", sha
    return True, "commit, paths and checks all good", sha
