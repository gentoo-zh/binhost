#!/usr/bin/env python3
"""The container must build for the x86-64 baseline, not for the build host.

Published packages carry whatever CPU_FLAGS_X86 the container resolved. The
site offers them as x86-64, so a flag beyond the baseline would hand out
binaries that fault on the machines the baseline exists for. Leaving the
variable unset makes that depend on the profile default rather than on a
decision in this repository.
"""

import pathlib
import re
import sys

ROOT = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else
        pathlib.Path(__file__).resolve().parent.parent)
IMAGE = ROOT / "build" / "base-image.sh"

# x86-64 mandates these; anything further is a later instruction set.
BASELINE = {"mmx", "sse", "sse2"}

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


text = IMAGE.read_text()
make_conf = text.split("cat >> /etc/portage/make.conf <<EOF", 1)[1] \
    .split("\nEOF", 1)[0]

m = re.search(r'^CPU_FLAGS_X86="([^"]*)"', make_conf, re.M)
check("容器 make.conf 明确设定 CPU_FLAGS_X86", m is not None,
      "没有设定就取决于 profile 默认值，本仓库无从保证")

if m:
    flags = set(m.group(1).split())
    check("设定的值不超出 x86-64 baseline", flags <= BASELINE,
          f"超出的部分：{sorted(flags - BASELINE)}")
    check("baseline 本身没有被削减", flags == BASELINE,
          f"缺少：{sorted(BASELINE - flags)}")

common = re.search(r'^CFLAGS="([^"]*)"$', make_conf, re.M)
march = re.search(r'(?:^|\s)-march=([A-Za-z0-9_-]+)(?:\s|$)',
                  common.group(1)) if common else None
check("编译目标仍是 x86-64", march is not None and march.group(1) == "x86-64",
      f"实际：{march.group(1) if march else 'CFLAGS 未设定 -march'}")

print()
print("  baseline：全部通过" if not failed else f"  {failed} 项不通过")
sys.exit(1 if failed else 0)
