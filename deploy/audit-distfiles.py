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

MARKERS = {"layout.conf", "README.txt"}


def reap(orphan, paths, grace=GRACE_SECONDS):
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
        path.unlink(missing_ok=True)
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
    deleted = reap(orphan, paths)

    print(f"overlay 引用 {len(users)}，其中可镜像 {len(mirrorable)}，"
          f"不可镜像 {len(never)}，无法取得 {len(unfetchable)}")
    print(f"镜像上 {len(have)}，缺 {len(missing)}，多 {len(extra)}，"
          f"已无人引用 {len(orphan)}，本轮清理 {len(deleted)}")

    for f in missing[:20]:
        print(f"  缺 {f}  <- {[p for p, _ in users[f]]}")
    for f in extra[:20]:
        print(f"  多 {f}  <- {[p for p, _ in users[f]]}（所有引用方都 RESTRICT=mirror）")
    for f in deleted[:20]:
        print(f"  清理 {f}")

    # Unreferenced files are handled by reap on its grace period. They are what
    # a bump normally leaves behind, so they are not a failure. Alerting hourly
    # about the same set of files only teaches people to ignore alerts.
    return 1 if (missing or extra) else 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "/var/lib/binhost-overlay",
        sys.argv[2] if len(sys.argv) > 2 else "/srv/pub/distfiles"))
