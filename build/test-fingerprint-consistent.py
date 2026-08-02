#!/usr/bin/env python3

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if not (ROOT / "deploy").is_dir() or not (ROOT / "site").is_dir():
    print("  跳过：本机没有完整仓库")
    sys.exit(0)

FPR = re.compile(r"\b((?:[0-9A-F]{4}[  ]?){9}[0-9A-F]{4})\b")

SKIP_DIRS = {".git", "node_modules"}
SKIP_FILES = {"build/test-fingerprint-consistent.py",
              "build/test-shell-behaviour.sh"}

found = {}
for p in sorted(ROOT.rglob("*")):
    if not p.is_file() or any(d in p.parts for d in SKIP_DIRS):
        continue
    rel = str(p.relative_to(ROOT))
    if rel in SKIP_FILES:
        continue
    try:
        text = p.read_text(errors="ignore")
    except OSError:
        continue
    for m in FPR.findall(text):
        norm = m.replace(" ", "").replace(" ", "")
        found.setdefault(norm, []).append(rel)

REQUIRED = {
    "deploy/systemd/binhost-build.service",
    "site/index.html",
    "docs/key-rotation.md",
}

ASC = ROOT / "site" / "gentoo-zh-binhost.asc"
if ASC.exists():
    import shutil
    import subprocess
    if shutil.which("gpg"):
        out = subprocess.run(
            ["gpg", "--with-colons", "--show-keys", str(ASC)],
            capture_output=True, text=True).stdout
        blob = {l.split(":")[9] for l in out.splitlines() if l.startswith("fpr:")}
        if not blob:
            print(f"!!! {ASC.name} 解析不出任何指纹", file=sys.stderr)
            sys.exit(1)
        for f in sorted(blob):
            found.setdefault(f, []).append("site/gentoo-zh-binhost.asc")
        print(f"  {ASC.name} 里的指纹：{', '.join(sorted(blob))}")
    else:
        print("  跳过公钥解析：本机没有 gpg")
else:
    print(f"!!! {ASC} 不存在", file=sys.stderr)
    sys.exit(1)

if not found:
    print("!!! 仓库里一个指纹都没有", file=sys.stderr)
    sys.exit(1)

for fpr, files in sorted(found.items()):
    print(f"  {fpr}")
    for f in sorted(set(files)):
        print(f"    {f}")

bad = 0
if len(found) > 1:
    print(f"\n!!! 出现 {len(found)} 个不同的指纹，轮替时漏改了某一处", file=sys.stderr)
    bad = 1

carriers = set(sum(found.values(), []))
for f in sorted(REQUIRED - carriers):
    print(f"!!! {f} 里没有指纹", file=sys.stderr)
    bad = 1
if bad:
    sys.exit(1)
print(f"\n  一致，出现在 {len(set(sum(found.values(), [])))} 个文件里")
