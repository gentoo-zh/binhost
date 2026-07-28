#!/usr/bin/env python3
"""The signing key fingerprint appears in several files and must agree everywhere.

It is written in the systemd unit that signs, on the setup page users verify
against, and in the rotation notes. Rotating the key means changing all of them,
and nothing said so until one of them was already stale.

Whitespace inside the fingerprint is how the site prints it for reading; it is
stripped before comparing.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if not (ROOT / "deploy").is_dir() or not (ROOT / "site").is_dir():
    # Only build/ is installed on the build machine. Repository-level test, runs in CI.
    print("  跳过：本机没有完整仓库")
    sys.exit(0)

# 40 hex characters, optionally in groups of four the way gpg prints them.
FPR = re.compile(r"\b((?:[0-9A-F]{4}[  ]?){9}[0-9A-F]{4})\b")

SKIP_DIRS = {".git", "node_modules"}
# The local trust key getuto generates on every machine is not this key, and
# example fingerprints in prose are not it either.
SKIP_FILES = {"build/test-fingerprint-consistent.py"}

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

# The fingerprint has to be in all three, not merely consistent wherever it
# happens to appear. Checking only for disagreement passed with the value
# deleted from the setup page, which is the one place users check it against.
REQUIRED = {
    "deploy/systemd/binhost-build.service",   # 签名时用的那个
    "site/index.html",                        # 用户拿来核对的那一份
    "docs/key-rotation.md",                   # 轮替时要一起改的清单
}

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
