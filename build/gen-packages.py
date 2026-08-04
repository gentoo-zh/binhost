#!/usr/bin/env python3

import functools
import json
import os
import pathlib
import re
import sys

try:
    from portage.versions import catpkgsplit, vercmp
except ImportError:
    sys.exit("需要 sys-apps/portage：版本比较用 portage.versions.vercmp")
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, PREBUILT_ECLASS, bindist_state, builds_from_source,
    accepts_amd64, inherits, keywords_of, newest_ebuild,
    read_mask, version_of, vercmp,
)


HERE = pathlib.Path(__file__).resolve().parent
LIST = pathlib.Path(os.environ.get("LIST", HERE / "packages.txt"))
EXCLUDED = pathlib.Path(os.environ.get("EXCLUDED", HERE / "excluded.txt"))
OUT = pathlib.Path(os.environ.get("OUT", HERE.parent / "site" / "packages.json"))
INDEX = os.environ.get("INDEX", "")
DIST_INDEX = pathlib.Path(os.environ.get("DIST_INDEX", OUT.parent / "distfiles-index.json"))

CPV = re.compile(r"^CPV: (\S+)", re.M)
STANZA = re.compile(r"^(\w+): (.*)$", re.M)


def field(text, name):
    m = re.search(rf'^{name}="([^"]*)"', text, re.M)
    return m.group(1).strip() if m else ""


def why_not_listed(cp, ver, text, masked):
    if masked.masks(cp, ver):
        return "masked"
    kw = keywords_of(text)
    if kw is not None and not accepts_amd64(kw):
        return "nokeyword"
    if bindist_state(text) != "no":
        return "bindist"
    if cp.startswith(("acct-", "virtual/", "app-alternatives/")):
        return "meta"
    if inherits(text) & PREBUILT_ECLASS or cp.endswith("-bin"):
        return "prebuilt"
    if builds_from_source(text):
        return "candidate"
    return "nobuild"


def read_excluded():
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


class IndexUnreadable(Exception):
    pass


def read_deps():
    """Every ::gentoo package the index publishes, one entry per CPV.

    Keyed by CPV rather than by package, because staging publishes more than
    one version of the same package whenever two slots or two exact atoms are
    depended on, and dropping the older one would name a version that is not
    the one a consumer gets.

    Only REPO: gentoo counts. A stanza from any other repository is a state
    this script does not know how to describe, so it stops rather than file it
    under the main tree.
    """
    if not INDEX:
        return []
    p = pathlib.Path(INDEX)
    if not p.exists():
        raise IndexUnreadable(f"{p} 不存在")
    try:
        text = p.read_text(errors="ignore")
    except OSError as e:
        raise IndexUnreadable(f"{p} 读取失败：{e}") from e

    out, others = [], set()
    for s in text.split("\n\n")[1:]:
        f = dict(STANZA.findall(s))
        cpv = f.get("CPV")
        if not cpv:
            continue
        repo = f.get("REPO", "")
        if repo == "gentoo-zh":
            continue
        if repo != "gentoo":
            others.add(repo or "（无 REPO 字段）")
            continue
        parts = catpkgsplit(cpv)
        if not parts:
            raise IndexUnreadable(f"无法解析 CPV：{cpv}")
        ver = parts[2] + ("-" + parts[3] if parts[3] != "r0" else "")
        out.append({"cp": f"{parts[0]}/{parts[1]}", "ver": ver,
                    "slot": f.get("SLOT", "0").split("/", 1)[0]})
    if others:
        raise IndexUnreadable(f"索引里有未知仓库的产物：{' '.join(sorted(others))}")
    def compare(left, right):
        prefix = (left["cp"], left["slot"]), (right["cp"], right["slot"])
        if prefix[0] != prefix[1]:
            return -1 if prefix[0] < prefix[1] else 1
        return vercmp(left["ver"], right["ver"]) or 0

    out.sort(key=functools.cmp_to_key(compare))
    return out


def mirrored():
    try:
        return set(json.loads(DIST_INDEX.read_text())["files"])
    except (OSError, ValueError, KeyError):
        return None


def main(overlay):
    overlay = pathlib.Path(overlay)
    if not (overlay / "profiles" / "repo_name").exists():
        sys.exit(f"not an ebuild repository: {overlay}")

    wanted = {
        line.strip()
        for line in LIST.read_text().splitlines()
        if ATOM.match(line.strip())
    }

    have = mirrored()
    if have is None:
        print(f"!! 无法获取 {DIST_INDEX}，源码一列无法确定", file=sys.stderr)

    excluded = read_excluded()
    built = read_built()
    try:
        deps = read_deps()
    except IndexUnreadable as e:
        print(f"!!! 索引无法使用：{e}", file=sys.stderr)
        print("!!! 未写出任何文件，保留上一份有效输出", file=sys.stderr)
        return 1
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
        if cp not in wanted and cp not in excluded:
            row["why"] = why_not_listed(cp, version_of(eb, pkgdir.name), text, masked)
        if cp in excluded:
            row["excluded"] = excluded[cp]
        out.append(row)

    out.sort(key=lambda p: p["cp"])

    if missing:
        print(f"!!! {len(missing)} listed but not in {overlay}:")
        for cp in missing:
            print(f"      {cp}")
        print("!!! 清单与 overlay 不一致，未写出任何文件", file=sys.stderr)
        return 1

    tmp = OUT.with_suffix(".json.new")
    tmp.write_text(json.dumps(
        {"schema": 2, "generated": int(time.time()), "packages": out,
         "deps": deps},
        ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, OUT)

    txt = OUT.with_name("packages.txt")
    lines = [f"# gentoo-zh overlay，{len(out)} 个包",
             f"# 生成于 {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
             "# 第二列：bin 有二进制包，src 只镜像源码，-- 两者都没有，"
             "?? 无法确定（distfiles 索引未能读取）",
             ""]
    for pkg in out:
        if pkg["binhost"]:
            mark = "bin"
        elif not pkg["dist"]:
            mark = "--"
        elif have is None:
            mark = "??"
        else:
            mark = "src" if all(f in have for f in pkg["dist"]) else "--"
        lines.append(f"{pkg['cp']:<44} {mark}  {pkg['desc']}".rstrip())
    tmp_txt = txt.with_suffix(".txt.new")
    tmp_txt.write_text("\n".join(lines) + "\n")
    os.replace(tmp_txt, txt)

    # A separate file rather than a second section: the second column in
    # packages.txt is a status, and reusing it for a version would break
    # anything reading the file line by line.
    dep_txt = OUT.with_name("deps.txt")
    dep_lines = [f"# 随 gentoo-zh 的包一并发布的 ::gentoo 运行期依赖，{len(deps)} 个",
                 f"# 生成于 {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
                 "# 第二列 slot，第三列版本；不替代 Gentoo 官方 binhost",
                 ""]
    dep_lines += [f"{d['cp']:<44} {d['slot']:<8} {d['ver']}" for d in deps]
    tmp_dep = dep_txt.with_suffix(".txt.new")
    tmp_dep.write_text("\n".join(dep_lines) + "\n")
    os.replace(tmp_dep, dep_txt)

    with_dist = sum(1 for p in out if p["dist"])
    print(f">>> {len(out)} packages ({sum(p['binhost'] for p in out)} on the binhost "
          f"list, {with_dist} with distfiles, {len(deps)} ::gentoo deps) -> {OUT}")
    if have is None:
        print("!!! distfiles 索引未能读取，源码一列按无法确定输出", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/db/repos/gentoo-zh"))
