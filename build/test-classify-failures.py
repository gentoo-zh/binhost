#!/usr/bin/env python3
"""classify-failures.py 的用例。

它的输出里有一段是「可以贴进 excluded.txt」的行，那份清单永久生效，所以这里
要确认的是：不该出现在里面的条目不会出现。
"""
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

# --- 整体日志不是包 -------------------------------------------------------------
# 整体解析失败时 whole.log 和逐包日志在同一个目录，按文件名拆出来就成了一个叫
# whole 的包，还会被印成可以贴进 excluded.txt 的一行。
out, _ = run({"failed.txt": "app-misc/aichat\n",
              "app-misc_aichat.log": MASKED,
              "whole.log": MASKED})
check("whole.log 不算一个包", "whole" not in out, out)
check("失败数不把它算进去", "失败 1 个" in out, out)
check("真的那个还在", "app-misc/aichat" in out, out)

# 手工跑一个日志目录时没有 failed.txt，也不能把整体日志当成包
out, _ = run({"app-misc_aichat.log": MASKED, "whole.log": MASKED})
check("没有 failed.txt 时同样不算", "whole" not in out, out)

# --- failed.txt 说了算 ----------------------------------------------------------
# 上一轮留下的日志没清掉时，不该跟着这一轮一起报
out, _ = run({"failed.txt": "app-misc/aichat\n",
              "app-misc_aichat.log": MASKED,
              "net-misc_stale.log": BUILD})
check("不在 failed.txt 里的日志不报", "stale" not in out, out)

# 反过来，failed.txt 里有而日志没了要出声，不能装作没失败
out, err = run({"failed.txt": "app-misc/aichat\nnet-misc/gone\n",
                "app-misc_aichat.log": MASKED})
check("日志缺了会出声", "net-misc/gone" in err, err)

# --- 分类本身 -------------------------------------------------------------------
out, _ = run({"failed.txt": "net-misc/x\n", "net-misc_x.log": BUILD})
check("构建失败归到 ebuild 要修", "构建失败" in out and "ebuild 需要修" in out, out)
check("构建失败不进 excluded.txt 那段",
      "excluded.txt" not in out or "net-misc/x " not in out.split("excluded.txt")[-1], out)

print(f"\n  {failed} 项不通过" if failed else "\n  失败分类：全部通过")
sys.exit(1 if failed else 0)
