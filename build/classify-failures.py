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
# Order matters, certain first. `ERROR: ... failed (xxx phase)` always concerns
# this package, while `masked by: ... license` is printed for any package in the
# dependency graph a licence blocks. With the licence rule first, one blocked
# dependency filed a real build failure as a licence problem -- and that
# category prints a line ready to paste into excluded.txt.
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


def read_logs(d):
    """这一轮的失败日志。目录不存在时出声，不要装成没有失败。

    以 failed.txt 为准，不是把目录里的 *.log 都当成包。整体解析失败时那份
    whole.log 也在同一个目录，按文件名拆出来就成了一个叫 whole 的「包」，还会
    被印成可以贴进 excluded.txt 的一行——那份清单是永久生效的。
    """
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
    # 手工对着一个日志目录跑时没有 failed.txt，退回按文件名，但整体日志不算包
    return [p for p in sorted(d.glob("*.log")) if p.name != "whole.log"]


def main(logdir):
    d = pathlib.Path(logdir)
    logs = read_logs(d)
    if logs is None:
        # 路径打错和「这轮没有失败」原来外观完全相同，都是安静地退出 0。
        return 1
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
                # 至少两个空格，不靠固定宽度。validate.py 按 \s{2,} 或 tab
                # 切分，而 43 个字符的 atom 在 40 列对齐下分隔宽度是 0，贴进
                # excluded.txt 整行会被当成 cp。
                lines.append(f"{atom:<40s}  {why}")
    if lines:
        print("## 这几个每轮都会以同样方式失败，可以写进 build/excluded.txt：\n")
        for line in lines:
            print(f"  {line}")
        print()
    return 0



if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/log/binhost"))
