#!/usr/bin/env python3
"""expand-slots turns a marked package into one atom per slot.

A bare atom builds only the newest slot, so a distribution kernel carried in
two slots would silently publish one of them. The expansion reads the slots
from the overlay so a version bump inside a slot needs no edit.
"""

import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build" / "expand-slots.py"

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


EBUILD = """EAPI=8
DESCRIPTION="t"
SLOT="{slot}"
KEYWORDS="~amd64"
"""


def overlay_with(d, versions):
    ov = d / "overlay"
    pkg = ov / "sys-kernel" / "demo-kernel"
    pkg.mkdir(parents=True)
    for v in versions:
        (pkg / f"demo-kernel-{v}.ebuild").write_text(EBUILD.format(slot=v))
    (pkg / "Manifest").write_text("")
    other = ov / "app-misc" / "plain"
    other.mkdir(parents=True)
    (other / "plain-1.ebuild").write_text(EBUILD.format(slot="0"))
    (other / "Manifest").write_text("")
    prof = ov / "profiles"
    prof.mkdir()
    (prof / "repo_name").write_text("gentoo-zh\n")
    (ov / "metadata").mkdir()
    (ov / "metadata" / "layout.conf").write_text(
        "masters = gentoo\nthin-manifests = true\nsign-manifests = false\n")
    tree = d / "gentoo"
    (tree / "profiles").mkdir(parents=True)
    (tree / "profiles" / "repo_name").write_text("gentoo\n")
    (tree / "profiles" / "categories").write_text("app-misc\nsys-kernel\n")
    return ov


def run(versions, marked="sys-kernel/demo-kernel\treason\n"):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        ov = overlay_with(d, versions)
        (d / "packages.txt").write_text("app-misc/plain\nsys-kernel/demo-kernel\n")
        (d / "all-slots.txt").write_text(marked)
        out = d / "atoms.txt"
        p = subprocess.run(
            [sys.executable, str(SCRIPT), str(d / "packages.txt"),
             str(d / "all-slots.txt"), str(ov), str(out)],
            capture_output=True, text=True,
            env={**os.environ, "GENTOO_TREE": str(d / "gentoo")})
        got = out.read_text().split() if out.exists() else []
        return p.returncode, got, p.stdout + p.stderr


rc, atoms, msg = run(["6.18.43", "7.1.7"])
check("两个 slot 展开成两个原子", rc == 0 and
      "sys-kernel/demo-kernel:6.18.43" in atoms and
      "sys-kernel/demo-kernel:7.1.7" in atoms, f"rc={rc} {atoms} {msg}")
check("展开后不再留下裸原子",
      bool(atoms) and "sys-kernel/demo-kernel" not in atoms, str(atoms))
check("没标记的包保持原样", "app-misc/plain" in atoms, str(atoms))

rc, atoms, _ = run(["7.1.7"])
check("只有一个 slot 时也带上 slot", atoms.count("sys-kernel/demo-kernel:7.1.7") == 1,
      str(atoms))

rc, atoms, msg = run(["6.18.43", "7.1.7"], marked="app-misc/absent\treason\n")
check("标记了不在清单中的包要报错", rc != 0 and "not in the package list" in msg,
      f"rc={rc} {msg}")

rc, atoms, msg = run(["6.18.43", "7.1.7"], marked="sys-kernel/demo-kernel\n")
check("没写理由要报错", rc != 0, f"rc={rc} {msg}")

sys.path.insert(0, str(ROOT / "build"))
import importlib.util
spec = importlib.util.spec_from_file_location("expand_slots", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

real_marked = ROOT / "build" / "all-slots.txt"
real_list = ROOT / "build" / "packages.txt"
if real_marked.exists():
    marked = mod.read_marked(real_marked)
    listed = {l.strip() for l in real_list.read_text().splitlines()
              if l.strip() and not l.strip().startswith("#")}
    check("仓库里的 all-slots.txt 解析得了", bool(marked), str(marked))
    missing = sorted(set(marked) - listed)
    check("它标记的包都在 packages.txt 里", not missing,
          "不在清单里：" + " ".join(missing))

print()
print("  slot 展开：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
