#!/usr/bin/env python3
import pathlib
import re
import sys

SITE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "site")
LINK = re.compile(r'<a\b([^>]*)>', re.S)
ATTR = re.compile(r'(\S+?)="([^"]*)"')


def links(block):
    out = []
    for m in LINK.finditer(block):
        a = dict(ATTR.findall(m.group(1)))
        out.append((a.get("href", ""), a.get("data-i18n", ""),
                    a.get("data-i18n-href", ""), a.get("aria-label", "")))
    return out


# The sidebar is compared as its tree: each group's id and title key, then each link with the group that
# holds it, so a link moved between groups or a renamed group differs even when the link set is the same.
TREE = re.compile(r'<details\b[^>]*\bdata-group="([^"]*)"[^>]*>\s*<summary\b[^>]*>\s*<span data-i18n="([^"]*)"'
                  r'|(</details>)|<a\b([^>]*)>', re.S)


def tree(block):
    out, group = [], ""
    for m in TREE.finditer(block):
        if m.group(1) is not None:
            group = m.group(1)
            out.append(("group:" + group, m.group(2), "", ""))
        elif m.group(3):
            group = ""
        else:
            a = dict(ATTR.findall(m.group(4)))
            out.append((a.get("href", ""), a.get("data-i18n", ""), group, a.get("aria-label", "")))
    return out


def block(text, tag):
    m = re.search(rf"<{tag}\b.*?</{tag}>", text, re.S)
    return m.group(0) if m else ""


pages, bad = {}, 0
for f in sorted(SITE.glob("*.html")) + sorted(SITE.glob("internal/*.html")):
    t = f.read_text()
    side = re.search(r'<nav class="sidebar".*?</nav>', t, re.S)
    pages[f.name] = {"nav": links(block(t, "header")),
                     "side": tree(side.group(0) if side else ""),
                     "foot": links(block(t, "footer"))}

if not pages:
    sys.exit(f"{SITE} 下没有页面")

ref_name = "index.html" if "index.html" in pages else sorted(pages)[0]
ref = pages[ref_name]

for name, got in sorted(pages.items()):
    if name == ref_name:
        continue
    for part in ("nav", "side", "foot"):
        if got[part] == ref[part]:
            continue
        bad += 1
        label = {"nav": "顶栏", "side": "侧栏", "foot": "页脚"}[part]
        print(f"!!! {name} 的{label}和 {ref_name} 不一样")
        missing = [x for x in ref[part] if x not in got[part]]
        extra = [x for x in got[part] if x not in ref[part]]
        for x in missing:
            print(f"      少： {x[0]}  {x[1] or x[3]}")
        for x in extra:
            print(f"      多： {x[0]}  {x[1] or x[3]}")
        if not missing and not extra:
            print(f"      顺序不同： {[x[0] for x in got[part]]}")

if bad:
    sys.exit(1)
print(f"  顶栏、侧栏与页脚： {len(pages)} 个页面一致")
