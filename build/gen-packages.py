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

# Shared module in the same directory. Only it and a couple of scripts are
# installed on the mirror, so it pulls in nothing extra.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, BUILD_ECLASS, PREBUILT_ECLASS,
    accepts_amd64, inherits, keywords_of, newest_ebuild,
    read_mask, restricts_bindist, version_of, vercmp,
)


# The paths are overridable: the layout differs between the repository and the
# mirror, so this must not assume where it was put.
HERE = pathlib.Path(__file__).resolve().parent
LIST = pathlib.Path(os.environ.get("LIST", HERE / "packages.txt"))
EXCLUDED = pathlib.Path(os.environ.get("EXCLUDED", HERE / "excluded.txt"))
OUT = pathlib.Path(os.environ.get("OUT", HERE.parent / "site" / "packages.json"))
INDEX = os.environ.get("INDEX", "")

CPV = re.compile(r"^CPV: (\S+)", re.M)


def field(text, name):
    m = re.search(rf'^{name}="([^"]*)"', text, re.M)
    return m.group(1).strip() if m else ""


def why_not_listed(cp, text, masked):
    """Why a package is not on the collection list.

    返回一个代号而不是句子：页面要按语言翻译，服务器这边不该决定用词。
    顺序就是判定的优先级——被 mask 的包连 keyword 都不用看。
    """
    if cp in masked:
        return "masked"
    # KEYWORDS is often indented inside an if block, and can come entirely from
    # an eclass, as with acct-group. Anchoring at the line start would take all
    # of those for having no keywords. When none is found, do not guess: leave
    # it to the checks below.
    #
    # The last assignment wins when one ebuild has several, as in bash.
    # liblol-glibc writes a long list of arches and then overrides it with
    # -* ~loong.
    # 三处判断都走 ebuilds.py，不再各写一份。原来这里的 RESTRICT 正则是
    # [^"]* 而 ebuilds.py 是 [^"\n]*，多行写法只有这边认得，于是页面标着
    # bindist 而 validate.py 那道唯一的再散布闸门放行。
    kw = keywords_of(text)
    if kw is not None and not accepts_amd64(kw):
        return "nokeyword"
    if restricts_bindist(text):
        return "bindist"
    if cp.startswith(("acct-", "virtual/", "app-alternatives/")):
        return "meta"
    eclasses = inherits(text)
    if eclasses & PREBUILT_ECLASS or cp.endswith("-bin"):
        return "prebuilt"
    if eclasses & BUILD_ECLASS:
        return "candidate"
    return "nobuild"


def read_excluded():
    """category/package -> reason. A package that cannot be built or
    redistributed needs a stated reason on the site."""
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
    """category/package seen in the Packages index. A missing index counts as
    empty.

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

        # A package with no source files, not on the binhost list and never
        # built is not covered by this mirror at all -- acct-group and
        # acct-user only define users and groups. Listing it would suggest the
        # mirror is incomplete.
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
        # A package on neither list used to show a bare dash on the page, which
        # says nothing. That is most of the four hundred-odd rows, so work out
        # the category.
        if cp not in wanted and cp not in excluded:
            row["why"] = why_not_listed(cp, text, masked)
        # An explicitly excluded package needs its reason, or the page cannot
        # be told apart from one nobody ever mentioned.
        if cp in excluded:
            row["excluded"] = excluded[cp]
        out.append(row)

    out.sort(key=lambda p: p["cp"])
    tmp = OUT.with_suffix(".json.new")
    tmp.write_text(json.dumps(
        {"generated": int(time.time()), "packages": out},
        ensure_ascii=False, separators=(",", ":")))
    # Overwriting in place lets the page read half-written JSON. Write a
    # temporary file and rename.
    os.replace(tmp, OUT)

    with_dist = sum(1 for p in out if p["dist"])
    print(f">>> {len(out)} packages ({sum(p['binhost'] for p in out)} on the binhost "
          f"list, {with_dist} with distfiles) -> {OUT}")
    if missing:
        print(f"!!! {len(missing)} listed but not in {overlay}:")
        for cp in missing:
            print(f"      {cp}")
        # The exit code has to carry out. On the mirror this step is wrapped by
        # daily.sh's step, which alerts only on a non-zero exit. Printing
        # without returning leaves a list that has drifted from the overlay
        # unnoticed.
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/db/repos/gentoo-zh"))
