#!/usr/bin/env python3
"""Every script install.sh puts on the mirror must be tracked by status.sh.

status.sh decides whether the mirror is behind by matching changed paths
against TRACKED. A script that ships but is not listed there deploys silently:
the mirror keeps running the old copy and the daily check still reports it as
up to date.

The package lists are deliberately not tracked. They change with every
newcomer or retire pull request, so tracking them would report the mirror as
behind for a list the mirror rebuilds from git on its own.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INSTALL = ROOT / "deploy" / "install.sh"
STATUS = ROOT / "ops" / "status.sh"

UNTRACKED_ON_PURPOSE = {
    "build/packages.txt": "每个收录或退役 PR 都会改，追踪它会让镜像机长期报落后",
    "build/excluded.txt": "同上",
    "build/stable-excluded.txt": "同上",
}

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def shipped_to_mirror():
    """Repo file paths install.sh copies to the mirror.

    Matching only one top-level directory would silently lose coverage the
    moment a script moves elsewhere, so this takes any dir/file.ext operand.
    """
    text = INSTALL.read_text()
    block = re.search(r"^rsync -a deploy/(.*?)\"\$\{REMOTE\}", text,
                      re.S | re.M)
    if not block:
        return []
    return re.findall(r"[a-z][a-z0-9-]*/[A-Za-z0-9._-]+\.[A-Za-z0-9]+",
                      block.group(1))


def tracked_for(component):
    m = re.search(rf'^\s*{component}\)\s+TRACKED="([^"]+)"', STATUS.read_text(), re.M)
    return m.group(1).split() if m else []


shipped = shipped_to_mirror()
tracked = tracked_for("mirror")

check("读到了 install.sh 送往镜像机的档案", bool(shipped), str(shipped))
check("读到了 status.sh 的 mirror 追踪清单", bool(tracked), str(tracked))
if not (shipped and tracked):
    sys.exit(1)


def covered(path):
    return any(path == prefix or path.startswith(prefix + "/") for prefix in tracked)


for path in shipped:
    if path.endswith((".py", ".sh")):
        check(f"{path} 在追踪清单里", covered(path),
              "改动它不会判定镜像机落后；追踪清单：" + " ".join(tracked))

for path in shipped:
    if covered(path) or path in UNTRACKED_ON_PURPOSE:
        continue
    check(f"{path} 未被追踪且没有写明理由", False,
          "要么加进 status.sh 的 mirror 清单，要么写进本测试的 UNTRACKED_ON_PURPOSE")

for path, reason in UNTRACKED_ON_PURPOSE.items():
    check(f"{path} 的豁免仍然成立", path in shipped and not covered(path),
          f"{reason}；它已经不再送往镜像机或已被追踪，请移除这条豁免")

print()
print("  镜像机追踪清单：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
