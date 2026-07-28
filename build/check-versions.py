#!/usr/bin/env python3
"""核对暂存区的版本与 overlay 当前版本是否一致。

跑在发布之后。那一刻两者本该逐个对上：overlay bump 了新版就该编出新版，
drop 了旧版索引里也不该再留着。对不上说明这个包这一轮没编出来，或者被
按 REPO 过滤掉了——单看失败清单发现不了后一种。

平时比对没有意义：overlay 一天 bump 十几次而构建一天一轮，两次构建之间
索引落后是设计如此，拿那个报警只会制造噪音。

    check-versions.py <overlay> <暂存区的 Packages> <packages.txt>
"""
import pathlib
import re
import sys

try:
    from portage.versions import vercmp
except ImportError:
    sys.exit("需要 sys-apps/portage：版本比较用 portage.versions.vercmp")

ATOM = re.compile(r"^[a-z0-9-]+/[A-Za-z0-9._+-]+$")


def newest_ebuild(pkgdir):
    """目录里版本最高的非 live ebuild 的版本号。"""
    ebuilds = [e for e in pkgdir.glob("*.ebuild") if "9999" not in e.name]
    if not ebuilds:
        return None
    pn = pkgdir.name
    best = ebuilds[0]
    for e in ebuilds[1:]:
        a = e.name[len(pn) + 1:-len(".ebuild")]
        b = best.name[len(pn) + 1:-len(".ebuild")]
        if (vercmp(a, b) or 0) > 0:
            best = e
    return best.name[len(pn) + 1:-len(".ebuild")]


def published(index):
    """索引里每个 cp 对应的版本。"""
    out = {}
    for line in index.read_text(errors="ignore").splitlines():
        if not line.startswith("CPV: "):
            continue
        cpv = line[5:].strip()
        cp = re.sub(r"-[0-9][^-]*(-r[0-9]+)?$", "", cpv)
        out[cp] = cpv[len(cp) + 1:]
    return out


def main(overlay, index, listfile):
    overlay, index = pathlib.Path(overlay), pathlib.Path(index)
    if not index.exists():
        print(f"!! 索引不存在: {index}")
        return 1

    wanted = {l.strip() for l in pathlib.Path(listfile).read_text().splitlines()
              if ATOM.match(l.strip())}
    have = published(index)

    stale, absent = [], []
    for cp in sorted(wanted):
        pkgdir = overlay / cp
        if not pkgdir.is_dir():
            continue
        cur = newest_ebuild(pkgdir)
        if cur is None:
            continue
        got = have.get(cp)
        if got is None:
            absent.append((cp, cur))
        elif got != cur:
            stale.append((cp, got, cur))

    print(f">>> 版本核对：清单 {len(wanted)}，索引 {len(have)}，"
          f"落后 {len(stale)}，缺 {len(absent)}")
    for cp, got, cur in stale:
        print(f"    落后 {cp}  索引 {got}  overlay {cur}")
    for cp, cur in absent:
        print(f"    缺   {cp}  overlay {cur}")

    return 1 if (stale or absent) else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
