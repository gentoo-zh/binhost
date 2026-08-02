#!/usr/bin/env python3
import pathlib
import subprocess
import sys
import tempfile

SCRIPT = pathlib.Path(__file__).with_name("add-package.py")

failed = 0


def check(name, cond, detail=""):
    global failed
    if cond:
        print(f"  ✓ {name}")
        return
    print(f"  ✗ {name}" + (f"\n      {detail}" if detail else ""))
    failed += 1


def run(lines, atom):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        script = d / "add-package.py"
        script.write_text(SCRIPT.read_text())
        (d / "packages.txt").write_text("\n".join(lines) + "\n")
        p = subprocess.run([sys.executable, str(script), atom],
                           capture_output=True, text=True)
        return p.returncode, (d / "packages.txt").read_text().split("\n"), p.stdout + p.stderr


BASE = ["app-misc/aaa", "net-misc/geo", "net-proxy/bore", "net-proxy/Xray",
        "sys-apps/pacman"]

rc, out, _ = run(BASE, "net-misc/zzz")
check("插在同一分类的末尾", out[:5] == ["app-misc/aaa", "net-misc/geo", "net-misc/zzz",
                                       "net-proxy/bore", "net-proxy/Xray"], out)

rc, out, _ = run(BASE, "app-misc/bbb")
check("插在正确位置", out[1] == "app-misc/bbb", out)

rc, out, _ = run(BASE, "net-misc/zzz")
check("其余各行原样不动", [l for l in out if l and l != "net-misc/zzz"] == BASE, out)

rc, out, _ = run(BASE, "net-proxy/Xray")
check("已经在清单里就不重复加", out[:-1] == BASE and rc == 0, out)

rc, out, msg = run(BASE, "not-an-atom")
check("不是 category/package 就拒绝", rc != 0, msg)
check("拒绝时不改文件", [l for l in out if l] == BASE, out)

rc, out, _ = run(BASE, "net-proxy/Yray")
check("大写不被按字节排到前面",
      out.index("net-proxy/Yray") > out.index("net-proxy/bore"), out)

rc, out, _ = run(BASE, "zzz-last/pkg")
check("排在最后的也接得上", out[-2] == "zzz-last/pkg", out)

rc, out, _ = run(BASE, "aaa-first/pkg")
check("排在最前的也接得上", out[0] == "aaa-first/pkg", out)

rc, out, _ = run(BASE, "net-misc/zzz")
check("末尾只有一个换行", out[-1] == "" and out[-2] != "", repr(out[-3:]))

print(f"\n  {failed} 项不通过" if failed else "\n  add-package：全部通过")
sys.exit(1 if failed else 0)
