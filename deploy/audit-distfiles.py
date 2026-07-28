#!/usr/bin/env python3
"""Reconcile the distfiles on the mirror against the overlay, item by item.

Two directions:
  missing  referenced by the overlay, mirrorable, and not here
  extra    every referrer has RESTRICT=mirror, yet the file is on the mirror

RESTRICT=mirror is decided per file rather than per package: one crate can be
referenced by both a restricted and an unrestricted package, and a single
referrer that allows mirroring makes the file mirrorable. That is what
emirrordist does; this checks it independently rather than repeating its
logic.

A non-zero exit means the two disagree; daily.sh turns that into an alert.
"""

import pathlib
import json
import re
import sys
import time


def scan(overlay):
    """filename -> [(package, whether its own ebuild has RESTRICT=mirror)]

    Attributed per file rather than or-ed across the whole package directory.
    Two versions of one package can carry different RESTRICT:
    dev-java/oraclejdk-bin 21.0.1 is bindist mirror while 8.391 is fetch. Or-ing
    across the directory lets the two contaminate each other, one taken for
    unmirrorable and the other for unfetchable, and neither is right.

    The Manifest does not say which DIST line belongs to which ebuild, so the
    version is matched against the filename -- nearly every source file in the
    overlay carries its version. With no match it falls back to the directory-
    wide or: better to keep the old behaviour than to guess a file past an
    upstream that forbids mirroring.
    """
    users = {}
    for man in overlay.glob("*/*/Manifest"):
        d = man.parent
        ebuilds = list(d.glob("*.ebuild"))
        if not ebuilds:
            continue
        pn = d.name
        by_version = {}
        for e in ebuilds:
            ver = e.name[len(pn) + 1:-len(".ebuild")]
            by_version[ver] = bool(
                re.search(r"RESTRICT=.*\bmirror\b", e.read_text(errors="replace")))
        fallback = any(by_version.values())

        for line in man.read_text(errors="replace").splitlines():
            if not line.startswith("DIST "):
                continue
            name = line.split()[1]
            # Longest version wins: with 1.2 and 1.2.3 both present, do not
            # attribute the 1.2.3 file to 1.2.
            hit = [v for v in by_version if v in name]
            restricted = by_version[max(hit, key=len)] if hit else fallback
            users.setdefault(name, []).append(
                (str(d.relative_to(overlay)), restricted))
    return users


GRACE_SECONDS = 7 * 24 * 3600
STATE = "/var/lib/emirrordist/orphans.json"

# Deleted files go here first, the same idea as emirrordist's --recycle-dir and
# the same two weeks. A distfile cannot be fetched again once upstream drops the
# release, so the grace period alone is not a safety net -- it only delays a
# decision that is still final.
RECYCLE = "/var/lib/emirrordist/audit-recycle"
RECYCLE_SECONDS = 14 * 24 * 3600

# The largest share of the mirror one round may retire. Reaping is driven by
# what the overlay references, so anything that makes the overlay read as empty
# or half-read -- a failed fetch, an interrupted reset, a wrong path -- turns
# every file on the mirror into an orphan at once. Below the limit the round
# proceeds; above it nothing is touched and the round fails so someone looks.
#
# A third, not a tenth. A real mass treeclean reaches double digits on its own:
# the overlay dropped 30 packages on 2026-07-28 and the mirror went to 138
# unreferenced files out of 1224, which is 11%. A limit that a legitimate day
# trips is a limit people learn to wave through. What it has to catch is the
# tree that read as empty or half-empty, and that lands far above a third.
MAX_REAP_SHARE = 1 / 3

MARKERS = {"layout.conf", "README.txt"}


def recycle(path):
    """Move one file into the recycle directory. True when it went.

    A move, not a copy: the file leaves the served tree in one step, and on the
    same filesystem it costs nothing. Failing to recycle means not deleting --
    an undeletable orphan costs disk, an unrecoverable one costs the file.
    """
    bin_ = pathlib.Path(RECYCLE)
    try:
        bin_.mkdir(parents=True, exist_ok=True)
        path.rename(bin_ / path.name)
        return True
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法回收 {path.name}: {e}", file=sys.stderr)
        return False


def sweep_recycle(now=None):
    """Drop recycled files older than the recycle window. Returns how many."""
    bin_ = pathlib.Path(RECYCLE)
    if not bin_.is_dir():
        return 0
    now = int(time.time()) if now is None else now
    gone = 0
    for p in bin_.iterdir():
        try:
            if p.is_file() and now - int(p.stat().st_mtime) >= RECYCLE_SECONDS:
                p.unlink()
                gone += 1
        except OSError:
            continue
    return gone


def reap(orphan, paths, grace=None):
    """Delete orphans past the grace period; return what this round removed.

    After a bump nothing references the old source file any more, and
    emirrordist --delete works from the list it fetched this round, so it never
    reaches them. Keeping them only costs disk.

    Not deleted on sight: the time it was first seen is recorded and the file
    goes only once the grace period has passed. A wrong call still leaves a week
    to notice, the same idea as emirrordist's own --deletion-delay.

    Takes the paths the caller already listed rather than searching by name.
    rglob treats its argument as a pattern, so a filename holding [ ] or ?
    matched something else or nothing at all -- one deletes the wrong file, the
    other leaves the orphan there for good. No distfile carries those characters
    today, which is exactly why it would have gone unnoticed.
    """
    # Resolved here rather than as a default argument: a default binds the
    # module constant once at import, so anything that overrides it afterwards
    # -- a test, an operator setting it before calling -- is silently ignored.
    grace = GRACE_SECONDS if grace is None else grace

    state = pathlib.Path(STATE)
    try:
        seen = json.loads(state.read_text())
    except (OSError, ValueError):
        seen = {}

    now = int(time.time())
    seen = {f: t for f, t in seen.items() if f in orphan}   # referenced again, so forget it
    deleted = []
    for f in orphan:
        first = seen.setdefault(f, now)
        if now - first < grace:
            continue
        path = paths.get(f)
        if path is None:
            continue
        if recycle(path):
            deleted.append(f)
    for f in deleted:
        seen.pop(f, None)

    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(seen, indent=1, sort_keys=True))
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法写入 {state}: {e}")
    return deleted


def main(overlay, dest):
    overlay, dest = pathlib.Path(overlay), pathlib.Path(dest)
    if not (overlay / "profiles" / "repo_name").exists():
        sys.exit(f"不是 ebuild 仓库：{overlay}")

    users = scan(overlay)
    paths = {p.name: p for p in dest.rglob("*") if p.is_file() and p.name != "layout.conf"}
    have = set(paths)

    # A fetch-restricted package has no URL in SRC_URI at all, so nobody can
    # mirror it and it does not count as missing.
    unfetchable = set()
    for man in overlay.glob("*/*/Manifest"):
        d = man.parent
        if not any(re.search(r'RESTRICT=.*\bfetch\b', e.read_text(errors="replace"))
                   for e in d.glob("*.ebuild")):
            continue
        for line in man.read_text(errors="replace").splitlines():
            if line.startswith("DIST "):
                unfetchable.add(line.split()[1])

    mirrorable = {f for f, us in users.items() if any(not r for _, r in us)} - unfetchable
    never = {f for f, us in users.items() if us and all(r for _, r in us)}

    missing = sorted(mirrorable - have)
    extra = sorted(never & have)
    # No longer referenced by the overlay at all. Old source files after a bump
    # are this, and emirrordist --delete works from the list it fetched this
    # round so it never reaches them.
    #
    # The layout marker is not a distfile: layout.conf tells portage this tree
    # uses two levels of hashing rather than a flat directory, and the official
    # distfiles root carries the same file. Without it clients fetch from the
    # wrong path.
    orphan = sorted(have - set(users) - MARKERS)

    # Refuse the round rather than act on an overlay that reads as empty or
    # half-read. An overlay with no Manifests at all passes the repo_name check
    # above and makes every file on the mirror an orphan; so does a git reset
    # that stopped halfway. Both are indistinguishable here from a legitimate
    # mass treeclean, so the call is left to a person.
    refused = ""
    if not users:
        refused = f"overlay 一个 Manifest 都没有读到，{overlay} 不完整"
    elif have and len(orphan) > len(have) * MAX_REAP_SHARE:
        refused = (f"本轮 {len(orphan)}/{len(have)} 个文件无人引用，"
                   f"超过 {MAX_REAP_SHARE:.0%}")

    deleted = [] if refused else reap(orphan, paths)
    swept = sweep_recycle()

    print(f"overlay 引用 {len(users)}，其中可镜像 {len(mirrorable)}，"
          f"不可镜像 {len(never)}，无法取得 {len(unfetchable)}")
    print(f"镜像上 {len(have)}，缺 {len(missing)}，多 {len(extra)}，"
          f"已无人引用 {len(orphan)}，本轮清理 {len(deleted)}")
    if swept:
        print(f"回收目录清掉 {swept} 个过期文件")
    if refused:
        print(f"!! 拒绝清理：{refused}", file=sys.stderr)

    for f in missing[:20]:
        print(f"  缺 {f}  <- {[p for p, _ in users[f]]}")
    for f in extra[:20]:
        print(f"  多 {f}  <- {[p for p, _ in users[f]]}（所有引用方都 RESTRICT=mirror）")
    for f in deleted[:20]:
        print(f"  清理 {f}")

    # Unreferenced files are handled by reap on its grace period. They are what
    # a bump normally leaves behind, so they are not a failure. Alerting hourly
    # about the same set of files only teaches people to ignore alerts.
    #
    # A refused round is a failure: it means the input could not be trusted, and
    # that is exactly the case nobody would otherwise hear about.
    return 1 if (missing or extra or refused) else 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "/var/lib/binhost-overlay",
        sys.argv[2] if len(sys.argv) > 2 else "/srv/pub/distfiles"))
