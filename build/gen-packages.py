#!/usr/bin/env python3

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
    ATOM, BUILD_ECLASS, PREBUILT_ECLASS,
    accepts_amd64, inherits, keywords_of, newest_ebuild,
    read_mask, restricts_bindist, version_of, vercmp,
)


HERE = pathlib.Path(__file__).resolve().parent
LIST = pathlib.Path(os.environ.get("LIST", HERE / "packages.txt"))
EXCLUDED = pathlib.Path(os.environ.get("EXCLUDED", HERE / "excluded.txt"))
OUT = pathlib.Path(os.environ.get("OUT", HERE.parent / "site" / "packages.json"))
INDEX = os.environ.get("INDEX", "")
DIST_INDEX = pathlib.Path(os.environ.get("DIST_INDEX", OUT.parent / "distfiles-index.json"))

CPV = re.compile(r"^CPV: (\S+)", re.M)


def field(text, name):
    m = re.search(rf'^{name}="([^"]*)"', text, re.M)
    return m.group(1).strip() if m else ""


def why_not_listed(cp, text, masked):
    if cp in masked:
        return "masked"
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
        print(f"!! 无法获取 {DIST_INDEX}，distfiles 一栏按 Manifest 算", file=sys.stderr)

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
            row["why"] = why_not_listed(cp, text, masked)
        if cp in excluded:
            row["excluded"] = excluded[cp]
        out.append(row)

    out.sort(key=lambda p: p["cp"])
    tmp = OUT.with_suffix(".json.new")
    tmp.write_text(json.dumps(
        {"generated": int(time.time()), "packages": out},
        ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, OUT)

    txt = OUT.with_name("packages.txt")
    lines = [f"# gentoo-zh overlay，{len(out)} 个包",
             f"# 生成于 {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
             "# 第二列：bin 有二进制包，src 只镜像源码，-- 两者都没有",
             ""]
    for pkg in out:
        on_mirror = bool(pkg["dist"]) and (
            have is None or all(f in have for f in pkg["dist"]))
        mark = "bin" if pkg["binhost"] else "src" if on_mirror else "--"
        lines.append(f"{pkg['cp']:<44} {mark}  {pkg['desc']}".rstrip())
    tmp_txt = txt.with_suffix(".txt.new")
    tmp_txt.write_text("\n".join(lines) + "\n")
    os.replace(tmp_txt, txt)

    with_dist = sum(1 for p in out if p["dist"])
    print(f">>> {len(out)} packages ({sum(p['binhost'] for p in out)} on the binhost "
          f"list, {with_dist} with distfiles) -> {OUT}")
    if missing:
        print(f"!!! {len(missing)} listed but not in {overlay}:")
        for cp in missing:
            print(f"      {cp}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/db/repos/gentoo-zh"))
