#!/usr/bin/env python3
"""把构建失败分成「ebuild 要修」和「构建环境要调」两类。

判定顺序是有意的，日志里常常几种迹象同时出现：
  - 许可证被挡的包，日志里也写着 "have been masked"
  - 依赖要调 USE 时，portage 会先打印完整的构建列表，看起来像正常构建
  - 真正的构建失败在最后才 "ERROR: ... failed (xxx phase)"
所以从最具体的证据往下匹配，第一条命中即止。
"""

import pathlib
import re
import sys

# (类别, 是不是 ebuild 的问题, 正则)
#
# 顺序有讲究：先看确凿的，再看可能指向别人的。
#
# 「ERROR: … failed (xxx phase)」说的一定是本包，而「masked by: … license」
# emerge 会为依赖图里任何被许可证挡住的包打印，不限于失败的那一个。许可证
# 那条原先排在最前又比对整份日志，于是一个依赖被许可证挡住，就能让真正的
# 构建失败被归成「许可证不允许再分发」——而这一类会直接印成可以写进
# excluded.txt 的成品行，照抄就是用错误理由永久排除一个包。
RULES = [
    ("构建失败", True,
     re.compile(r"^\s*\*\s*ERROR:.*failed \(\w+ phase\)", re.M)),
    ("取源失败", True,
     re.compile(r"Unable to fetch|Couldn't download", re.I)),
    ("许可证不允许再分发", False, None),   # 见 classify()，要指向本包才算
    ("被掩码或缺关键字", True,
     re.compile(r"have been masked|missing keyword", re.I)),
    # 下面两类是我们这边的环境，不是 ebuild 写错
    ("依赖需要调整 USE", False,
     re.compile(r"The following USE changes are necessary", re.I)),
    ("依赖冲突", False,
     re.compile(r"slot conflict|Multiple package instances|REQUIRED_USE", re.I)),
]

# 需要调 USE 时，portage 把要求写成「原子 + 空格 + USE 名」，
# 前面几行是 "# required by ..."。取这一行当证据，比截 ERROR 行有用。
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
        # configure/编译的真正原因通常在 ERROR 之前
        why = re.findall(r"^.*(?:configure: error|fatal error|No such file"
                         r"|command not found|is required).*$", text, re.M)
        return out + [w.strip()[:110] for w in why[:2]]
    return []


# 许可证那条要求被挡的原子就是本包，形如：
#   - app-misc/crush-1.0::gentoo-zh (masked by: FSL-1.1-MIT license(s))
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


def main(logdir):
    d = pathlib.Path(logdir)
    logs = sorted(p for p in d.glob("*.log"))
    if not logs:
        print(f"{d} 里没有日志")
        return 0

    groups = {}
    for p in logs:
        text = p.read_text(errors="replace")
        atom = p.stem.replace("_", "/", 1)
        kind, is_ebuild = classify(text, atom)
        groups.setdefault((is_ebuild, kind), []).append((atom, evidence(text, kind)))

    print(f"失败 {len(logs)} 个\n")

    # 结论稳定的那几类每轮都会以同样的方式失败。把可以直接贴进 excluded.txt
    # 的行打出来，避免每次翻日志重新判断一遍。
    permanent = {
        "许可证不允许再分发": "许可证不允许再分发",
        "被掩码或缺关键字": "在树里被掩码",
    }
    # ebuild 的问题排前面：那些才需要有人去改
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
                lines.append(f"{atom:<40s}{why}")
    if lines:
        print("## 这几个每轮都会以同样方式失败，可以写进 build/excluded.txt：\n")
        for line in lines:
            print(f"  {line}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/log/binhost"))
