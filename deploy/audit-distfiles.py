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
import re
import sys


def scan(overlay):
    """文件名 -> [(包, 该包是否 RESTRICT=mirror)]"""
    users = {}
    for man in overlay.glob("*/*/Manifest"):
        d = man.parent
        ebuilds = list(d.glob("*.ebuild"))
        if not ebuilds:
            continue
        restricted = any(
            re.search(r"RESTRICT=.*\bmirror\b", e.read_text(errors="replace"))
            for e in ebuilds)
        for line in man.read_text(errors="replace").splitlines():
            if line.startswith("DIST "):
                users.setdefault(line.split()[1], []).append(
                    (str(d.relative_to(overlay)), restricted))
    return users


MARKERS = {"layout.conf", "README.txt"}


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

    print(f"overlay 引用 {len(users)}，其中可镜像 {len(mirrorable)}，"
          f"不可镜像 {len(never)}，无法取得 {len(unfetchable)}")
    print(f"镜像上 {len(have)}，缺 {len(missing)}，多 {len(extra)}，"
          f"已无人引用 {len(orphan)}")

    for f in missing[:20]:
        print(f"  缺 {f}  <- {[p for p, _ in users[f]]}")
    for f in extra[:20]:
        print(f"  多 {f}  <- {[p for p, _ in users[f]]}（所有引用方都 RESTRICT=mirror）")
    for f in orphan[:20]:
        print(f"  已无人引用 {f}")

    return 1 if (missing or extra or orphan) else 0


if __name__ == "__main__":
    sys.exit(main(
        sys.argv[1] if len(sys.argv) > 1 else "/var/lib/binhost-overlay",
        sys.argv[2] if len(sys.argv) > 2 else "/srv/pub/distfiles"))
