#!/usr/bin/env python3
import hashlib
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import highlight  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
TPL = ROOT / "site" / "tools" / "chrome"
BLOCK = re.compile(r"( *)<!-- chrome:(\w+)([^>]*?) -->\n.*?^ *<!-- /chrome:\2 -->\n",
                   re.S | re.M)
START = re.compile(r"<!-- chrome:(\w+)\b[^>]*-->")
END = re.compile(r"<!-- /chrome:(\w+)\s*-->")


def stamp(body):
    def one(m):
        f = ROOT / "site" / m.group(1).lstrip("/")
        if not f.exists():
            return m.group(0)
        h = hashlib.blake2b(f.read_bytes(), digest_size=4).hexdigest()
        return f'{m.group(1)}?v={h}'
    return re.sub(r'(?<![\w/])(/assets/[\w.-]+\.(?:css|js|json))(?:\?v=\w+)?', one, body)


CURRENT = re.compile(r'\bcurrent="([^"]*)"')
NAV_LINK = re.compile(r'<a class="nav-link" href="([^"]+)"(?: data-i18n="(\w+)")?>([^<]+)</a>')
NAV_CURRENT = re.compile(r'<!-- chrome:nav current="([^"]*)" -->')
# Optional blocks are generated here rather than copied from a template, and only pages that carry the
# marker get one.
OPTIONAL = {"pager"}
MAIN = re.compile(r"<main\b([^>]*)>(.*?)</main>", re.S)


def has_outline(text):
    """docs.js builds "On this page" from two or more h2s in an article that is not the wide layout. The
    mark is written here so the layout reserves the outline column only on those pages, before any script."""
    m = MAIN.search(text)
    return bool(m) and not re.search(r'class="[^"]*\bwide\b', m.group(1)) \
        and len(re.findall(r"<h2\b", m.group(2))) > 1

# The design page lists token values. Its script reads them from the stylesheet in force; the static
# copy written here is what readers without scripts see, in the markup's language (zh-cn).
TOKENS_CSS = ROOT / "site" / "assets" / "tokens.css"
SWATCH_LIST = re.compile(r"var TOKENS = \[([^\]]*)\]")
SWATCH_GRID = re.compile(r'(<div class="sw-grid" id="sw-(light|dark)" data-theme="\2">).*?(</div>\n)', re.S)
TOKEN_CELL = re.compile(r'(<td data-token="([\w-]+)"(?: data-label="([^"]*)")?>)[^<]*(</td>)')


def css_block(css, selector):
    m = re.search(r"^" + re.escape(selector) + r" \{(.*?)^\}", css, re.S | re.M)
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", m.group(1))) if m else {}


def design_values(text):
    names = SWATCH_LIST.search(text)
    if not names:
        return text
    css = TOKENS_CSS.read_text()
    palettes = {"light": css_block(css, ':root, [data-theme="light"]'),
                "dark": css_block(css, '[data-theme="dark"]')}
    sizes = {**css_block(css, ":root"), **css_block(css, ":root:lang(zh)")}
    order = re.findall(r"'([\w-]+)'", names.group(1))

    def grid(m):
        pal = palettes[m.group(2)]
        # The swatch paints itself from its class inside the grid's data-theme; only the value is written.
        cells = "".join(f'<div class="sw sw-{t}"><i></i><b>{t}</b><span>{pal[t]}</span></div>'
                        for t in order)
        return m.group(1) + cells + m.group(3)

    def cell(m):
        v = sizes[m.group(2)]
        return m.group(1) + (f"{m.group(3)} · {v}" if m.group(3) else v) + m.group(4)

    return TOKEN_CELL.sub(cell, SWATCH_GRID.sub(grid, text))


def pager(text):
    """Previous and next follow the sidebar, so reordering the sidebar reorders the pager."""
    # A link ending in "/" is a directory served by the file browser (_app.html), not a page, so the pager
    # steps over it.
    links = [l for l in NAV_LINK.findall((TPL / "nav.html").read_text())
             if l[0] == "/" or not l[0].endswith("/")]
    cur = NAV_CURRENT.search(text)
    hrefs = [href for href, _, _ in links]
    if not cur or cur.group(1) not in hrefs:
        return ""
    i = hrefs.index(cur.group(1))

    def link(j, side, key, word):
        href, label_key, label = links[j]
        attr = f' data-i18n="{label_key}"' if label_key else ""
        return (f'  <a class="pager-link pager-{side}" href="{href}"><span class="pager-dir" data-i18n="{key}">'
                f'{word}</span><span class="pager-title"{attr}>{label}</span></a>\n')

    body = '<nav class="pager" aria-label="上一页与下一页" data-i18n-label="aPager">\n'
    if i > 0:
        body += link(i - 1, "prev", "prev", "上一页")
    if i + 1 < len(links):
        body += link(i + 1, "next", "next", "下一页")
    return body + "</nav>\n"


def render(name, flags, indent, outline=False, text=""):
    body = pager(text) if name == "pager" else (TPL / f"{name}.html").read_text()
    if outline:
        body = body.replace('<aside class="toc"', '<aside class="toc" data-outline', 1)
    # current="/faq" on the marker marks that page's link as the current page without scripts: the first sidebar
    # row and the first top-bar link to it ("/files/" has both, a phone-only sidebar row and the bar link).
    cur = CURRENT.search(flags)
    if cur:
        for cls in ("nav-link", "bar-link"):
            link = re.compile(rf'class="(?:[\w-]+ )*{cls}(?: [\w-]+)*" href="{re.escape(cur.group(1))}"')
            body = link.sub(lambda m: m.group(0) + ' aria-current="page"', body, count=1)
    lines = [indent + l if l.strip() else l for l in body.splitlines(keepends=True)]
    head = f"{indent}<!-- chrome:{name}{flags} -->\n"
    return head + "".join(lines) + f"{indent}<!-- /chrome:{name} -->\n"


def marker_errors(text, expected):
    starts = [m.group(1) for m in START.finditer(text)]
    ends = [m.group(1) for m in END.finditer(text)]
    complete = [m.group(2) for m in BLOCK.finditer(text)]
    errors = []
    for name in sorted(expected):
        counts = (starts.count(name), ends.count(name), complete.count(name))
        if counts != (1, 1, 1):
            errors.append(f"{name} 标记数量为 {counts[0]}/{counts[1]}/{counts[2]}")
    for name in sorted(OPTIONAL & (set(starts) | set(ends) | set(complete))):
        counts = (starts.count(name), ends.count(name), complete.count(name))
        if counts != (1, 1, 1):
            errors.append(f"{name} 标记数量为 {counts[0]}/{counts[1]}/{counts[2]}")
    for name in sorted((set(starts) | set(ends) | set(complete)) - set(expected) - OPTIONAL):
        errors.append(f"存在未知的 {name} 标记")
    return errors


def main():
    check = "--check" in sys.argv
    site = ROOT / "site"
    expected = {p.stem for p in TPL.glob("*.html")}
    stale, invalid = [], []
    # site/internal/ holds maintainer pages that publish-site.sh never copies; they share the chrome.
    for f in sorted(site.glob("*.html")) + sorted(site.glob("internal/*.html")):
        old = f.read_text()
        errors = marker_errors(old, expected)
        if errors:
            invalid.extend(f"{f.name}: {error}" for error in errors)
            continue
        outline = has_outline(old)
        new = BLOCK.sub(lambda m: render(m.group(2), m.group(3), m.group(1), outline, old), old)
        # Code blocks that opt in with data-syntax take their colours here (highlight.py).
        new = highlight.render(design_values(stamp(new)))
        if new == old:
            continue
        if check:
            stale.append(f.name)
        else:
            f.write_text(new)
            print(f"  更新 {f.name}")

    if invalid:
        print("!!! 共用部分的生成标记不完整：", file=sys.stderr)
        for error in invalid:
            print(f"    {error}", file=sys.stderr)
    if check and stale:
        print("!!! 这些页面和 site/tools/chrome/ 下的模板不一致：" + "，".join(stale),
              file=sys.stderr)
        print("    执行 python3 site/tools/render-chrome.py 重新生成", file=sys.stderr)
    if invalid or (check and stale):
        return 1
    if check:
        print("  共用部分： 各页与模板一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
