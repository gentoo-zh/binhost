#!/usr/bin/env python3
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE / "classify-failures.py"

failed = 0


def check(name, cond, detail=""):
    global failed
    if cond:
        print(f"  ✓ {name}")
        return
    print(f"  ✗ {name}" + (f"\n      {detail}" if detail else ""))
    failed += 1


def run(files):
    d = pathlib.Path(tempfile.mkdtemp())
    for name, body in files.items():
        (d / name).write_text(body)
    r = subprocess.run([sys.executable, str(SCRIPT), str(d)],
                       capture_output=True, text=True)
    return r.stdout, r.stderr


MASKED = "!!! All ebuilds that could satisfy this have been masked\n"
BUILD = " * ERROR: net-misc/x-1::gentoo-zh failed (compile phase)\n"

out, _ = run({"failed.txt": "app-misc/aichat\n",
              "app-misc_aichat.log": MASKED,
              "whole.log": MASKED})
check("whole.log 不算一个包", "whole" not in out, out)
check("失败数不把它算进去", "失败 1 个" in out, out)
check("真的那个还在", "app-misc/aichat" in out, out)

out, _ = run({"app-misc_aichat.log": MASKED, "whole.log": MASKED})
check("没有 failed.txt 时同样不算", "whole" not in out, out)

out, _ = run({"failed.txt": "app-misc/aichat\n",
              "app-misc_aichat.log": MASKED,
              "net-misc_stale.log": BUILD})
check("不在 failed.txt 里的日志不报", "stale" not in out, out)

out, err = run({"failed.txt": "app-misc/aichat\nnet-misc/gone\n",
                "app-misc_aichat.log": MASKED})
check("日志缺了会出声", "net-misc/gone" in err, err)

out, _ = run({"failed.txt": "net-misc/x\n", "net-misc_x.log": BUILD})
check("构建失败归到 ebuild 要修", "构建失败" in out and "ebuild 需要修" in out, out)
check("构建失败不进 excluded.txt 那段",
      "excluded.txt" not in out or "net-misc/x " not in out.split("excluded.txt")[-1], out)

print(f"\n  {failed} 项不通过" if failed else "\n  失败分类：全部通过")
sys.exit(1 if failed else 0)
