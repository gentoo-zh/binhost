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
    ATOM, PREBUILT_ECLASS, bindist_state, builds_from_source, inherits,
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




def read_moves(overlay):
    direct = {}
    updates = pathlib.Path(overlay) / "profiles" / "updates"
    for path in sorted(updates.glob("*")) if updates.is_dir() else ():
        for raw in path.read_text(errors="replace").splitlines():
            line = raw.split("#", 1)[0].split()
            if len(line) == 3 and line[0] == "move" and ATOM.match(line[1]) \
                    and ATOM.match(line[2]):
                direct[line[1]] = line[2]
    resolved = {}
    for source in direct:
        seen = {source}
        target = direct[source]
        while target in direct and target not in seen:
            seen.add(target)
            target = direct[target]
        if target not in seen:
            resolved[source] = target
    return resolved


def newcomer_classifications(overlay, wanted, masked, move_destinations=()):
    groups = {}
    excluded = read_excluded(overlay)
    for pkgdir in sorted(overlay.glob("*/*")):
        if not pkgdir.is_dir() or not any(pkgdir.glob("*.ebuild")):
            continue
        cp = f"{pkgdir.parent.name}/{pkgdir.name}"
        if cp in wanted or cp in excluded:
            continue
        category = None
        version = None
        if cp in move_destinations:
            category = "move destination"
        elif cp.startswith(("acct-", "virtual/", "app-alternatives/")):
            category = "meta package"
        elif cp.endswith("-bin"):
            category = "-bin package"
        usable = usable_ebuilds(pkgdir, masked)
        if category is None and not usable:
            reason = why_unbuildable(pkgdir, masked) or ""
            category = "live only" if "live ebuild" in reason else "no amd64 or masked"
        if category is None:
            eb, version = usable[0]
            text = eb.read_text(errors="ignore")
            restriction = bindist_state(text)
            if restriction == "yes":
                category = "bindist"
            elif restriction == "unknown":
                category = "unknown RESTRICT"
            elif inherits(text) & PREBUILT_ECLASS:
                category = "prebuilt eclass"
            elif builds_from_source(text):
                category = "candidate"
            else:
                category = "no known build stage"
        groups.setdefault(category, []).append((cp, version))
    return groups


def newcomers(overlay, wanted, masked, move_destinations=()):
    return newcomer_classifications(
        overlay, wanted, masked, move_destinations).get("candidate", [])


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
    for stanza in index.read_text(errors="ignore").split("\n\n")[1:]:
        fields = dict(re.findall(r"^(\w+): (.*)$", stanza, re.M))
        if fields.get("REPO") != "gentoo-zh" or not fields.get("CPV"):
            continue
        cpv = fields["CPV"]
        cp = re.sub(r"-[0-9][^-]*(-r[0-9]+)?$", "", cpv)
        ver = cpv[len(cp) + 1:]
        if cp not in out or (vercmp(ver, out[cp]) or 0) > 0:
            out[cp] = ver
    return out


def main(overlay, index, listfile):
    overlay, index = pathlib.Path(overlay), pathlib.Path(index)
    if not index.exists():
        print(f"!! 索引不存在： {index}")
        return 1

    wanted = {l.strip() for l in pathlib.Path(listfile).read_text().splitlines()
              if ATOM.match(l.strip())}
    have = published(index)

    tree = os.environ.get("GENTOO_TREE", "/var/db/repos/gentoo")
    masked = read_mask(overlay)
    moves = read_moves(overlay)
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

    fresh = newcomers(overlay, wanted, masked, set(moves.values()))

    print(f">>> 版本核对：清单 {len(wanted)}，索引 {len(have)}，落后 {len(stale)}，"
          f"缺 {len(absent)}，overlay 中不存在 {len(gone)}，已屏蔽 {len(blocked)}，"
          f"只有 9999 的 {len(live)}，不可再散布的 {len(banned)}，"
          f"RESTRICT 无法判定的 {len(unclear)}，"
          f"::gentoo 也有的 {len(upstreamed)}，未收录的新包 {len(fresh)}")
    for cp, got, cur in stale:
        print(f"    落后   {cp}  索引 {got}  overlay {cur}")
    for cp, cur in absent:
        print(f"    缺     {cp}  overlay {cur}")
    for cp in gone:
        moved = moves.get(cp)
        if moved and moved not in wanted and (overlay / moved).is_dir():
            print(f"    改分类 {cp} -> {moved}  profiles/updates 要求清单同步替换")
        else:
            print(f"    已移除 {cp}  overlay 中不存在该软件包，可能被删除或改了分类，清单需同步")
    for cp in blocked:
        print(f"    已屏蔽 {cp}  没有一个版本可构建，应从清单移除")
    for cp in live:
        print(f"    仅 9999 {cp}  只有 live ebuild，无法构建可发布的版本")
    for cp in banned:
        print(f"    不可散布 {cp}  全部可用版本都是 RESTRICT=bindist，应从清单移除")
    for cp in unclear:
        print(f"    待人工确认 {cp}  RESTRICT 用了变量或条件式，无法确认能否散布，本轮不发布")
    for cp in upstreamed:
        print(f"    已进主树 {cp}  ::gentoo 也有这个包，需确认是否仍由本站构建")
    for cp, ver in fresh:
        print(f"    新包   {cp}  {ver}  有构建系统但不在清单，需要判断是否收录")

    return 1 if (stale or absent or gone or blocked or live or banned or unclear) else 0


def list_retirable(overlay, listfile):
    overlay = pathlib.Path(overlay)
    wanted = {l.strip() for l in pathlib.Path(listfile).read_text().splitlines()
              if ATOM.match(l.strip())}
    masked = read_mask(overlay)
    move_sources = set(read_moves(overlay))
    for cp in sorted(wanted):
        if cp in move_sources:
            continue
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
    moves = read_moves(overlay)
    groups = newcomer_classifications(
        overlay, wanted, read_mask(overlay), set(moves.values()))
    for category in sorted(groups):
        atoms = " ".join(cp for cp, _version in groups[category])
        print(f">>> {category}: {len(groups[category])}: {atoms}", file=sys.stderr)
    for cp, ver in groups.get("candidate", []):
        print(f"{cp} {ver}")
    return 0


def list_moves(overlay, listfile):
    overlay = pathlib.Path(overlay)
    wanted = {line.strip() for line in pathlib.Path(listfile).read_text().splitlines()
              if ATOM.match(line.strip())}
    for source, target in sorted(read_moves(overlay).items()):
        if source in wanted and target not in wanted and (overlay / target).is_dir():
            print(f"{source}\t{target}")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--retire"]:
        if len(sys.argv) != 4:
            sys.exit("用法： check-versions.py --retire OVERLAY PACKAGES.TXT")
        sys.exit(list_retirable(sys.argv[2], sys.argv[3]))
    if sys.argv[1:2] == ["--newcomers"]:
        if len(sys.argv) != 4:
            sys.exit("用法： check-versions.py --newcomers OVERLAY PACKAGES.TXT")
        sys.exit(list_newcomers(sys.argv[2], sys.argv[3]))
    if sys.argv[1:2] == ["--moves"]:
        if len(sys.argv) != 4:
            sys.exit("用法： check-versions.py --moves OVERLAY PACKAGES.TXT")
        sys.exit(list_moves(sys.argv[2], sys.argv[3]))
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
