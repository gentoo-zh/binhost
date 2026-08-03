#!/usr/bin/env python3

import pathlib
import re
import sys

RULES = [
    ("构建失败", True,
     re.compile(r"^\s*\*\s*ERROR:.*failed \(\w+ phase\)", re.M)),
    ("取源失败", True,
     re.compile(r"Unable to fetch|Couldn't download", re.I)),
    ("许可证不允许再分发", False, None),
    ("被掩码或缺关键字", True,
     re.compile(r"have been masked|missing keyword", re.I)),
    ("依赖需要调整 USE", False,
     re.compile(r"The following USE changes are necessary", re.I)),
    ("依赖冲突", False,
     re.compile(r"slot conflict|Multiple package instances|REQUIRED_USE", re.I)),
]

USE_REQ = re.compile(r"^(>=?[a-z0-9-]+/\S+)\s+([a-z0-9_ -]+)$", re.M)


def evidence(text, kind):
    if kind == "依赖需要调整 USE":
        return [f"{a} {u}" for a, u in USE_REQ.findall(text)][:3]
    if kind == "许可证不允许再分发":
        m = re.search(r"^\s*- (\S+).*masked by: (.+?) license", text, re.M)
        return [f"{m.group(1)} — {m.group(2)}"] if m else []
    if kind == "构建失败":
        m = re.search(r"^\s*\*\s*(ERROR:.*failed \(\w+ phase\))", text, re.M)
        out = [m.group(1)] if m else []
        why = re.findall(r"^.*(?:configure: error|fatal error|No such file"
                         r"|command not found|is required).*$", text, re.M)
        return out + [w.strip()[:110] for w in why[:2]]
    return []


def license_blocks(text, cp):
    if cp is None:
        return bool(re.search(r"masked by:.*license", text, re.I))
    return bool(re.search(
        r"^\s*-\s*" + re.escape(cp) + r"-[^\s:]*::[^\s(]*\s*\(masked by:.*license",
        text, re.I | re.M))


def classify(text, cp=None):
    for kind, is_ebuild, pat in RULES:
        if pat is None:
            if license_blocks(text, cp):
                return kind, is_ebuild
        elif pat.search(text):
            return kind, is_ebuild
    return "未归类", True


def read_logs(d):
    d = pathlib.Path(d)
    if not d.is_dir():
        print(f"!! 日志目录不存在：{d}", file=sys.stderr)
        return None
    failed = d / "failed.txt"
    if failed.is_file():
        out = []
        for atom in failed.read_text().split():
            log = d / (atom.replace("/", "_", 1) + ".log")
            if log.is_file():
                out.append(log)
            else:
                print(f"!! {atom} 在 failed.txt 里，却没有对应的日志", file=sys.stderr)
        return out
    return [p for p in sorted(d.glob("*.log")) if p.name != "whole.log"]


def main(logdir):
    d = pathlib.Path(logdir)
    logs = read_logs(d)
    if logs is None:
        return 1
    if not logs:
        print(f"{d} 未产生日志")
        return 0

    groups = {}
    for p in logs:
        text = p.read_text(errors="replace")
        atom = p.stem.replace("_", "/", 1)
        kind, is_ebuild = classify(text, atom)
        groups.setdefault((is_ebuild, kind), []).append((atom, evidence(text, kind)))

    print(f"失败 {len(logs)} 个\n")

    permanent = {
        "许可证不允许再分发": "许可证不允许再分发",
        "被掩码或缺关键字": "在树里被掩码",
    }
    for is_ebuild in (True, False):
        for (e, kind), items in sorted(groups.items()):
            if e != is_ebuild:
                continue
            tag = "ebuild 需要修" if is_ebuild else "构建环境，不是 ebuild 的问题"
            print(f"## {kind}（{len(items)} 个）— {tag}")
            for atom, ev in items:
                print(f"  {atom}")
                for line in ev:
                    print(f"      {line}")
            print()

    lines = []
    for (e, kind), items in groups.items():
        if kind in permanent:
            for atom, ev in items:
                why = ev[0] if ev else permanent[kind]
                lines.append(f"{atom:<40s}  {why}")
    if lines:
        print("## 以下软件包在多个周期以相同原因失败，可以写进 build/excluded.txt：\n")
        for line in lines:
            print(f"  {line}")
        print()
    return 0



if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/log/binhost"))
