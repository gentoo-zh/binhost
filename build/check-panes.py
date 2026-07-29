#!/usr/bin/env python3
"""手动配置与快速配置写的必须是同一份东西。

一页上同一份配置有两种写法，改了一边忘了另一边，页面看着仍然正常，照着抄的人
拿到的却是旧的。这里要求手动那份的每一行都能在快速那份里找到。

快速那份还多出命令行（cat、mkdir、EOF），所以是单向包含，不是逐字相等。
"""
import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRE = re.compile(r'<pre[^>]*>(.*?)</pre>', re.S)
PANE = re.compile(r'<div[^>]*data-pane="(\w+)"(?![^>]*class="mode")')


def text(pre):
    return [l.rstrip() for l in html.unescape(re.sub(r"<[^>]+>", "", pre)).split("\n") if l.strip()]


def panes(t):
    """按 data-pane 的容器切开，取每一段里的 <pre>。"""
    out = {"manual": [], "quick": []}
    for m in PANE.finditer(t):
        name = m.group(1)
        if name not in out:
            continue
        # 到下一个同层 data-pane 或大标题为止，够用且不必真的解析 HTML
        end = t.find('data-pane=', m.end())
        seg = t[m.start():end if end > 0 else len(t)]
        for p in PRE.findall(seg):
            out[name].append(text(p))
    return out


def main():
    bad = []
    for f in sorted((ROOT / "site").glob("*.html")):
        t = f.read_text()
        p = panes(t)
        if not p["quick"]:
            continue
        quick = {l for block in p["quick"] for l in block}
        if not p["manual"]:
            bad.append(f"{f.name}: 有快速配置却没有手动配置")
        for block in p["manual"]:
            for line in block:
                if line not in quick:
                    bad.append(f"{f.name}: 手动配置里的这一行在快速配置里找不到：{line}")
    for b in bad:
        print("!!! " + b, file=sys.stderr)
    if bad:
        return 1
    print("  两种写法: 内容一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
