#!/usr/bin/env python3

import errno
import os
import pathlib
import json
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import restrict_tokens                        # noqa: E402


def scan(overlay):
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
            by_version[ver] = "mirror" in restrict_tokens(
                e.read_text(errors="replace"))
        fallback = any(by_version.values())

        for line in man.read_text(errors="replace").splitlines():
            if not line.startswith("DIST "):
                continue
            name = line.split()[1]
            hit = [v for v in by_version if v in name]
            restricted = by_version[max(hit, key=len)] if hit else fallback
            users.setdefault(name, []).append(
                (str(d.relative_to(overlay)), restricted))
    return users


GRACE_SECONDS = 7 * 24 * 3600
STATE = "/var/lib/emirrordist/orphans.json"

RECYCLE = "/var/lib/emirrordist/recycle"

MAX_REAP_SHARE = 1 / 3

MIN_RESTRICTED_TO_DOUBT = 20

LEDGER = "/var/lib/emirrordist/reaped.json"
WINDOW_HOURS = 24

MARKERS = {"layout.conf", "README.txt"}


class LedgerError(Exception):
    pass


def recent_deletions(add_count, now=None):
    now = int(time.time()) if now is None else now
    f = pathlib.Path(LEDGER)
    try:
        rows = json.loads(f.read_text())
    except FileNotFoundError:
        rows = []
    except (OSError, ValueError) as e:
        raise LedgerError(f"{f} 无法读取：{e}") from e
    if not isinstance(rows, list):
        raise LedgerError(f"{f} 内容不是清单")
    rows = [r for r in rows if now - r[0] < WINDOW_HOURS * 3600]
    if add_count:
        rows.append([now, add_count])
    tmp = f.with_suffix(".json.new")
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(rows))
        os.replace(tmp, f)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise LedgerError(f"{f} 无法写入：{e}") from e
    return sum(n for _, n in rows)


def recycle(path):
    bin_ = pathlib.Path(RECYCLE)
    try:
        bin_.mkdir(parents=True, exist_ok=True)
        dst = bin_ / path.name
        n = 0
        while dst.exists():
            n += 1
            dst = bin_ / f"{path.name}.{n}"
        try:
            path.rename(dst)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            shutil.copy2(path, dst)
            path.unlink()
        return True
    except OSError as e:                                   # noqa: BLE001
        print(f"!! 无法回收 {path.name}: {e}", file=sys.stderr)
        return False


def reap(orphan, paths, grace=None, budget=None):
    grace = GRACE_SECONDS if grace is None else grace

    state = pathlib.Path(STATE)
    try:
        seen = json.loads(state.read_text())
    except (OSError, ValueError):
        seen = {}

    now = int(time.time())
    seen = {f: t for f, t in seen.items() if f in orphan}
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

    unfetchable = set()
    for man in overlay.glob("*/*/Manifest"):
        d = man.parent
        pn = d.name
        by_version = {}
        for e in d.glob("*.ebuild"):
            ver = e.name[len(pn) + 1:-len(".ebuild")]
            by_version[ver] = "fetch" in restrict_tokens(
                e.read_text(errors="replace"))
        if not any(by_version.values()):
            continue
        fallback = any(by_version.values())
        for line in man.read_text(errors="replace").splitlines():
            if not line.startswith("DIST "):
                continue
            name = line.split()[1]
            hit = [v for v in by_version if v in name]
            if by_version[max(hit, key=len)] if hit else fallback:
                unfetchable.add(name)

    mirrorable = {f for f, us in users.items() if any(not r for _, r in us)} - unfetchable
    never = {f for f, us in users.items() if us and all(r for _, r in us)}

    missing = sorted(mirrorable - have)
    extra = sorted(never & have)
    orphan = sorted(have - set(users))

    refused = ""
    if not users:
        refused = f"overlay 一个 Manifest 都没有读到，{overlay} 不完整"
    elif have and len(orphan) > len(have) * MAX_REAP_SHARE:
        refused = (f"本轮 {len(orphan)}/{len(have)} 个文件无人引用，"
                   f"超过 {MAX_REAP_SHARE:.0%}")

    spent, budget = 0, 0
    if not refused:
        try:
            spent = recent_deletions(0)
        except LedgerError as e:
            refused = f"{e}，跨轮预算无依据"
        else:
            budget = max(0, int(len(have) * MAX_REAP_SHARE) - spent)
    deleted, failed = ([], []) if refused else reap(orphan, paths, budget=budget)

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

    recent = spent
    if deleted:
        try:
            recent = recent_deletions(len(deleted))
        except LedgerError as e:
            print(f"!! 帐本未记下本轮的 {len(deleted)} 个：{e}", file=sys.stderr)
            failed = failed + deleted
    if not refused and budget == 0 and orphan:
        refused = (f"最近 {WINDOW_HOURS} 小时累计清理 {spent} 个，"
                   f"已达镜像的 {MAX_REAP_SHARE:.0%}，本轮未清理")

    print(f"overlay 引用 {len(users)}，其中可镜像 {len(mirrorable)}，"
          f"不可镜像 {len(never)}，无法取得 {len(unfetchable)}")
    print(f"镜像上 {len(have)}，缺 {len(missing)}，禁止镜像 {len(extra)}，"
          f"已无人引用 {len(orphan)}，本轮清理 {len(deleted) + len(restricted)}"
          f"（其中禁止镜像 {len(restricted)}）")
    if restricted_failed:
        print(f"!! {len(restricted_failed)} 个禁止镜像的文件回收失败，仍可公开存取",
              file=sys.stderr)
    if failed:
        print(f"!! {len(failed)} 个回收失败，本轮清理未完成", file=sys.stderr)
    if refused:
        print(f"!! 拒绝清理：{refused}", file=sys.stderr)

    for f in missing[:20]:
        print(f"  缺 {f}  <- {[p for p, _ in users[f]]}")
    for f in extra[:20]:
        print(f"  多 {f}  <- {[p for p, _ in users[f]]}（所有引用方都 RESTRICT=mirror）")
    for f in deleted[:20]:
        print(f"  清理 {f}")

    return 1 if (missing or refused or failed or restricted_failed or too_many) else 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "/var/lib/binhost-overlay",
        sys.argv[2] if len(sys.argv) > 2 else "/srv/pub/distfiles"))
