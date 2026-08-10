#!/usr/bin/env python3
import pathlib
import subprocess
import sys
import tempfile

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"

SCRIPT = TOOLS / "retire-package.py"

BASE = ["app-misc/aaa", "net-misc/geo", "net-proxy/bore", "sys-apps/pacman"]
EXCL = "# 不收录的包和原因\napp-misc/old\t上游停更\n"
STABLE = "# stable 不构建\nnet-misc/geo\t依赖只有测试关键字\nsys-apps/pacman\t其他原因\n"
GONE = "overlay 中已不存在该软件包"

failed = 0


def check(name, cond, detail=""):
    global failed
    if cond:
        print(f"  ✓ {name}")
        return
    print(f"  ✗ {name}" + (f"\n      {detail}" if detail else ""))
    failed += 1


def run(*args, excluded=EXCL, listed=BASE, stable=STABLE):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "tools").mkdir()
        (d / "build").mkdir()
        script = d / "tools" / "retire-package.py"
        script.write_text(SCRIPT.read_text())
        lst = d / "build" / "packages.txt"
        exc = d / "build" / "excluded.txt"
        stable_exc = d / "build" / "stable-excluded.txt"
        lst.write_text("\n".join(listed) + "\n")
        exc.write_text(excluded)
        stable_exc.write_text(stable)
        p = subprocess.run([sys.executable, str(script), *args],
                           capture_output=True, text=True)
        return (p.returncode, lst.read_text(), exc.read_text(), stable_exc.read_text(),
                p.stdout + p.stderr)


rc, lst, exc, stable, msg = run("net-misc/geo", GONE)
check("overlay 中不存在的只从清单移除", rc == 0 and "net-misc/geo" not in lst, msg)
check("overlay 中不存在的不写进 excluded", "net-misc/geo" not in exc, exc)
check("退役时同步移出 stable 排除清单",
      "net-misc/geo" not in stable and "sys-apps/pacman" in stable, stable)

rc, lst, exc, stable, msg = run("net-proxy/bore", "overlay 的 package.mask 屏蔽了它")
check("其他原因也从清单删", rc == 0 and "net-proxy/bore" not in lst, msg)
check("其他原因连同原因写进 excluded",
      exc.endswith("net-proxy/bore\toverlay 的 package.mask 屏蔽了它\n"), exc)

rc, lst, exc, stable, msg = run("app-misc/aaa", "原因",
                                excluded="# 头\napp-misc/aaa\t早先写过的原因\n")
check("excluded 里已经有就不重复写一行", exc.count("app-misc/aaa") == 1, exc)
check("已经在 excluded 里也要退出清单", "app-misc/aaa" not in lst, lst)

rc, lst, exc, stable, msg = run("app-misc/aaa", "原因", excluded="# 头\napp-misc/old\t原因")
check("excluded 末尾没换行也不跟前一行粘连",
      exc == "# 头\napp-misc/old\t原因\napp-misc/aaa\t原因\n", repr(exc))

rc, lst, exc, stable, msg = run("app-misc/nope", "原因")
check("不在清单里就拒绝", rc != 0, msg)
check("不在清单里给的是一句话不是 traceback",
      "不在清单里" in msg and "Traceback" not in msg, msg)
check("拒绝时清单不动", lst == "\n".join(BASE) + "\n", lst)
check("拒绝时 excluded 不动", exc == EXCL, exc)
check("拒绝时 stable 排除清单不动", stable == STABLE, stable)

BAD = "../../etc/passwd"
rc, lst, exc, stable, msg = run(BAD, "原因", listed=[BAD] + BASE)
check("不是 category/package 就拒绝，哪怕清单里真有这一行", rc != 0, msg)
check("非法名字不改任何文件",
      lst == "\n".join([BAD] + BASE) + "\n" and exc == EXCL, lst)

rc, lst, exc, stable, msg = run("app-misc/aaa", "   ")
check("空原因就拒绝", rc != 0, msg)
check("空原因不改清单", lst == "\n".join(BASE) + "\n", lst)

rc, lst, exc, stable, msg = run("app-misc/aaa")
check("参数少了就拒绝", rc != 0, msg)

rc, lst, exc, stable, msg = run("net-misc/geo", GONE)
check("其余各行原样不动",
      [l for l in lst.splitlines() if l] == [c for c in BASE if c != "net-misc/geo"], lst)
check("清单末尾只有一个换行", lst.endswith("\n") and not lst.endswith("\n\n"), repr(lst[-4:]))

print(f"\n  {failed} 项不通过" if failed else "\n  retire-package：全部通过")
sys.exit(1 if failed else 0)
