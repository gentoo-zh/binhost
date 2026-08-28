#!/usr/bin/env python3
"""Only a package the overlay masks in full is dropped from the build list."""

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build" / "drop_masked.py"

MASK = """\
# Comment line, ignored.
dev-libs/gone
=media-libs/partly-2.0
~net-misc/tilde-1.5
=app-misc/edge-0
app-misc/also-gone
"""

LIST = """\
app-misc/also-gone
app-misc/edge
app-misc/kept
dev-libs/gone
media-libs/partly
net-misc/tilde
"""

total = fail = 0


def ok(name, got, want):
    global fail, total
    total += 1
    if got == want:
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name}\n      得到 {got!r}\n      应为 {want!r}")


with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    overlay = d / "overlay"
    (overlay / "profiles").mkdir(parents=True)
    (overlay / "profiles" / "package.mask").write_text(MASK)
    src = d / "packages.txt"
    src.write_text(LIST)
    out = d / "out" / "unmasked.txt"

    r = subprocess.run([sys.executable, str(SCRIPT), str(src), str(overlay), str(out)],
                       capture_output=True, text=True)
    ok("退出码 0", r.returncode, 0)
    kept = out.read_text().splitlines()

    # A bare atom masks every version, so the package cannot be built at all.
    ok("整包屏蔽的被剔除", "dev-libs/gone" in kept, False)
    ok("第二个整包屏蔽的也被剔除", "app-misc/also-gone" in kept, False)

    # A versioned mask leaves other versions buildable; emerge picks one.
    ok("只屏蔽某个版本的保留", "media-libs/partly" in kept, True)
    ok("波浪号屏蔽的保留", "net-misc/tilde" in kept, True)

    ok("没被屏蔽的保留", "app-misc/kept" in kept, True)
    # =app-misc/edge-0 masks one version. Asking whether some fixed version is
    # masked, rather than whether the bare atom is present, would drop this one.
    ok("屏蔽了 0 版的包仍保留", "app-misc/edge" in kept, True)
    ok("保留顺序不变", kept,
       ["app-misc/edge", "app-misc/kept", "media-libs/partly", "net-misc/tilde"])

    # The dropped ones have to be named, otherwise a package silently leaves
    # the channel and nobody knows to put it in excluded.txt.
    ok("剔除的包印出来了",
       all(p in r.stdout for p in ("dev-libs/gone", "app-misc/also-gone")), True)
    ok("提示补 excluded.txt", "excluded.txt" in r.stdout, True)
    ok("统计行", ">>> 4 packages (2 masked)" in r.stdout, True)

    # No mask file at all is the common case for a plain overlay checkout.
    bare = d / "bare"
    (bare / "profiles").mkdir(parents=True)
    out2 = d / "out" / "second.txt"
    r2 = subprocess.run([sys.executable, str(SCRIPT), str(src), str(bare), str(out2)],
                        capture_output=True, text=True)
    ok("没有 package.mask 时全部保留", out2.read_text().splitlines(),
       LIST.splitlines())
    ok("那种情况退出码也是 0", r2.returncode, 0)

print()
if fail:
    print(f">>> {fail} 项不过")
    sys.exit(1)
print(f">>> {total} 项全过")
