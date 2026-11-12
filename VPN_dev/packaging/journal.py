"""Keeps the automatic build log inside the PRIVATE build journal (private/BUILD-JOURNAL.md) up to date. Called by build.ps1:

  python packaging/journal.py start  <version> "<pytest summary>"           -> prints the new build id (B<n>)
  python packaging/journal.py finish <build id> <installer path> <signed 0|1>
  python packaging/journal.py fail   <version> "<step>" "<detail>"

Rows go between the BUILD-LOG markers, newest last. The journal is private (VPN_dev/private/, git-ignored)."""
import datetime
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Maintainer-only: the journal lives in the git-ignored private/ folder and is never published or shipped.
# Clones and CI don't have it, and then every command is a quiet no-op.
JOURNAL = os.environ.get("NOBAD_JOURNAL") or os.path.join(ROOT, "private", "BUILD-JOURNAL.md")
START, END = "<!-- BUILD-LOG:START -->", "<!-- BUILD-LOG:END -->"
ROW = re.compile(r"\| B\d+ \|")          # a build row (the header starts with '| Build', so match the id exactly)
HEADER = "| Build | Date (local) | Version | Commit | Tests | Result | Installer | SHA-256 |\n|---|---|---|---|---|---|---|---|"


def _git():
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return (sha or "?") + ("+changes" if dirty else "")
    except OSError:
        return "?"


def _read():
    with open(JOURNAL, encoding="utf-8") as f:
        s = f.read()
    if START not in s or END not in s:
        raise SystemExit("BUILD-JOURNAL.md is missing the BUILD-LOG markers")
    head, rest = s.split(START, 1)
    body, tail = rest.split(END, 1)
    rows = [ln for ln in body.strip().splitlines() if ROW.match(ln)]
    return head, rows, tail


def _write(head, rows, tail):
    body = "\n" + HEADER + "\n" + "\n".join(rows) + "\n"
    tmp = JOURNAL + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + START + body + END + tail)
    os.replace(tmp, JOURNAL)


def _cell(s):
    return " ".join(str(s).replace("|", "/").split())[:120]


def _next_id(rows):
    nums = [int(m.group(1)) for r in rows for m in [re.match(r"\| B(\d+) ", r)] if m]
    return f"B{(max(nums) + 1) if nums else 1}"


def start(version, tests):
    head, rows, tail = _read()
    bid = _next_id(rows)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows.append(f"| {bid} | {now} | {_cell(version)} | {_git()} | {_cell(tests)} | packaging | | pending |")
    _write(head, rows, tail)
    print(bid)


def finish(bid, setup, signed):
    head, rows, tail = _read()
    with open(setup, "rb") as f:
        data = f.read()
    sha, size = hashlib.sha256(data).hexdigest(), f"{len(data) / 1e6:.1f} MB"
    result = "built, signed" if signed == "1" else "built, unsigned"
    for i, r in enumerate(rows):
        if r.startswith(f"| {bid} |"):
            cells = [c.strip() for c in r.strip("|").split("|")]
            cells[5], cells[6], cells[7] = result, size, f"`{sha}`"
            rows[i] = "| " + " | ".join(cells) + " |"
            break
    else:
        raise SystemExit(f"build {bid} not found in the journal")
    _write(head, rows, tail)


def fail(version, step, detail):
    head, rows, tail = _read()
    bid = _next_id(rows)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows.append(f"| {bid} | {now} | {_cell(version)} | {_git()} | {_cell(detail)} | FAILED at {_cell(step)} | | |")
    _write(head, rows, tail)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if not os.path.exists(JOURNAL):
        print("none")            # no private journal here (clone/CI): nothing to record
        sys.exit(0)
    {"start": start, "finish": finish, "fail": fail}[cmd](*args)
