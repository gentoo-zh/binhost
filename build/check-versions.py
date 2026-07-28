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


def read_mask(overlay):
    """profiles/package.mask 里被屏蔽的 category/package。"""
    f = overlay / "profiles" / "package.mask"
    if not f.exists():
        return set()
    out = set()
    for raw in f.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"[a-z0-9-]+/[A-Za-z0-9._+-]+", line.lstrip("<>=~!"))
        if m:
            out.add(re.sub(r"-[0-9][^/]*$", "", m.group(0)))
    return out


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


# 有真正编译过程的 eclass。判定与 gen-packages.py 一致。
BUILD_ECLASS = {
    "cmake", "meson", "go-module", "cargo", "autotools", "gnome2",
    "distutils-r1", "dotnet-pkg", "qmake-utils", "waf-utils", "scons-utils",
}
PREBUILT_ECLASS = {"unpacker", "rpm", "java-pkg-simple"}


def accepts_amd64(keywords):
    """KEYWORDS 是否涵盖 amd64。`*` 与 `~*` 算涵盖，`-*` 关闭全部。"""
    ok = False
    for k in keywords.split():
        if k in ("*", "~*"):
            ok = True
        elif k == "-*":
            ok = False
        elif k.lstrip("~") == "amd64":
            ok = not k.startswith("-")
        elif k == "-amd64":
            ok = False
    return ok


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
        ver = newest_ebuild(pkgdir)
        if ver is None:
            continue
        text = (pkgdir / f"{pkgdir.name}-{ver}.ebuild").read_text(errors="ignore")
        kw = re.findall(r'^\s*KEYWORDS="([^"]*)"', text, re.M)
        if kw and not accepts_amd64(kw[-1]):
            continue
        restrict = re.findall(r'^\s*RESTRICT="([^"]*)"', text, re.M)
        if restrict and "bindist" in restrict[-1]:
            continue
        inherits = set(" ".join(re.findall(r"^inherit (.+)$", text, re.M)).split())
        if inherits & PREBUILT_ECLASS:
            continue
        if inherits & BUILD_ECLASS:
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
        cur = newest_ebuild(pkgdir)
        if cur is None:
            continue
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

    return 1 if (stale or absent or gone or blocked or fresh) else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3]))
