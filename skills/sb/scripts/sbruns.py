"""Every run the hub knows of, for History: the queue's finished ticket items plus the vault's run folders
(wayfinder/<project>/runs/<folder>/<NNN>.md, <NNN>.log, <NNN>-media/). sbhub.py serves the answers at api/runs and
api/run; this file only reads, it writes nothing."""
import json
import re
from pathlib import Path
from urllib.parse import quote

MEDIA_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm"}
MEDIA_MAX = 6
MEDIA_BYTES = 8 << 20
LOG_SHOWN = 256 << 10  # the end of a log that api/run carries
OUTCOMES = {"done": "done", "failed": "failed", "skipped": "skipped"}


def plain_reason(note, outcome):
    """A run's reason in plain words, as the board says it (board.ts plainReason)."""
    first = next((l.strip() for l in (note or "").splitlines() if l.strip()), "")
    if not first:
        return "" if outcome == "done" else ("skipped, no reason recorded" if outcome == "skipped" else "no reason recorded")
    if first.startswith("no commit after "):
        return "ended without a commit"
    m = re.fullmatch(r"check failed: (.+)", first)
    if m:
        cmd = m[1].strip()
        if cmd.startswith(("/", "~")):
            return "the {} check failed".format(re.sub(r"[-_]+", " ", re.sub(r"\.[a-z]+$", "", cmd.split()[0].split("/")[-1], flags=re.I)))
        return cmd + " failed"
    m = re.fullmatch(r"commits since the start touch files outside the ticket's paths: (.+)", first)
    if m:
        n = len([x for x in m[1].split(",") if x.strip()])
        return "it changed a file outside its list" if n == 1 else "it changed {} files outside its list".format(n)
    m = re.fullmatch(r"could not land: .*conflict.* in (\S+)", first)
    if m:
        return "its commits conflict with the branch in " + m[1].split("/")[-1]
    m = re.fullmatch(r"blocked: after (.+)", first)
    if m:
        return "waited on “{}”".format(m[1])
    if first.startswith("claimed: "):
        return "someone else had claimed it"
    if first.startswith("no longer open"):
        return "its ticket was closed after it was queued"
    return first if len(first) <= 140 else first[:139] + "…"


def media_in(folder, num):
    d = Path(folder) / "{}-media".format(int(num))
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.suffix.lower() in MEDIA_TYPES and p.is_file() and p.stat().st_size <= MEDIA_BYTES)[:MEDIA_MAX]


def _uri(path):
    """The obsidian://open?path= link of a file that exists, else None (the TypeScript server renames it by vault)."""
    try:
        return "obsidian://open?path=" + quote(str(Path(path).resolve(strict=True)), safe="") if Path(path).exists() else None
    except OSError:
        return None


def _ticket_file(vault, map_, num):
    issues = Path(vault) / "wayfinder" / map_ / "issues"
    found = sorted(p for d in (issues, issues / "done") for p in d.glob("{:03d}[ -]*.md".format(num)))
    return found[0] if found else None


def _links(vault, key, folder, log):
    m = re.fullmatch(r"(.+)#(\d+)", key)
    ticket = _ticket_file(vault, m[1], int(m[2])) if m else None
    num = int(m[2]) if m else 0
    return {"ticket": _uri(ticket) if ticket else None,
            "map": _uri(ticket.parent.parent / "map.md") if ticket and ticket.parent.name == "issues"
            else (_uri(ticket.parent.parent.parent / "map.md") if ticket else None),
            "board": None,
            "report": _uri(Path(folder) / "{}.md".format(num)) if folder and m else None,
            "log": _uri(log) if log else None}


def _hub_checks(text):
    """The checks the hub appended to a report (`## Hub checks`): [{cmd, code, secs, tail}]."""
    m = re.search(r"^## Hub checks[^\n]*\n(.*?)(?=^## |\Z)", text or "", re.M | re.S)
    out = []
    if not m:
        return out
    for c in re.finditer(r"^- `(.+?)`: (timed out|exit (-?\d+)), ([\d.]+) s\n(?:\n  ```\n(.*?)\n  ```)?", m[1], re.M | re.S):
        tail = "\n".join(l[2:] if l.startswith("  ") else l for l in (c[5] or "").splitlines())
        out.append({"cmd": c[1], "code": None if c[3] is None else int(c[3]), "secs": float(c[4]), "tail": tail})
    return out


def _from_report(text):
    """(title, commit, outcome, reason) a run's report says: its heading, `Commit: sha`, and the hub's verdict."""
    title = ""
    h = re.search(r"^#\s+(?:\d+\s*[:.–-]\s*)?(.+?)\s*$", text or "", re.M)
    if h:
        title = h[1]
    commit = re.search(r"^Commit:\s*`?([0-9a-f]{7,40})", text or "", re.M | re.I)
    verdict = re.search(r"^Checked by the sb hub at [\d: -]+: (passed|failed: .+?)(?:, commit ([0-9a-f]+))?\.\s*$", text or "", re.M)
    outcome, reason, sha = "unknown", "", commit[1] if commit else None
    if verdict:
        outcome = "done" if verdict[1] == "passed" else "failed"
        reason = "" if outcome == "done" else verdict[1][len("failed: "):]
        sha = sha or verdict[2]
    return title, sha, outcome, reason


def _vault_runs(vault):
    """{key: run-ish dict} for every NNN.md or NNN.log in wayfinder/<project>/runs/<folder>/."""
    out = {}
    for folder in sorted(Path(vault).glob("wayfinder/*/runs/*")):
        if not folder.is_dir():
            continue
        project = folder.parent.parent.name
        effort = re.sub(r"^\d{4}-\d\d-\d\d-", "", folder.name)
        nums = {int(m[1]) for p in folder.iterdir() if (m := re.fullmatch(r"(\d+)\.(?:md|log)", p.name))}
        for n in nums:
            md, log = folder / "{}.md".format(n), folder / "{}.log".format(n)
            try:
                text = md.read_text(encoding="utf-8", errors="replace") if md.is_file() else ""
                end = (md if md.is_file() else log).stat().st_mtime
            except OSError:
                continue
            title, sha, outcome, reason = _from_report(text)
            key = "{}/{}#{}".format(project, effort, n)
            out[key] = {"key": key, "folder": str(folder), "num": n, "title": title, "commit": sha, "outcome": outcome,
                        "reason": reason, "ended": end, "log": str(log) if log.is_file() else None, "md": text}
    return out


def _run(vault, key, item, vr):
    """One Run of the answer, from the queue item (its fields win) and the vault's folder (its fills the gaps)."""
    item, vr = item or {}, vr or {}
    m = re.fullmatch(r"(.+)#(\d+)", key)
    map_, num = (m[1], int(m[2])) if m else ("", 0)
    folder = item.get("run") or vr.get("folder")
    log = item.get("log") or vr.get("log")
    state = item.get("state")
    outcome = OUTCOMES.get(state) or vr.get("outcome") or "unknown"
    note = item.get("note") if item else vr.get("reason", "")
    started, ended = item.get("started"), item.get("ended") or vr.get("ended")
    return {"key": key, "title": item.get("title") or vr.get("title") or "{} ticket {}".format(map_, num),
            "project": map_.split("/")[0] if "/" in map_ else map_.split("-")[0], "map": map_,
            "outcome": outcome, "reason": plain_reason(note, outcome) if outcome in ("failed", "skipped") or (outcome == "unknown" and note) else "",
            "account": item.get("agent"), "model": item.get("model"), "started": started, "ended": ended,
            "commit": item.get("commit") or vr.get("commit"), "tries": item.get("tries") or (1 if vr else 0),
            "pictures": item.get("media") or (media_in(folder, num) if folder and num else []),
            "links": _links(vault, key, folder, log)}


def _all(vault, items):
    queue = {i["key"]: i for i in items if i.get("kind") == "ticket" and i.get("state") in OUTCOMES}
    # a key can be in the list and in the log of cleared items: the newest end wins
    for i in items:
        k = i.get("key")
        if k in queue and (i.get("ended") or 0) > (queue[k].get("ended") or 0):
            queue[k] = i
    vr = _vault_runs(vault)
    keys = set(queue) | set(vr)
    runs = [_run(vault, k, queue.get(k), vr.get(k)) for k in keys]
    return sorted(runs, key=lambda r: (-(r["ended"] or 0), r["key"]))


def list_runs(vault, items, since=0, offset=0, limit=100):
    """{runs, total, offset, limit}: runs that ended after `since`, newest first, one page."""
    limit = max(1, min(int(limit), 500))
    runs = [r for r in _all(vault, items) if (r["ended"] or 0) >= since]
    return {"runs": runs[max(0, int(offset)):max(0, int(offset)) + limit], "total": len(runs),
            "offset": max(0, int(offset)), "limit": limit}


def readable(text):
    """A worker's stream-json log as lines a person reads; a line that is not JSON stays as it is."""
    out = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        if not isinstance(d, dict):
            out.append(line)
        elif d.get("type") == "assistant":
            for b in (d.get("message") or {}).get("content") or []:
                if b.get("type") == "text" and b.get("text", "").strip():
                    out.append(b["text"].strip())
                elif b.get("type") == "tool_use":
                    arg = next((str(v) for v in (b.get("input") or {}).values() if isinstance(v, (str, int))), "")
                    out.append("→ {} {}".format(b.get("name", "tool"), arg.splitlines()[0][:160] if arg else "").rstrip())
        elif d.get("type") == "result" and isinstance(d.get("result"), str):
            out.append("result: " + d["result"].strip())
        elif isinstance(d.get("error"), str):
            out.append("error: " + d["error"])
    return "\n".join(out)


def find(vault, items, key):
    """(Run, folder, report text, log path) of one run, or None."""
    for r in _all(vault, items):
        if r["key"] == key:
            item = next((i for i in items if i.get("key") == key and i.get("kind") == "ticket"), None)
            vr = _vault_runs(vault).get(key) if not (item and item.get("run")) else None
            folder = (item or {}).get("run") or (vr or {}).get("folder")
            log = (item or {}).get("log") or (vr or {}).get("log")
            return r, folder, log, item
    return None


def detail(vault, items, key):
    """{run, checks, report, log}: what the run viewer shows. KeyError for a run nobody knows."""
    got = find(vault, items, key)
    if got is None:
        raise KeyError(key)
    run, folder, log, item = got
    num = int(key.rsplit("#", 1)[-1])
    report = None
    if folder and (Path(folder) / "{}.md".format(num)).is_file():
        report = (Path(folder) / "{}.md".format(num)).read_text(encoding="utf-8", errors="replace")
    checks = (item or {}).get("checks") or _hub_checks(report)
    text = None
    if log and Path(log).is_file():
        with open(log, "rb") as f:
            f.seek(0, 2)
            at = max(0, f.tell() - LOG_SHOWN)
            f.seek(at)
            data = f.read().decode("utf-8", "replace")
        text = readable(data[data.find("\n") + 1:] if at else data)
    return {"run": run, "checks": checks, "report": report, "log": text}


def media_file(vault, items, key, name):
    """The path of one of a run's pictures; KeyError for a name it does not have or one with a path in it."""
    got = find(vault, items, key)
    if got is None or not name or any(c in name for c in ("/", "\\", "..")):
        raise KeyError(name)
    run, folder, _, _ = got
    if not folder or name not in media_in(folder, int(key.rsplit("#", 1)[-1])):
        raise KeyError(name)
    d = (Path(folder) / "{}-media".format(int(key.rsplit("#", 1)[-1]))).resolve()
    f = (d / name).resolve()
    if f.parent != d or not f.is_file():
        raise KeyError(name)
    return f
