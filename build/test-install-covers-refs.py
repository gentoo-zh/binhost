#!/usr/bin/env python3
"""Everything the deployed scripts reach for must be something install.sh puts there.

This exists because of a real break: alert.sh was extracted into a shared file
and daily.sh was changed to source ${LIB}/alert.sh, but install.sh only rsynced
it to the staging directory and never installed it. Nothing failed until the
next deploy, and the thing that would have broken was the alerting.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"

# Where install.sh puts things -> which prefix scripts refer to it by
DIRS = {
    "/usr/local/lib/binhost": ("${LIB}", "/usr/local/lib/binhost"),
    "/usr/local/bin": ("/usr/local/bin",),
}


def installed():
    """Basenames install.sh writes, per destination directory."""
    out = {d: set() for d in DIRS}
    for line in INSTALL.read_text().splitlines():
        m = re.search(r"install\s+-m\d+\s+(\S+)\s+(/usr/local/\S+)", line)
        if not m:
            continue
        dest = m.group(2)
        for d in out:
            if dest.startswith(d + "/"):
                out[d].add(pathlib.PurePath(dest).name)
    return out


def referenced():
    """Basenames the deployed scripts read at runtime, per destination directory."""
    out = {d: set() for d in DIRS}
    for sh in sorted((ROOT / "deploy").glob("*.sh")):
        text = sh.read_text()
        for d, prefixes in DIRS.items():
            for p in prefixes:
                for m in re.finditer(re.escape(p) + r"/([A-Za-z0-9._-]+)", text):
                    out[d].add(m.group(1))
    return out


inst, refs = installed(), referenced()
bad = 0
for d in DIRS:
    missing = sorted(refs[d] - inst[d])
    print(f"  {d}: 引用 {len(refs[d])} 个，安装 {len(inst[d])} 个")
    for name in missing:
        print(f"    ✗ {name} 被引用但 install.sh 没有安装它")
        bad += 1

# install.sh 装了却没人用的不算错——status.sh 两台机器共用，
# 而这里只读 deploy/ 下的脚本。
sys.exit(1 if bad else 0)
