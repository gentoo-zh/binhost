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

# 同目录的共用模块。镜像机上只装了它和几个脚本，所以它不引入额外依赖。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, BUILD_ECLASS, PREBUILT_ECLASS,
    accepts_amd64, inherits, keywords_of, newest_ebuild,
    read_mask, restricts_bindist, version_of, vercmp,
)




def newcomers(overlay, wanted, masked):
    """overlay 里有构建系统、能装在 amd64 上、却不在清单里的包。

    排除的几类与收录规则一致：预编译重打包没有编译过程，RESTRICT=bindist
    不能再分发，acct/virtual 不装任何文件，被 mask 的等着删。
    """
    out = []
    excluded = read_excluded(overlay)
    for pkgdir in sorted(overlay.glob("*/*")):
        if not pkgdir.is_dir():
            continue
        cp = f"{pkgdir.parent.name}/{pkgdir.name}"
        if cp in wanted or cp in masked or cp in excluded:
            continue
        if cp.startswith(("acct-", "virtual/", "app-alternatives/")) or cp.endswith("-bin"):
            continue
        eb = newest_ebuild(pkgdir)
        if eb is None:
            continue
        ver = version_of(eb, pkgdir.name)
        text = eb.read_text(errors="ignore")
        kw = keywords_of(text)
        if kw is not None and not accepts_amd64(kw):
            continue
        if restricts_bindist(text):
            continue
        eclasses = inherits(text)
        if eclasses & PREBUILT_ECLASS:
            continue
        if eclasses & BUILD_ECLASS:
            out.append((cp, ver))
    return out


def read_excluded(overlay):
    """build/excluded.txt 里明确不收录的包。跟 check-versions.py 放在一起。"""
    f = pathlib.Path(__file__).with_name("excluded.txt")
    if not f.exists():
        return set()
    return {l.split()[0] for l in f.read_text().splitlines()
            if l.strip() and not l.startswith("#")}


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

    masked = read_mask(overlay)
    stale, absent, gone, blocked = [], [], [], []
    for cp in sorted(wanted):
        pkgdir = overlay / cp
        # 清单里有、overlay 里没有：包被删或改了分类，清单没跟上
        if not pkgdir.is_dir():
            gone.append(cp)
            continue
        # overlay 自己 mask 掉了却还在清单里，构建时才会报所有版本被屏蔽
        if cp in masked:
            blocked.append(cp)
            continue
        eb = newest_ebuild(pkgdir)
        if eb is None:
            continue
        cur = version_of(eb, pkgdir.name)
        got = have.get(cp)
        if got is None:
            absent.append((cp, cur))
        elif got != cur:
            stale.append((cp, got, cur))

    # overlay 里新出现、有构建系统、却不在清单里的包。新包上线时清单不会自己
    # 跟上，没有这一项就只能靠人翻提交记录。判定与站点上那个「待复查」标签同源。
    fresh = newcomers(overlay, wanted, masked)

    print(f">>> 版本核对：清单 {len(wanted)}，索引 {len(have)}，落后 {len(stale)}，"
          f"缺 {len(absent)}，overlay 里没有 {len(gone)}，已屏蔽 {len(blocked)}，"
          f"未收录的新包 {len(fresh)}")
    for cp, got, cur in stale:
        print(f"    落后   {cp}  索引 {got}  overlay {cur}")
    for cp, cur in absent:
        print(f"    缺     {cp}  overlay {cur}")
    for cp in gone:
        print(f"    已移除 {cp}  overlay 里找不到，包被删或改了分类，清单要跟上")
    for cp in blocked:
        print(f"    已屏蔽 {cp}  overlay 的 package.mask 屏蔽了它，该移出清单")
    for cp, ver in fresh:
        print(f"    新包   {cp}  {ver}  有构建系统却不在清单，要人决定收不收")

    # 新包不计入退出码。它不是「对不上」，是「有一个包等人决定收不收」，
    # 而 cycle.sh 每轮都会据此推一条告警——同一件事每天推一次，只会让人
    # 学会忽略告警。审计里 audit-distfiles.py 已经因为同样的理由改过一次。
    # 它仍然打印出来，读日志的人看得到。
    return 1 if (stale or absent or gone or blocked) else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
