#!/usr/bin/env python3
import pathlib
import subprocess
import sys
import tempfile

CHECK = str(pathlib.Path(__file__).resolve().parent.parent / "tools" / "check-world.py")

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
    (d / "tree" / "app-misc" / "present").mkdir(parents=True)
    (d / "tree" / "app-misc" / "present" / "present-1.ebuild").touch()

    def run(*atoms):
        (d / "world").write_text("".join(a + "\n" for a in atoms))
        return subprocess.run([sys.executable, CHECK, str(d / "world"), "--tree", str(d / "tree")],
                              capture_output=True, text=True)

    p = run("app-misc/present", "app-misc/absent")
    check("没有 ebuild 的原子使检查失败并被列出",
          p.returncode == 1 and "app-misc/absent" in p.stdout, p.stdout + p.stderr)
    p = run("app-misc/present:1")
    check("原子都有 ebuild 时检查通过", p.returncode == 0, p.stdout + p.stderr)

print()
print("  world 原子检查：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
