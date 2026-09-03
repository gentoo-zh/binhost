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

import os
import pathlib
import re
import subprocess
import sys
import tempfile

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


def tracked_at_runtime(path):
    """Ask status.sh whether a deployed revision changing path is behind."""
    with tempfile.TemporaryDirectory() as raw:
        root = pathlib.Path(raw)
        bindir = root / "bin"
        bindir.mkdir()
        version = root / "VERSION"
        version.write_text("1" * 40)
        curl = bindir / "curl"
        curl.write_text(f"""#!/bin/sh
case "$*" in
  *'/commits/master'*) printf '  "sha": "{'2' * 40}",\\n' ;;
  *'/compare/'*) printf '      "filename": "{path}",\\n' ;;
  *) exit 22 ;;
esac
""")
        curl.chmod(0o755)
        env = os.environ.copy()
        env.update({
            "PATH": f"{bindir}:{env['PATH']}",
            "COMPONENT": "mirror",
            "VERSION_FILE": str(version),
            "SITE_WORK": str(root / "missing-site"),
            "SITE_DEST": str(root / "missing-public"),
            "SIGNING_GNUPGHOME": str(root / "missing-gnupg"),
            "HEARTBEAT": str(root / "missing-health"),
            "DISK_PATH": str(root),
        })
        result = subprocess.run(["bash", str(STATUS)], env=env,
                                capture_output=True, text=True)
        return "已变更" in result.stdout


shipped = shipped_to_mirror()
tracked = {path: tracked_at_runtime(path) for path in shipped}

check("读到了 install.sh 送往镜像机的文件", bool(shipped), str(shipped))
if not shipped:
    sys.exit(1)


for path in shipped:
    if path.endswith((".py", ".sh")):
        check(f"{path} 在追踪清单里", tracked[path],
              "status.sh 执行后没有把该路径的变更判定为落后")

for path in shipped:
    if tracked[path] or path in UNTRACKED_ON_PURPOSE:
        continue
    check(f"{path} 未被追踪且没有写明理由", False,
          "要么加进 status.sh 的 mirror 清单，要么写进本测试的 UNTRACKED_ON_PURPOSE")

for path, reason in UNTRACKED_ON_PURPOSE.items():
    check(f"{path} 的豁免仍然成立", path in shipped and not tracked[path],
          f"{reason}；它已经不再送往镜像机或已被追踪，请移除这条豁免")

print()
print("  镜像机追踪清单：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
