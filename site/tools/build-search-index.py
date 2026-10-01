#!/usr/bin/env python3
"""Write site/assets/search-index.json, which the site search reads.

The index lists every public page and each of its h2 and h3 headings that has an anchor, in the three
languages: zh-CN from the markup, zh-TW and en from the page's MIRROR_I18N table over strings.js. The pages
and their groups come from the sidebar template (site/tools/chrome/nav.html), so a page added to the sidebar
is indexed and the search's category chips follow the sidebar's groups. Each group's icon is the one the
overview's guide card for that group shows (index.html), matched by the group's title key; a group with no
card takes its icon from GROUP_ICON.

--check fails when the file on disk differs from what the pages give.
"""
import html
import html.parser
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SITE = ROOT / "site"
OUT = SITE / "assets" / "search-index.json"
LANGS = ("zh-cn", "zh-tw", "en")
# Joins a page's section titles into its card description when the page has no lead paragraph.
LIST_SEP = {"zh-cn": "、", "zh-tw": "、", "en": ", "}


# --- JavaScript object literals -------------------------------------------------------------------------
# The i18n tables are object literals of string values: identifier or quoted keys, single- or double-quoted
# strings, nested objects, comments and trailing commas. Anything else is an error, so a table written in
# some other shape fails the build instead of dropping its strings.

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def js_string(src, i):
    quote, out, i = src[i], [], i + 1
    while src[i] != quote:
        c = src[i]
        if c == "\\":
            n = src[i + 1]
            if n == "u":
                out.append(chr(int(src[i + 2:i + 6], 16)))
                i += 6
                continue
            if n == "\n":
                i += 2
                continue
            out.append(ESCAPES.get(n, n))
            i += 2
            continue
        if c == "\n":
            raise ValueError("unterminated string")
        out.append(c)
        i += 1
    return "".join(out), i + 1


def js_skip(src, i):
    while True:
        m = re.compile(r"\s+|//[^\n]*|/\*.*?\*/", re.S).match(src, i)
        if not m:
            return i
        i = m.end()


def js_value(src, i):
    i = js_skip(src, i)
    if src[i] in "'\"":
        return js_string(src, i)
    if src[i] != "{":
        raise ValueError(f"unexpected {src[i:i + 20]!r}")
    obj, i = {}, i + 1
    while True:
        i = js_skip(src, i)
        if src[i] == "}":
            return obj, i + 1
        if src[i] in "'\"":
            key, i = js_string(src, i)
        else:
            m = re.compile(r"[A-Za-z_$][\w$-]*").match(src, i)
            if not m:
                raise ValueError(f"bad key at {src[i:i + 20]!r}")
            key, i = m.group(0), m.end()
        i = js_skip(src, i)
        if src[i] != ":":
            raise ValueError(f"expected : after {key}")
        obj[key], i = js_value(src, i + 1)
        i = js_skip(src, i)
        if src[i] == ",":
            i += 1


def js_table(text, name):
    m = re.search(r"window\." + name + r"\s*=\s*", text)
    return js_value(text, m.end())[0] if m else {}


def plain(markup):
    """Visible text of an HTML fragment, whitespace collapsed."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", markup))).strip()


# --- Pages ----------------------------------------------------------------------------------------------

class Page(html.parser.HTMLParser):
    """Collects, inside <main>, the h1, the lead paragraph before the first h2, and each h2 and h3: its
    i18n key, zh-CN text, anchor (its own id, else the nearest enclosing one) and classes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.main, self.cur, self.items = [], False, None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("br", "img", "input", "meta", "link", "wbr", "hr", "source", "path"):
            return
        self.stack.append((tag, a.get("id")))
        if tag == "main":
            self.main = True
        if not self.main or self.cur:
            return
        classes = (a.get("class") or "").split()
        key = a.get("data-i18n") or a.get("data-i18n-html")
        lead = tag == "p" and "lead" in classes and not any(i["tag"] == "h2" for i in self.items)
        if tag in ("h1", "h2", "h3") or lead:
            anchor = a.get("id") or next((i for _, i in reversed(self.stack[:-1]) if i), None)
            self.cur = {"tag": "lead" if lead else tag, "key": key, "id": anchor, "classes": classes,
                        "text": [], "depth": len(self.stack)}

    def handle_endtag(self, tag):
        if self.cur and len(self.stack) == self.cur["depth"]:
            self.cur["text"] = re.sub(r"\s+", " ", "".join(self.cur["text"])).strip()
            self.items.append(self.cur)
            self.cur = None
        if any(t == tag for t, _ in self.stack):
            while self.stack.pop()[0] != tag:
                pass
        if tag == "main":
            self.main = False

    def handle_startendtag(self, tag, attrs):
        pass  # <path/> and the like hold no text and open nothing

    def handle_data(self, data):
        if self.cur:
            self.cur["text"].append(data)


def sidebar():
    """The sidebar's groups and pages, from the template: [(group id, title key, zh-CN title, [hrefs])]."""
    text = (SITE / "tools" / "chrome" / "nav.html").read_text()
    side = re.search(r'<nav class="sidebar".*?</nav>', text, re.S).group(0)
    groups, current = [], ("", "", "", [])
    groups.append(current)
    for m in re.finditer(r'<details\b[^>]*\bdata-group="([^"]*)"[^>]*>\s*<summary\b[^>]*>\s*'
                         r'<span data-i18n="([^"]*)">([^<]*)</span>|(</details>)|<a\b[^>]*\bhref="([^"]*)"',
                         side, re.S):
        if m.group(1) is not None:
            current = (m.group(1), m.group(2), m.group(3).strip(), [])
            groups.append(current)
        elif m.group(4):
            current = groups[0]
        else:
            current[3].append(m.group(5))
    return groups


def page_file(href):
    if not href.startswith("/") or href.endswith("/") and href != "/":
        return None
    f = SITE / ("index.html" if href == "/" else href.lstrip("/") + ".html")
    return f if f.is_file() else None


# Icons for sidebar groups with no guide card on the overview, by the group's title key. Same Spectrum 2
# workflow set as the cards: About uses InfoCircle.
GROUP_ICON = {
    "navGAbout": {"viewBox": "0 0 20 20", "paths": [
        "M10 18.75c-4.825 0-8.75-3.925-8.75-8.75S5.175 1.25 10 1.25s8.75 3.925 8.75 8.75-3.925 8.75-8.75 8.75"
        "m0-16c-3.998 0-7.25 3.252-7.25 7.25s3.252 7.25 7.25 7.25 7.25-3.252 7.25-7.25S13.998 2.75 10 2.75",
        "M10 5.26c.231-.008.456.074.627.229.33.365.33.921 0 1.286-.17.159-.395.243-.626.235"
        "-.237.01-.466-.08-.633-.248-.162-.168-.25-.394-.242-.627-.012-.235.07-.465.228-.64.174-.164.408-.25.647-.235"
        "M10 15.063c-.414 0-.75-.336-.75-.75V9.478c0-.415.336-.75.75-.75s.75.335.75.75v4.835c0 .414-.336.75-.75.75",
    ]},
}


def icons():
    """Each overview entry card's icon, by the i18n key of the card's title."""
    text = (SITE / "index.html").read_text()
    out = {}
    for m in re.finditer(r'<span class="entry-head">(<svg\b.*?</svg>)\s*'
                         r'<span class="entry-title" data-i18n="(\w+)"', text, re.S):
        svg = m.group(1)
        out[m.group(2)] = {"viewBox": re.search(r'viewBox="([^"]*)"', svg).group(1),
                           "paths": re.findall(r'<path\b[^>]*\bd="([^"]*)"', svg)}
    return out


def build():
    common = js_table((SITE / "assets" / "strings.js").read_text(), "MIRROR_I18N_COMMON")
    art = {**GROUP_ICON, **icons()}
    groups, entries, problems = [], [], []

    def tr(key, zh, table):
        out = {"zh-cn": zh}
        for lang in LANGS[1:]:
            v = (table.get(lang) or {}).get(key) if key else None
            if v is None and key:
                v = (common.get(lang) or {}).get(key)
            out[lang] = plain(v) if v is not None else zh
        return out

    for gid, gkey, gzh, hrefs in sidebar():
        if gid:
            if gkey not in art:
                problems.append(f"侧栏分组 {gid} 的标题 {gkey} 在 index.html 的指南卡片和 GROUP_ICON 中都找不到图标")
            groups.append({"id": gid, "label": tr(gkey, gzh, {}), "icon": art.get(gkey)})
        for href in hrefs:
            f = page_file(href)
            if not f:
                continue
            text = f.read_text()
            table = js_table(text, "MIRROR_I18N")
            p = Page()
            p.feed(text)
            h1 = next((i for i in p.items if i["tag"] == "h1"), None)
            if not h1:
                problems.append(f"{f.name} 没有 h1")
                continue
            title = tr(h1["key"], h1["text"], table)
            heads = [i for i in p.items if i["tag"] in ("h2", "h3") and i["id"]]
            lead = next((i for i in p.items if i["tag"] == "lead"), None)
            if lead:
                desc = tr(lead["key"], lead["text"], table)
            else:
                names = {lang: [] for lang in LANGS}
                for h in heads:
                    if h["tag"] == "h2" and "pane-title" not in h["classes"]:
                        t = tr(h["key"], h["text"], table)
                        for lang in LANGS:
                            if t[lang] not in names[lang]:
                                names[lang].append(t[lang])
                desc = {lang: LIST_SEP[lang].join(names[lang]) for lang in LANGS}
            slug = href.strip("/") or "index"
            entries.append({"url": href, "group": gid, "kind": "page", "title": title, "desc": desc,
                            "keywords": [slug]})
            # A section's card names its page and, below the page, the heading it sits under: a pane title
            # (the Live ISO page repeats its h2s once per image) for an h2, the h2 for an h3.
            pane = h2 = None
            for h in heads:
                t = tr(h["key"], h["text"], table)
                if "pane-title" in h["classes"]:
                    pane, h2 = t, None
                    continue
                context = pane if h["tag"] == "h2" else (h2 or pane)
                if h["tag"] == "h2":
                    h2 = t
                d = {lang: title[lang] + (" · " + context[lang] if context else "") for lang in LANGS}
                entries.append({"url": f"{href}#{h['id']}", "group": gid, "kind": "section",
                                "title": t, "desc": d, "keywords": [h["id"]]})
    return {"langs": list(LANGS), "groups": groups, "entries": entries}, problems


def main():
    check = "--check" in sys.argv[1:]
    index, problems = build()
    for p in problems:
        print(f"!!! {p}", file=sys.stderr)
    if problems:
        return 1
    body = json.dumps(index, ensure_ascii=False, indent=1) + "\n"
    pages = sum(e["kind"] == "page" for e in index["entries"])
    sections = len(index["entries"]) - pages
    if check:
        if not OUT.exists() or OUT.read_text() != body:
            print(f"!!! {OUT.relative_to(ROOT)} 与页面不一致", file=sys.stderr)
            print("    执行 python3 site/tools/build-search-index.py 重新生成", file=sys.stderr)
            return 1
        print(f"  搜索索引： 与页面一致（{pages} 个页面，{sections} 个章节）")
        return 0
    if not OUT.exists() or OUT.read_text() != body:
        OUT.write_text(body)
        print(f"  更新 {OUT.relative_to(ROOT)}（{pages} 个页面，{sections} 个章节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
