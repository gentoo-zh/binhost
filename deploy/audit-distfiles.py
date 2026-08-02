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

import errno
import pathlib
import json
import re
import shutil
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

# Deleted files go into emirrordist's own recycle directory, the one
# distfiles-sync.sh already configures with --recycle-dir and --recycle-db.
#
# Not a separate bin of our own with an mtime-based sweep: rename() keeps the
# original mtime, and a distfile's mtime is when it was fetched, not when it was
# recycled. Anything older than the window was therefore swept in the same round
# it arrived -- the earlier attempt at this was an unlink with extra steps.
# emirrordist records the time in recycle.db instead, and adopts files it finds
# there that it did not put there itself, so one bin and one clock serve both.
RECYCLE = "/var/lib/emirrordist/recycle"

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

# 禁止镜像那一类另加一个绝对下限。只按比例，镜像小的时候一个文件就超过三分之一，
# 永远清不掉。一次真的加 RESTRICT 的批量是个位数——今晚三次分别是 2、7 个。
# 要拦的是「整棵树忽然都成了禁止镜像」，那种规模远在这之上。
MIN_RESTRICTED_TO_DOUBT = 20

# 累计窗口。跨轮记账放在这里而不是 orphans.json，因为它记的是「已经做过什么」
# 而不是「打算做什么」。
LEDGER = "/var/lib/emirrordist/reaped.json"
WINDOW_HOURS = 24

MARKERS = {"layout.conf", "README.txt"}


def recent_deletions(add_count, now=None):
    """记下这一轮清掉多少，返回窗口内的累计值。"""
    now = int(time.time()) if now is None else now
    f = pathlib.Path(LEDGER)
    try:
        rows = json.loads(f.read_text())
    except (OSError, ValueError):
        rows = []
    rows = [r for r in rows if now - r[0] < WINDOW_HOURS * 3600]
    if add_count:
        rows.append([now, add_count])
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rows))
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法写入 {f}: {e}", file=sys.stderr)
    return sum(n for _, n in rows)


def recycle(path):
    """Move one file into the recycle directory. True when it went.

    A move, not a copy: the file leaves the served tree in one step, and on the
    same filesystem it costs nothing. Failing to recycle means not deleting --
    an undeletable orphan costs disk, an unrecoverable one costs the file.
    """
    bin_ = pathlib.Path(RECYCLE)
    try:
        bin_.mkdir(parents=True, exist_ok=True)
        dst = bin_ / path.name
        # 不覆盖同名的那一份。rename 在 POSIX 上直接盖掉目标，而桶里那一份是
        # 更早回收的，也就是更可能有人要回头找的那一份。
        n = 0
        while dst.exists():
            n += 1
            dst = bin_ / f"{path.name}.{n}"
        try:
            path.rename(dst)
        except OSError as e:
            # 跨文件系统时 rename 报 EXDEV。搬不动就复制再删，别因为布局
            # 换了就退回不可恢复的删除。
            if e.errno != errno.EXDEV:
                raise
            shutil.copy2(path, dst)
            path.unlink()
        return True
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法回收 {path.name}: {e}", file=sys.stderr)
        return False


def reap(orphan, paths, grace=None, budget=None):
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
    failed = []
    held = 0
    for f in orphan:
        first = seen.setdefault(f, now)
        if now - first < grace:
            continue
        path = paths.get(f)
        if path is None:
            continue
        if budget is not None and len(deleted) >= budget:
            held += 1
            continue
        if recycle(path):
            deleted.append(f)
        else:
            failed.append(f)
    if held:
        print(f"!! 达到额度上限，本轮保留 {held} 个未清理", file=sys.stderr)
    for f in deleted:
        seen.pop(f, None)

    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(seen, indent=1, sort_keys=True))
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法写入 {state}: {e}", file=sys.stderr)
        failed.append(str(state))
    return deleted, failed


def main(overlay, dest):
    overlay, dest = pathlib.Path(overlay), pathlib.Path(dest)
    if not (overlay / "profiles" / "repo_name").exists():
        sys.exit(f"不是 ebuild 仓库：{overlay}")

    users = scan(overlay)
    paths = {p.name: p for p in dest.rglob("*") if p.is_file() and p.name not in MARKERS}
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
    orphan = sorted(have - set(users))

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

    # 额度在删除之前算。原来先删再核对累计值，于是这道闸门只能在文件已经不存在
    # 之后报错：连续两轮各删三成，第二轮报了超限，而那一批已经没了。
    spent = recent_deletions(0)
    budget = max(0, int(len(have) * MAX_REAP_SHARE) - spent)
    deleted, failed = ([], []) if refused else reap(orphan, paths, budget=budget)

    # RESTRICT=mirror 的文件不等宽限期。孤儿要等，是因为一次 bump 会让旧文件
    # 短暂无人引用，等一周就能看出是不是误判；而「所有引用方都禁止镜像」是上游
    # 明确的声明，不是过渡状态，多留一轮就是多发一轮不该发的文件。
    #
    # 仍然走回收桶：判断错了还取得回来，和孤儿同一个桶、同一个时钟。
    # 比例闸和孤儿那道对称，但独立：这一类不进跨轮帐本。帐本记的是孤儿清理，
    # 把这一类算进去会让整轮在文件已经删掉之后被标成拒绝清理，而 refused
    # 的含义是一个都没碰。
    restricted, restricted_failed = [], []
    too_many = (len(extra) > MIN_RESTRICTED_TO_DOUBT
                and len(extra) > len(have) * MAX_REAP_SHARE)
    if too_many:
        print(f"!! 本轮 {len(extra)}/{len(have)} 个文件被标为禁止镜像，"
              f"超过 {MAX_REAP_SHARE:.0%}，没有清理", file=sys.stderr)
    if not refused and not too_many:
        for f in extra:
            path = paths.get(f)
            if path is None:
                continue
            (restricted if recycle(path) else restricted_failed).append(f)

    # 按轮计的上限拦不住连着来的几轮：每轮 30% 两轮就是一半个镜像，一次都不会
    # 被拒绝。所以再核对最近这段时间总共清掉了多少。
    recent = recent_deletions(len(deleted))
    if not refused and budget == 0 and orphan:
        refused = (f"最近 {WINDOW_HOURS} 小时累计清理 {spent} 个，"
                   f"已达镜像的 {MAX_REAP_SHARE:.0%}，本轮未清理")

    print(f"overlay 引用 {len(users)}，其中可镜像 {len(mirrorable)}，"
          f"不可镜像 {len(never)}，无法取得 {len(unfetchable)}")
    print(f"镜像上 {len(have)}，缺 {len(missing)}，禁止镜像 {len(extra)}，"
          f"已无人引用 {len(orphan)}，本轮清理 {len(deleted) + len(restricted)}"
          f"（其中禁止镜像 {len(restricted)}）")
    if restricted_failed:
        print(f"!! {len(restricted_failed)} 个禁止镜像的文件没能回收，还在对外发",
              file=sys.stderr)
    if failed:
        # 回收不成等于清理永远失效，而原来它只印一行 stderr、退出码不变，
        # daily.sh 于是每小时报一次成功。
        print(f"!! {len(failed)} 个没能回收，本轮清理没有完成", file=sys.stderr)
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
    # extra 不再让这一轮失败：它已经被清掉了，报错等于每清一次就告警一次。
    # 清不掉才是要人看的，那是 restricted_failed。
    return 1 if (missing or refused or failed or restricted_failed or too_many) else 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "/var/lib/binhost-overlay",
        sys.argv[2] if len(sys.argv) > 2 else "/srv/pub/distfiles"))
