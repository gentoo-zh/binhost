#!/usr/bin/env python3

import pathlib
import re
import sys
from collections import Counter, defaultdict


def rules(css):
    out, media, depth = [], [], 0
    for lineno, line in enumerate(css.split("\n"), 1):
        structural = re.sub(r"(['\"])(?:\\.|(?!\1).)*\1", "", line)
        opens = structural.count("{")
        closes = structural.count("}")
        if re.match(r"\s*@(media|container|supports)\b", structural):
            label = structural.split("{", 1)[0].strip()
            if opens > closes:
                media.append((label, depth + 1))
        m = re.match(r"^([^@{}/][^{]*)\{", line)
        if m:
            out.append((lineno, m.group(1).strip(), media[-1][0] if media else None))
        depth += opens - closes
        while media and depth < media[-1][1]:
            media.pop()
    return out


# Values come from tokens.css. In site.css a declaration may not write a length in px or rem or a colour
# literal: a new value is a new token, named for its role, or it is a value the scale already has.
# Relative units (%, em, ch, fr, vw, vh, dvh), angles and durations through var() are fine. Exceptions:
RAW_OK = {
    "0px": "zero in any unit",
    "1px": "hairlines: borders, dividers and the 1px outline of an overlay",
    "-1px": "the margin that hides a visually hidden element",
}
# A corner radius is one of the radius tokens and nothing else, so each component size keeps one radius.
RADIUS_TOKEN = re.compile(r"var\(--r-[a-z]+\)|0")
LENGTH = re.compile(r"(?<![\w.#-])-?(?:\d+\.?\d*|\.\d+)(?:px|rem)\b")
COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|lab|lch)\(")


def blank_comments(css):
    # Comments become spaces, newlines kept, so line numbers still match the file.
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), css, flags=re.S)


def raw_values(css):
    out = []
    for lineno, line in enumerate(blank_comments(css).split("\n"), 1):
        if re.match(r"\s*@(media|container|supports)\b", line):
            continue  # a media condition cannot read a custom property
        for decl in re.findall(r"([\w-]+)\s*:\s*([^;{}]+)", line):
            if re.fullmatch(r"border(?:-[a-z]+)*-radius", decl[0]):
                parts = decl[1].replace("!important", "").split()
                if not parts or not all(RADIUS_TOKEN.fullmatch(p) for p in parts):
                    out.append(f"行 {lineno}：{decl[0]} 写了 {decl[1].strip()}，圆角只能取 --r-* 令牌")
                    continue
            value = re.sub(r"var\([^()]*\)", "", decl[1])
            for m in LENGTH.finditer(value):
                if m.group(0) not in RAW_OK:
                    out.append(f"行 {lineno}：{decl[0]} 写了 {m.group(0)}，应取 tokens.css 的令牌")
            for m in COLOUR.finditer(value):
                out.append(f"行 {lineno}：{decl[0]} 写了颜色 {m.group(0)}，应取 tokens.css 的令牌")
    return out


def inline_styles(pages, scripts):
    # A page is built from the shared components only: no style attribute, no page stylesheet.
    out = []
    for f in pages:
        for lineno, line in enumerate(f.read_text().split("\n"), 1):
            if re.search(r"<style\b", line):
                out.append(f"{f.name} 行 {lineno}：页面内的 <style>，样式应写在 site.css")
            if re.search(r"\sstyle\s*=", line):
                out.append(f"{f.name} 行 {lineno}：style 属性，样式应写在 site.css")
    for f in scripts:
        for lineno, line in enumerate(f.read_text().split("\n"), 1):
            if re.search(r"""\sstyle=['"\\]""", line):
                out.append(f"{f.name} 行 {lineno}：脚本生成 style 属性，样式应写在 site.css")
    return out


def main(site):
    site = pathlib.Path(site)
    css_path = site / "assets" / "site.css"
    # Tokens live in tokens.css and components in site.css; variables and palettes span both.
    css = "\n".join(p.read_text() for p in
                    [site / "assets" / "tokens.css", css_path] if p.exists())
    src = "\n".join(p.read_text() for p in
                    list(site.glob("*.html")) + list(site.glob("internal/*.html")) +
                    list((site / "assets").glob("*.js")))

    bad = []

    bad.extend(raw_values(css_path.read_text()) if css_path.exists() else [])
    pages = sorted(site.glob("*.html")) + sorted(site.glob("internal/*.html"))
    bad.extend(inline_styles(pages, sorted((site / "assets").glob("*.js"))))

    declared = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.M))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css)) | set(re.findall(r"(--[a-z0-9-]+)", src))
    for v in sorted(declared - used):
        bad.append(f"变量 {v} 已声明但未使用")

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
        bad.append('缺少跟随系统的深色调色盘（:root:not([data-theme="light"]) {）')
    elif not auto:
        bad.append('跟随系统的深色调色盘未定义颜色变量')
    if manual is None:
        bad.append('缺少手动选择的深色调色盘（[data-theme="dark"] {）')
    elif not manual:
        bad.append('手动选择的深色调色盘未定义颜色变量')
    if auto is not None and manual is not None:
        for k in sorted(set(auto) | set(manual)):
            a, m = auto.get(k), manual.get(k)
            if a is None:
                bad.append(f"深色变量 {k} 仅在手动选择的调色盘中定义")
            elif m is None:
                bad.append(f"深色变量 {k} 仅在跟随系统的调色盘中定义")
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
