#!/usr/bin/env python3
"""Sort build failures into ones an ebuild must fix and ones the build
environment must.

判定顺序是有意的，日志里常常几种迹象同时出现：
  - 许可证被挡的包，日志里也写着 "have been masked"
  - 依赖要调 USE 时，portage 会先打印完整的构建列表，看起来像正常构建
  - 真正的构建失败在最后才 "ERROR: ... failed (xxx phase)"
所以从最具体的证据往下匹配，第一条命中即止。
"""

import pathlib
import re
import sys

# (category, is it the ebuild's problem, pattern)
#
# The order matters: what is certain first, what may point at someone else
# after.
#
# `ERROR: ... failed (xxx phase)` always concerns this package, while
# `masked by: ... license` is printed by emerge for any package in the
# dependency graph a licence blocks, not only the one that failed. The licence
# rule used to come first and match the whole log, so one blocked dependency
# was enough to file a real build failure under a licence problem -- and that
# category is printed as a line ready to paste into excluded.txt, which would
# exclude a package permanently for the wrong reason.
RULES = [
    ("构建失败", True,
     re.compile(r"^\s*\*\s*ERROR:.*failed \(\w+ phase\)", re.M)),
    ("取源失败", True,
     re.compile(r"Unable to fetch|Couldn't download", re.I)),
    ("许可证不允许再分发", False, None),   # 见 classify()，要指向本包才算
    ("被掩码或缺关键字", True,
     re.compile(r"have been masked|missing keyword", re.I)),
    # The next two are our environment, not a mistake in the ebuild
    ("依赖需要调整 USE", False,
     re.compile(r"The following USE changes are necessary", re.I)),
    ("依赖冲突", False,
     re.compile(r"slot conflict|Multiple package instances|REQUIRED_USE", re.I)),
]

# For a USE change portage writes the requirement as atom, space, USE name,
# with "# required by ..." on the lines above. That line makes better evidence
# than the ERROR line.
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
        # The real reason for a configure or compile failure is usually above
        # the ERROR line
        why = re.findall(r"^.*(?:configure: error|fatal error|No such file"
                         r"|command not found|is required).*$", text, re.M)
        return out + [w.strip()[:110] for w in why[:2]]
    return []


# The licence rule requires the blocked atom to be this package, as in:
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

    # The categories whose conclusion is stable fail the same way every round.
    # Print the line ready to paste into excluded.txt so nobody has to read the
    # logs and decide again.
    permanent = {
        "许可证不允许再分发": "许可证不允许再分发",
        "被掩码或缺关键字": "在树里被掩码",
    }
    # Ebuild problems first: those are the ones somebody has to act on
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
