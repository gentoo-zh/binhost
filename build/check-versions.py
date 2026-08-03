#!/usr/bin/env python3
"""
check-versions.py <overlay> <staged Packages> <packages.txt>
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, bindist_state, builds_from_source,
    accepts_amd64, keywords_of, newest_ebuild,
    read_mask, usable_ebuilds, version_of, vercmp,
)


def why_unbuildable(pkgdir, masks):
    """Reason no version can be built, or None when one still can.

    Returns None as soon as any version survives, so a mask or a dropped
    keyword on the newest version alone never retires the package.
    """
    versions = [(e, version_of(e, pkgdir.name))
                for e in pkgdir.glob("*.ebuild") if "9999" not in e.name]
    if not versions:
        return "只有 live ebuild，无法构建可发布的版本"
    if usable_ebuilds(pkgdir, masks):
        return None
    cp = f"{pkgdir.parent.name}/{pkgdir.name}"
    if all(masks.masks(cp, v) for _, v in versions):
        return "overlay 的 package.mask 屏蔽了全部版本"
    return "没有接受 amd64 的版本"




def newcomers(overlay, wanted, masked):
    out = []
    excluded = read_excluded(overlay)
    for pkgdir in sorted(overlay.glob("*/*")):
        if not pkgdir.is_dir():
            continue
        cp = f"{pkgdir.parent.name}/{pkgdir.name}"
        if cp in wanted or cp in excluded:
            continue
        if cp.startswith(("acct-", "virtual/", "app-alternatives/")) or cp.endswith("-bin"):
            continue
        usable = usable_ebuilds(pkgdir, masked)
        if not usable:
            continue
        eb, ver = usable[0]
        text = eb.read_text(errors="ignore")
        if bindist_state(text) != "no":
            continue
        if builds_from_source(text):
            out.append((cp, ver))
    return out


def in_gentoo(cp, tree):
    d = pathlib.Path(tree) / cp
    return d.is_dir() and any(d.glob("*.ebuild"))


def read_excluded(overlay):
    f = pathlib.Path(__file__).with_name("excluded.txt")
    if not f.exists():
        return set()
    return {l.split()[0] for l in f.read_text().splitlines()
            if l.strip() and not l.startswith("#")}


def published(index):
    out = {}
    for line in index.read_text(errors="ignore").splitlines():
        if not line.startswith("CPV: "):
            continue
        cpv = line[5:].strip()
        cp = re.sub(r"-[0-9][^-]*(-r[0-9]+)?$", "", cpv)
        ver = cpv[len(cp) + 1:]
        if cp not in out or (vercmp(ver, out[cp]) or 0) > 0:
            out[cp] = ver
    return out


def main(overlay, index, listfile):
    overlay, index = pathlib.Path(overlay), pathlib.Path(index)
    if not index.exists():
        print(f"!! 索引不存在: {index}")
        return 1

    wanted = {l.strip() for l in pathlib.Path(listfile).read_text().splitlines()
              if ATOM.match(l.strip())}
    have = published(index)

    tree = os.environ.get("GENTOO_TREE", "/var/db/repos/gentoo")
    masked = read_mask(overlay)
    stale, absent, gone, blocked = [], [], [], []
    live, banned, upstreamed, unclear = [], [], [], []
    for cp in sorted(wanted):
        pkgdir = overlay / cp
        if not pkgdir.is_dir():
            gone.append(cp)
            continue
        why = why_unbuildable(pkgdir, masked)
        if why:
            (live if "live ebuild" in why else blocked).append(cp)
            continue
        usable = usable_ebuilds(pkgdir, masked)
        eb, cur = usable[0]
        states = {bindist_state(e.read_text(errors="ignore")) for e, _ in usable}
        if "unknown" in states:
            unclear.append(cp)
            continue
        if states == {"yes"}:
            banned.append(cp)
            continue
        if in_gentoo(cp, tree):
            upstreamed.append(cp)
        got = have.get(cp)
        if got is None:
            absent.append((cp, cur))
        elif vercmp(got, cur) != 0:
            stale.append((cp, got, cur))

    fresh = newcomers(overlay, wanted, masked)

    print(f">>> 版本核对：清单 {len(wanted)}，索引 {len(have)}，落后 {len(stale)}，"
          f"缺 {len(absent)}，overlay 中不存在 {len(gone)}，已屏蔽 {len(blocked)}，"
          f"只有 9999 的 {len(live)}，不可再散布的 {len(banned)}，"
          f"RESTRICT 无法判定的 {len(unclear)}，"
          f"::gentoo 也有的 {len(upstreamed)}，未收录的新包 {len(fresh)}")
    for cp, got, cur in stale:
        print(f"    落后   {cp}  索引 {got}  overlay {cur}")
    for cp, cur in absent:
        print(f"    缺     {cp}  overlay {cur}")
    fresh_by_pn = {}
    for cp, _ in fresh:
        fresh_by_pn.setdefault(cp.split("/", 1)[1], []).append(cp)
    for cp in gone:
        pn = cp.split("/", 1)[1]
        moved = fresh_by_pn.get(pn, [])
        if moved:
            print(f"    疑似改分类 {cp} -> {moved[0]}  同名不同分类，两边一起改")
        else:
            print(f"    已移除 {cp}  overlay 中不存在该软件包，可能被删除或改了分类，清单需同步")
    for cp in blocked:
        print(f"    已屏蔽 {cp}  没有一个版本可构建，该移出清单")
    for cp in live:
        print(f"    仅 9999 {cp}  只有 live ebuild，无法构建可发布的版本")
    for cp in banned:
        print(f"    不可散布 {cp}  全部可用版本都是 RESTRICT=bindist，该移出清单")
    for cp in unclear:
        print(f"    待人工确认 {cp}  RESTRICT 用了变量或条件式，无法静态判定，未做任何处置")
    for cp in upstreamed:
        print(f"    已进主树 {cp}  ::gentoo 也有这个包，该判断是否还要自己构建")
    for cp, ver in fresh:
        print(f"    新包   {cp}  {ver}  有构建系统但不在清单，需要判断是否收录")

    return 1 if (stale or absent or gone or blocked or live or banned) else 0


def list_retirable(overlay, listfile):
    overlay = pathlib.Path(overlay)
    wanted = {l.strip() for l in pathlib.Path(listfile).read_text().splitlines()
              if ATOM.match(l.strip())}
    masked = read_mask(overlay)
    for cp in sorted(wanted):
        pkgdir = overlay / cp
        if not pkgdir.is_dir():
            print(f"{cp}\toverlay 中已不存在该软件包")
            continue
        why = why_unbuildable(pkgdir, masked)
        if why:
            print(f"{cp}\t{why}")
            continue
        states = {bindist_state(eb.read_text(errors="ignore"))
                  for eb, _ in usable_ebuilds(pkgdir, masked)}
        if "unknown" in states:
            print(f"!! {cp} 的 RESTRICT 无法静态判定，不提出退休", file=sys.stderr)
        elif states == {"yes"}:
            print(f"{cp}\t全部可用版本都是 RESTRICT=bindist，不可再散布")
    return 0


def list_newcomers(overlay, listfile):
    overlay = pathlib.Path(overlay)
    wanted = {l.strip() for l in pathlib.Path(listfile).read_text().splitlines()
              if ATOM.match(l.strip())}
    for cp, ver in newcomers(overlay, wanted, read_mask(overlay)):
        print(f"{cp} {ver}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--retire"]:
        if len(sys.argv) != 4:
            sys.exit("用法: check-versions.py --retire OVERLAY PACKAGES.TXT")
        sys.exit(list_retirable(sys.argv[2], sys.argv[3]))
    if sys.argv[1:2] == ["--newcomers"]:
        if len(sys.argv) != 4:
            sys.exit("用法: check-versions.py --newcomers OVERLAY PACKAGES.TXT")
        sys.exit(list_newcomers(sys.argv[2], sys.argv[3]))
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
