#!/usr/bin/env python3
"""对镜像上的 distfiles 与 overlay 逐项核对。

两个方向：
  缺失  overlay 引用、允许镜像、我们却没有的
  多余  所有引用方都 RESTRICT=mirror、不该出现却出现在镜像上的

RESTRICT=mirror 的判定按文件而不是按包：一个 crate 可能同时被限制的和不限制的
包引用，只要有一个允许镜像，这个文件就是可以镜像的。emirrordist 就是这么做的，
这里是独立复核它，而不是重复它的逻辑。

退出码非零表示对不上，由 daily.sh 转成告警。
"""

import pathlib
import json
import re
import sys
import time


def scan(overlay):
    """文件名 -> [(包, 该文件所属的 ebuild 是否 RESTRICT=mirror)]

    按文件归属，不按整个包目录取或。一个包的两个版本可以有不同的 RESTRICT：
    dev-java/oraclejdk-bin 的 21.0.1 是 bindist mirror，8.391 是 fetch。按目录
    取或的话，两个版本的源码文件会互相污染，一个被当成不可镜像，另一个被当成
    取不到，而两者都不对。

    Manifest 不说哪一行 DIST 属于哪个 ebuild，所以按版本号匹配文件名——overlay
    里的源码文件绝大多数带版本号。匹配不上时退回按目录取或：宁可沿用旧行为，
    也不要凭猜测放行一个上游不许镜像的文件。
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
            # 最长的版本号优先：1.2 与 1.2.3 并存时，别把 1.2.3 的文件算到 1.2 上
            hit = [v for v in by_version if v in name]
            restricted = by_version[max(hit, key=len)] if hit else fallback
            users.setdefault(name, []).append(
                (str(d.relative_to(overlay)), restricted))
    return users


GRACE_SECONDS = 7 * 24 * 3600
STATE = "/var/lib/emirrordist/orphans.json"

MARKERS = {"layout.conf", "README.txt"}


def reap(orphan, distdir, grace=GRACE_SECONDS):
    """删掉过了回收期的孤儿文件，返回这一轮删掉的。

    版本 bump 之后旧的源码文件就没人引用了，emirrordist --delete 按它这一轮
    取过的清单删，删不到这些。留着只是占磁盘。

    不立刻删：先记下第一次发现的时间，过了回收期才动手。误判时还有一周可以
    发现，和 emirrordist 自己的 --deletion-delay 同一个思路。
    """
    state = pathlib.Path(STATE)
    try:
        seen = json.loads(state.read_text())
    except (OSError, ValueError):
        seen = {}

    now = int(time.time())
    seen = {f: t for f, t in seen.items() if f in orphan}   # 又被引用了就忘掉
    deleted = []
    for f in orphan:
        first = seen.setdefault(f, now)
        if now - first < grace:
            continue
        for path in distdir.rglob(f):
            path.unlink(missing_ok=True)
            deleted.append(f)
            break
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
    have = {p.name for p in dest.rglob("*") if p.is_file() and p.name != "layout.conf"}

    # fetch 限制的包连 SRC_URI 都没有 URL，谁也镜像不了，不算缺失
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
    # overlay 已经完全不再引用的。版本 bump 之后旧的源码文件就是这一类，
    # emirrordist --delete 只按它这一轮取过的清单删，删不到这些。
    # 布局标记不是 distfile：layout.conf 告诉 portage 这里用两级哈希而不是
    # 平铺目录，官方 distfiles 根下也有同一份。没有它客户端会到错误的路径去取。
    orphan = sorted(have - set(users) - MARKERS)
    deleted = reap(orphan, dest)

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

    # 无人引用的文件由 reap 按回收期处理，是版本 bump 的常态，不判失败。
    # 每小时为同一批文件推一次告警只会让人学会忽略告警。
    return 1 if (missing or extra) else 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "/var/lib/binhost-overlay",
        sys.argv[2] if len(sys.argv) > 2 else "/srv/pub/distfiles"))
