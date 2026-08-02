#!/usr/bin/env python3
import html
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRE = re.compile(r'<pre[^>]*>(.*?)</pre>', re.S)
PANE = re.compile(r'<div[^>]*data-pane="(\w+)"(?![^>]*class="mode")')
CONF = re.compile(r'^\[[\w-]+\]$|^[\w-]+\s*=')


def text(pre):
    return [l.rstrip() for l in html.unescape(re.sub(r"<[^>]+>", "", pre)).split("\n") if l.strip()]


def panes(t):
    out = {"manual": [], "quick": []}
    for m in PANE.finditer(t):
        name = m.group(1)
        if name not in out:
            continue
        end = t.find('data-pane=', m.end())
        seg = t[m.start():end if end > 0 else len(t)]
        for p in PRE.findall(seg):
            out[name].append(text(p))
    return out


def sudo_btns(name, t, bad):
    for m in re.finditer(r'<div class="code"[^>]*>(.*?)</pre>', t, re.S):
        block = m.group(1)
        has_cmd = 'class="sudo"' in block
        has_btn = 'sudo-btn' in block
        if has_cmd and not has_btn:
            bad.append(f"{name}: 有 root 命令的代码块，标题栏里没有 sudo 开关")
        if has_btn and not has_cmd:
            bad.append(f"{name}: 代码块里一条 root 命令都没有，却有 sudo 开关")


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
        for m in re.finditer(r'<(\w+)([^>]*data-pane="quick"[^>]*)>', t):
            if "class=\"mode\"" in m.group(2) or " hidden" in m.group(2):
                continue
            bad.append(f"{f.name}: <{m.group(1)} data-pane=\"quick\"> 没写 hidden")

        sudo_btns(f.name, t, bad)
        for block in p["manual"]:
            for line in block:
                if not CONF.match(line.strip()):
                    continue
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
