#!/usr/bin/env python3

import pathlib
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
if not (ROOT / "deploy").is_dir() or not (ROOT / "site").is_dir():
    print("  跳过：本机没有完整仓库")
    sys.exit(0)

FPR = re.compile(r"\b((?:[0-9A-F]{4}[ 　]?){9}[0-9A-F]{4})\b")

SKIP_DIRS = {".git", "node_modules"}
SKIP_FILES = {"build/test-fingerprint-consistent.py",
              "build/test-shell-behaviour.sh"}

ASC = ROOT / "site" / "gentoo-zh-binhost.asc"
SERVICE = "deploy/systemd/binhost-build.service"
REQUIRED = {SERVICE, "site/index.html", "docs/key-rotation.md"}

bad = 0


def fail(msg):
    global bad
    print(f"!!! {msg}", file=sys.stderr)
    bad = 1


def mentions():
    out = {}
    asc_rel = str(ASC.relative_to(ROOT))
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or any(d in p.parts for d in SKIP_DIRS):
            continue
        rel = str(p.relative_to(ROOT))
        if rel in SKIP_FILES or rel == asc_rel:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for m in FPR.findall(text):
            out.setdefault(m.replace(" ", "").replace("　", ""), []).append(rel)
    return out


def published():
    out = {}
    run = subprocess.run(["gpg", "--with-colons", "--show-keys", str(ASC)],
                         capture_output=True, text=True)
    primary = None
    for line in run.stdout.splitlines():
        f = line.split(":")
        if f[0] in ("pub", "sub"):
            primary = f if f[0] == "pub" else None
        elif f[0] == "fpr" and primary is not None:
            out[f[9]] = {"validity": primary[1], "expires": primary[6],
                         "caps": primary[11]}
            primary = None
    return out


if not ASC.exists():
    fail(f"{ASC} 不存在")
    sys.exit(1)

found = mentions()
if not found:
    fail("仓库里一个指纹都没有")
    sys.exit(1)

signing = sorted(f for f, files in found.items() if SERVICE in files)
if len(signing) != 1:
    fail(f"{SERVICE} 里应当只有一个指纹，实际 {len(signing)} 个")

if not shutil.which("gpg"):
    print("  本机没有 gpg，读不到 .asc，只比对文本里的指纹是否一致")
    if len(found) > 1:
        fail(f"出现 {len(found)} 个不同的指纹，轮替时漏改了某一处")
    sys.exit(1 if bad else 0)

keys = published()
if not keys:
    fail(f"{ASC.name} 解析不出任何公钥")
    sys.exit(1)

print(f"  {ASC.name} 发布了 {len(keys)} 把公钥：")
for f, k in sorted(keys.items()):
    if k["expires"]:
        days = (int(k["expires"]) - time.time()) / 86400
        if days < 0:
            left = f"，已过期 {-days:.0f} 天"
            fail(f"{f[:8]} 已经过期，不该还留在 {ASC.name} 里")
        else:
            left = f"，{days:.0f} 天后过期"
    else:
        left = "，无过期时间"
    state = "已撤销" if k["validity"] == "r" else k["caps"]
    print(f"    {f}  {state}{left}")

for f in sorted(set(found) - set(keys)):
    fail(f"{f[:8]} 写在下面这些地方，但 {ASC.name} 里没有这把公钥：\n      "
         + "\n      ".join(sorted(set(found[f]))))

if len(signing) == 1:
    key = keys.get(signing[0])
    if key and key["validity"] == "r":
        fail(f"{SERVICE} 指定的 {signing[0][:8]} 已撤销")
    if key and "S" not in key["caps"].upper():
        fail(f"{SERVICE} 指定的 {signing[0][:8]} 没有签名能力")
    for f in sorted(REQUIRED - set(found[signing[0]]) - {SERVICE}):
        fail(f"{f} 里没有正在签名的那把 {signing[0][:8]}")

if len(keys) > 1:
    print(f"\n  注意：{ASC.name} 里有 {len(keys)} 把公钥，这是轮替重叠期的状态，"
          f"重叠期结束后按 docs/key-rotation.md 第五步去掉旧的那把。")

sys.exit(1 if bad else 0)
