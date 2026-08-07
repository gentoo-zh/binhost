#!/usr/bin/env python3
"""The download staging directory must share a filesystem with the distfiles.

emirrordist finishes a download by renaming it into place. Across devices that
rename fails, and portage's fallback in 3.0.81.2 raises TypeError instead, so
the whole round dies with a traceback that says nothing about the real cause.
The mirror hit this the moment /srv became its own partition.
"""

import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SYNC = ROOT / "deploy" / "distfiles-sync.sh"

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


text = SYNC.read_text()

check("--temp-dir 用的是 TEMP_DIR，而不是 STATE 下的子目录",
      '--temp-dir "${TEMP_DIR}"' in text,
      "STATE 默认在 /var/lib，与 /srv 上的 distfiles 不同设备")
check("TEMP_DIR 默认取 distfiles 所在的挂载点",
      'df -P "${DEST%/*}"' in text,
      "写死路径会在别的布局上重新引入跨设备问题")
check("落地前比较两者的设备号",
      re.search(r'stat -c %d "\$\{TEMP_DIR\}".*stat -c %d "\$\{DEST\}"',
                text, re.S) is not None,
      "缺少该比较时，跨设备只会得到 portage 的 TypeError")


def run_guard(same_device):
    """Run only the guard, with TEMP_DIR forced on or off the DEST filesystem."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        dest = d / "pub" / "distfiles"
        dest.mkdir(parents=True)
        temp = (d / "staging") if same_device else pathlib.Path("/dev/shm/exdev-probe")
        temp.mkdir(parents=True, exist_ok=True)
        guard = re.search(
            r'if \[\[ \$\(stat -c %d "\$\{TEMP_DIR\}"\).*?\nfi\n', text, re.S)
        if not guard:
            return None
        script = (f'set -euo pipefail\nDEST={dest}\nTEMP_DIR={temp}\n'
                  + guard.group(0))
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        return p.returncode, p.stderr


same = run_guard(True)
check("同设备时放行", same is not None and same[0] == 0,
      "" if same is None else same[1])

cross = run_guard(False)
if cross is None:
    check("跨设备时中止", False, "没能从脚本里取出这段检查")
elif cross[0] == 0 and pathlib.Path("/dev/shm").exists():
    check("跨设备时中止", False, "/dev/shm 与临时目录同设备，本机无法构造跨设备场景")
else:
    check("跨设备时中止并说明原因",
          cross[0] != 0 and "同一个文件系统" in cross[1], cross[1])

print()
print("  暂存目录设备：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
