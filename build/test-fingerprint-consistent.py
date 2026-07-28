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

if not found:
    print("  仓库里没有指纹，跳过")
    sys.exit(0)

for fpr, files in sorted(found.items()):
    print(f"  {fpr}")
    for f in sorted(set(files)):
        print(f"    {f}")

if len(found) > 1:
    print(f"\n!!! 出现 {len(found)} 个不同的指纹，轮替时漏改了某一处", file=sys.stderr)
    sys.exit(1)
print(f"\n  一致，出现在 {len(set(sum(found.values(), [])))} 个文件里")
