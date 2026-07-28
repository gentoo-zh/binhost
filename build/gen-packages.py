#!/usr/bin/env python3
"""Build site/packages.json from the overlay and the binhost package list.

The page covers the whole overlay, not just the binhost list: distfiles are
mirrored for every package that has any, which is far more packages than the
binhost builds. Listing only the binhost candidates would understate distfiles
coverage by more than half.

这里只输出「在不在收录清单里」这个布尔。页面上的三态——已构建 / 待构建 /
不收录——是把这个布尔和线上的 Packages 索引合起来算的：清单说该有，索引里
没有，那就是还没构建。哪些真的构建出来了由页面按索引判断，不写进这份 JSON。

`INDEX` 指向 Packages 索引时，索引里出现过的包一律保留一行。构建一个包会把
它属于本 overlay 的依赖一并编出来（acct-user、virtual 这类），那些包不在清单
里也没有源码文件，按下面的规则本会被跳过，页面上就查不到已经发布的东西。
"""

import json
import os
import pathlib
import re
import sys

try:
    from portage.versions import catpkgsplit, vercmp
except ImportError:  # 没有 portage 就没法正确比版本，宁可停下也不要读错 ebuild
    sys.exit("需要 sys-apps/portage：版本比较用 portage.versions.vercmp")
import time

# 同目录的共用模块。镜像机上只装了它和几个脚本，所以它不引入额外依赖。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, BUILD_ECLASS, PREBUILT_ECLASS,
    accepts_amd64, inherits, keywords_of, newest_ebuild,
    read_mask, restricts_bindist, version_of, vercmp,
)


# 路径可以覆盖：这个脚本在仓库里和在镜像机上的布局不同，不该假设自己被放在哪。
HERE = pathlib.Path(__file__).resolve().parent
LIST = pathlib.Path(os.environ.get("LIST", HERE / "packages.txt"))
EXCLUDED = pathlib.Path(os.environ.get("EXCLUDED", HERE / "excluded.txt"))
OUT = pathlib.Path(os.environ.get("OUT", HERE.parent / "site" / "packages.json"))
INDEX = os.environ.get("INDEX", "")

CPV = re.compile(r"^CPV: (\S+)", re.M)


def field(text, name):
    m = re.search(rf'^{name}="([^"]*)"', text, re.M)
    return m.group(1).strip() if m else ""


# 有真正编译过程的 eclass。收录清单当初就是按这个分的第一梯队。
BUILD_ECLASS = {
    "cmake", "meson", "go-module", "cargo", "autotools", "gnome2",
    "distutils-r1", "dotnet-pkg", "qmake-utils", "waf-utils", "scons-utils",
}
# 出现这些 eclass 即为解包上游产物，无编译过程
PREBUILT_ECLASS = {"unpacker", "rpm", "java-pkg-simple"}


def why_not_listed(cp, text, masked):
    """不在收录清单的包，为什么不在。

    返回一个代号而不是句子：页面要按语言翻译，服务器这边不该决定用词。
    顺序就是判定的优先级——被 mask 的包连 keyword 都不用看。
    """
    if cp in masked:
        return "masked"
    # KEYWORDS 常写在 if 块里而带缩进，也可能整个来自 eclass（acct-group 这些）。
    # 锚行首会把它们全判成没有 keyword。找不到就别猜，交给后面的判断。
    # 同一个 ebuild 里出现多次时后一次生效，和 bash 一致。liblol-glibc 先写了
    # 一长串架构，随后又被 -* ~loong 覆盖。
    kw = re.findall(r'^\s*KEYWORDS="([^"]*)"', text, re.M)
    if kw and not accepts_amd64(kw[-1]):
        return "nokeyword"
    restrict = re.findall(r'^\s*RESTRICT="([^"]*)"', text, re.M)
    if restrict and "bindist" in restrict[-1]:
        return "bindist"
    if cp.startswith(("acct-", "virtual/", "app-alternatives/")):
        return "meta"
    inherits = set(" ".join(re.findall(r"^inherit (.+)$", text, re.M)).split())
    if inherits & PREBUILT_ECLASS or cp.endswith("-bin"):
        return "prebuilt"
    if inherits & BUILD_ECLASS:
        return "candidate"
    return "nobuild"


def read_excluded():
    """category/package -> 原因。构建不出来或不能分发的包，站点上要说明为什么。"""
    out = {}
    if not EXCLUDED.exists():
        return out
    for raw in EXCLUDED.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\s{2,}|\t", line, maxsplit=1)
        out[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else ""
    return out


def read_built():
    """Packages 索引里出现过的 category/package。索引不存在就当成空。

    刚部署、还没发布过第一批包的时候索引本来就没有，那不是错误。
    """
    if not INDEX:
        return set()
    p = pathlib.Path(INDEX)
    if not p.exists():
        return set()
    out = set()
    for cpv in CPV.findall(p.read_text(errors="ignore")):
        parts = catpkgsplit(cpv)
        if parts:
            out.add(f"{parts[0]}/{parts[1]}")
    return out


def main(overlay):
    overlay = pathlib.Path(overlay)
    if not (overlay / "profiles" / "repo_name").exists():
        sys.exit(f"not an ebuild repository: {overlay}")

    wanted = {
        line.strip()
        for line in LIST.read_text().splitlines()
        if ATOM.match(line.strip())
    }

    excluded = read_excluded()
    built = read_built()
    masked = read_mask(overlay)
    out, missing = [], sorted(wanted)
    for pkgdir in sorted(overlay.glob("*/*")):
        if not pkgdir.is_dir():
            continue
        cp = f"{pkgdir.parent.name}/{pkgdir.name}"
        eb = newest_ebuild(pkgdir)
        if eb is None:
            continue

        manifest = pkgdir / "Manifest"
        dist = []
        if manifest.exists():
            dist = re.findall(r"^DIST (\S+)", manifest.read_text(errors="ignore"), re.M)

        # 既没有源码文件、又不在 binhost 清单、也没被构建出来的包，这个镜像
        # 完全不涵盖（acct-group/acct-user 这类只是用户与组的定义）。列出来
        # 只会让人以为镜像有遗漏。
        if not dist and cp not in wanted and cp not in built:
            continue

        if cp in wanted:
            missing.remove(cp)

        text = eb.read_text(errors="ignore")
        row = {
            "cp": cp,
            "desc": field(text, "DESCRIPTION"),
            "binhost": cp in wanted,
            "dist": sorted(set(dist)),
        }
        # 不在清单也不在排除清单的包，页面上原本只有一个破折号，什么都不说。
        # 四百多行里这样的占一大半，算出类别来。
        if cp not in wanted and cp not in excluded:
            row["why"] = why_not_listed(cp, text, masked)
        # 明确排除的包要说明为什么，否则页面上和「没人提过它」看着一样
        if cp in excluded:
            row["excluded"] = excluded[cp]
        out.append(row)

    out.sort(key=lambda p: p["cp"])
    tmp = OUT.with_suffix(".json.new")
    tmp.write_text(json.dumps(
        {"generated": int(time.time()), "packages": out},
        ensure_ascii=False, separators=(",", ":")))
    # 就地覆写时页面可能读到写了一半的 JSON。写临时文件再改名。
    os.replace(tmp, OUT)

    with_dist = sum(1 for p in out if p["dist"])
    print(f">>> {len(out)} packages ({sum(p['binhost'] for p in out)} on the binhost "
          f"list, {with_dist} with distfiles) -> {OUT}")
    if missing:
        print(f"!!! {len(missing)} listed but not in {overlay}:")
        for cp in missing:
            print(f"      {cp}")
        # 退出码要带出去。镜像机上这一步由 daily.sh 的 step 包着，而 step 只在
        # 非零退出时告警。只打印不返回，清单与 overlay 脱节就没有人知道。
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/db/repos/gentoo-zh"))
