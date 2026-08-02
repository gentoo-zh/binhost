#!/usr/bin/env python3

import pathlib
import re
import sys
from collections import Counter, defaultdict


def rules(css):
    out, media = [], None
    for lineno, line in enumerate(css.split("\n"), 1):
        if re.match(r"\s*@media", line):
            media = line.strip()
        elif media and line == "}":
            media = None
        m = re.match(r"^([^@{}/][^{]*)\{", line)
        if m:
            out.append((lineno, m.group(1).strip(), media))
    return out


def main(site):
    site = pathlib.Path(site)
    css_path = site / "assets" / "site.css"
    css = css_path.read_text()
    src = "\n".join(p.read_text() for p in
                    list(site.glob("*.html")) + list((site / "assets").glob("*.js")))

    bad = []

    declared = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.M))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css)) | set(re.findall(r"(--[a-z0-9-]+)", src))
    for v in sorted(declared - used):
        bad.append(f"变量 {v} 声明了没人用")

    for v in sorted(set(re.findall(r"var\((--[a-z0-9-]+)", css)) - declared):
        bad.append(f"变量 {v} 被引用但没有声明")

    seen = defaultdict(list)
    for lineno, sel, media in rules(css):
        seen[(sel, media)].append(lineno)
    for (sel, media), lines in sorted(seen.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        if len(lines) > 1:
            where = media or "顶层"
            bad.append(f"选择器 {sel} 在{where}出现 {len(lines)} 次：行 {lines}")

    classes = set()
    for _, sel, _ in rules(css):
        classes.update(re.findall(r"\.([a-zA-Z][\w-]*)", sel))
    for c in sorted(classes):
        used = (re.search(r'class="' + re.escape(c) + r'(?:\s|")', src)
                or re.search(r'class="[^"]*\s' + re.escape(c) + r'(?:\s|")', src)
                or re.search(r'[\'"]' + re.escape(c) + r'[\'"]', src)
                or re.search(r'classList\.[a-z]+\([^)]*[\'"]' + re.escape(c) + r'[\'"]', src))
        if not used:
            bad.append(f"类 .{c} 在页面与脚本里都找不到")

    def palette(sel):
        i = css.find(sel)
        if i < 0:
            return None
        body = css[css.index("{", i) + 1:]
        body = body[:body.index("}")]
        return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))

    auto = palette(':root:not([data-theme="light"]) {')
    manual = palette('[data-theme="dark"] {')
    if auto is None:
        bad.append('找不到跟随系统那份深色调色盘（:root:not([data-theme="light"]) {）')
    elif not auto:
        bad.append('跟随系统那份深色调色盘是空的')
    if manual is None:
        bad.append('找不到手动选择那份深色调色盘（[data-theme="dark"] {）')
    elif not manual:
        bad.append('手动选择那份深色调色盘是空的')
    if auto is not None and manual is not None:
        for k in sorted(set(auto) | set(manual)):
            a, m = auto.get(k), manual.get(k)
            if a is None:
                bad.append(f"深色变量 {k} 只在手动选择那份里有")
            elif m is None:
                bad.append(f"深色变量 {k} 只在跟随系统那份里有")
            elif a.strip() != m.strip():
                bad.append(f"深色变量 {k} 两份不一致：{a.strip()} / {m.strip()}")

    if bad:
        print(f"!!! {css_path}")
        for b in bad:
            print(f"      {b}")
        return 1
    print(f"  {css_path.name}: 无残留")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "site"))
