#!/usr/bin/env python3
import pathlib
import shutil
import subprocess
import sys
import tempfile

TOOL = pathlib.Path(__file__).resolve().parent.parent / "tools" / "gen-worlds.py"

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


with tempfile.TemporaryDirectory() as tmp:
    d = pathlib.Path(tmp)
    for sub in ("tools", "build", "builders/stable", "builders/unstable"):
        (d / sub).mkdir(parents=True)
    shutil.copy(TOOL, d / "tools")
    (d / "build/packages.txt").write_text("app-misc/b\napp-misc/A\napp-misc/c\n")
    (d / "build/stable-excluded.txt").write_text("# reason\n\napp-misc/c\t需要 ~amd64 依赖\n")
    (d / "builders/unstable/world-base").write_text("# tool\napp-portage/gentoolkit\n")
    (d / "builders/stable/world-base").write_text("# tool\napp-portage/gentoolkit\ndev-lang/python:3.13\n")

    def run(*args):
        return subprocess.run([sys.executable, str(d / "tools/gen-worlds.py"), *args],
                              capture_output=True, text=True)

    def world(channel):
        return (d / "builders" / channel / "world").read_text()

    p = run("--check")
    check("world 不存在时 --check 失败", p.returncode == 1, p.stdout + p.stderr)
    p = run()
    check("生成成功", p.returncode == 0, p.stdout + p.stderr)
    check("unstable = 清单 + world-base，不区分大小写排序",
          world("unstable") == "app-misc/A\napp-misc/b\napp-misc/c\napp-portage/gentoolkit\n", world("unstable"))
    check("stable 去掉排除的原子并加入 world-base",
          world("stable") == "app-misc/A\napp-misc/b\napp-portage/gentoolkit\ndev-lang/python:3.13\n",
          world("stable"))
    p = run("--check")
    check("与清单一致时 --check 通过", p.returncode == 0, p.stdout + p.stderr)

    (d / "builders/stable/world").write_text(world("stable") + "app-misc/extra\n")
    drifted = world("stable")
    p = run("--check")
    check("world 被改动时 --check 失败并指出频道",
          p.returncode == 1 and "builders/stable/world" in p.stdout, p.stdout + p.stderr)
    check("--check 不改写文件", world("stable") == drifted)

print()
print("  world 生成：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
