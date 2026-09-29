#!/usr/bin/env python3
import importlib.util
import json
import re
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


copy = load("check_copy", ROOT / "site" / "tools" / "check-copy.py")
css = load("check_css", ROOT / "site" / "tools" / "check-css.py")
bad = 0
forbidden = "值得" + "注意的是"

for label, marker in (("void", "<img data-specimen>"),
                      ("self-closing", "<span data-specimen />")):
    text = copy.visible_text(f"<p>正常</p>{marker}<p>{forbidden}</p>")
    if forbidden in text:
        print(f"  ✓ {label} specimen 不会跳过后续文案")
    else:
        print(f"  ✗ {label} specimen 让后续文案退出检查")
        bad += 1

sample = "a { color: red; }\n@media (x) { * { color: blue; } }\na { color: green; }\n"
top_level = [(line, selector) for line, selector, media in css.rules(sample)
             if selector == "a" and media is None]
if top_level == [(1, "a"), (3, "a")]:
    print("  ✓ 单行 media 结束后的规则仍属于顶层")
else:
    print(f"  ✗ 单行 media 污染了后续规则： {top_level}")
    bad += 1

# Token-only values: a raw length or colour in a site.css declaration fails; hairlines, relative units,
# token references and media conditions pass.
raw = css.raw_values(
    "/* 7px in a comment */\n"
    ".a { padding: 7px var(--sp-2); }\n"
    ".b { color: #fff; }\n"
    ".c { border: 1px solid var(--border); width: 50%; margin: 0.2em; }\n"
    "@media (max-width: 34rem) { .d { gap: var(--sp-1); } }\n"
    ".e { box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.1); }\n")
lines = sorted(int(r.split("：")[0].split()[1]) for r in raw)
if lines == [2, 3, 6]:
    print("  ✓ site.css 的原始长度与颜色被拒绝，细线、相对单位与媒体条件放行")
else:
    print(f"  ✗ 原始值检查不对： {raw}")
    bad += 1

# A corner radius is a radius token: a percentage, a calc() or another token fails.
raw = css.raw_values(
    ".a { border-radius: var(--r-md); }\n"
    ".b { border-radius: 50%; }\n"
    ".c { border-radius: calc(var(--field-h) / 2); }\n"
    ".d { border-radius: var(--r-xl) var(--r-xl) 0 0; }\n"
    ".e { border-top-left-radius: var(--sp-2); }\n")
lines = sorted(int(r.split("：")[0].split()[1]) for r in raw)
if lines == [2, 3, 5]:
    print("  ✓ 圆角只接受 --r-* 令牌")
else:
    print(f"  ✗ 圆角检查不对： {raw}")
    bad += 1

with tempfile.TemporaryDirectory() as base:
    d = pathlib.Path(base)
    (d / "internal").mkdir()
    (d / "a.html").write_text('<p class="x">正常</p>\n<p style="margin: 0;">内联</p>\n')
    (d / "internal" / "b.html").write_text("<style>.x { }</style>\n")
    (d / "c.js").write_text("el.innerHTML = '<i style=\"background:' + v + '\"></i>';\n")
    (d / "d.js").write_text("el.style.display = 'none';\n")
    found = css.inline_styles([d / "a.html", d / "internal" / "b.html"], [d / "c.js", d / "d.js"])
    names = sorted(f.split(" ")[0] for f in found)
    if names == ["a.html", "b.html", "c.js"]:
        print("  ✓ 页面的 style 属性、页面样式表与脚本生成的 style 属性被拒绝")
    else:
        print(f"  ✗ 内联样式检查不对： {found}")
        bad += 1

with tempfile.TemporaryDirectory() as base:
    tree = pathlib.Path(base)
    tools = tree / "site" / "tools"
    chrome = tools / "chrome"
    chrome.mkdir(parents=True)
    shutil.copy2(ROOT / "site" / "tools" / "render-chrome.py", tools)
    shutil.copy2(ROOT / "site" / "tools" / "highlight.py", tools)
    for name in ("head", "nav", "foot"):
        (chrome / f"{name}.html").write_text(f"<{name}>内容</{name}>\n")
    page = tree / "site" / "index.html"
    page.write_text("".join(
        f"<!-- chrome:{name} -->\n旧内容\n<!-- /chrome:{name} -->\n"
        for name in ("head", "nav", "foot")))
    script = tools / "render-chrome.py"
    subprocess.run([sys.executable, script], check=True, capture_output=True, text=True)
    clean = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True)
    rendered = page.read_text()
    for name in ("head", "nav", "foot"):
        expected = (f"<!-- chrome:{name} -->\n<{name}>内容</{name}>\n"
                    f"<!-- /chrome:{name} -->\n")
        if expected in rendered:
            print(f"  ✓ 共用 {name} 区块使用自己的模板")
        else:
            print(f"  ✗ 共用 {name} 区块没有使用自己的模板")
            bad += 1
    nav = "<!-- chrome:nav -->\n<nav>内容</nav>\n<!-- /chrome:nav -->\n"
    page.write_text(page.read_text().replace(nav, ""))
    missing = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True)
    if clean.returncode == 0 and missing.returncode != 0 and "nav 标记数量" in missing.stderr:
        print("  ✓ 共用区块标记被移除时检查失败")
    else:
        print("  ✗ 共用区块标记被移除后检查仍然通过")
        bad += 1

# The search index: the committed file matches the pages, the i18n tables parse in every shape they are
# written in, and a translation changed in a page makes --check fail.
index = load("build_search_index", ROOT / "site" / "tools" / "build-search-index.py")
current = subprocess.run([sys.executable, ROOT / "site" / "tools" / "build-search-index.py", "--check"],
                         capture_output=True, text=True)
if current.returncode == 0:
    print("  ✓ site/assets/search-index.json 与页面一致")
else:
    print(f"  ✗ 搜索索引过期：{current.stderr.strip()}")
    bad += 1

table = index.js_table("x\nwindow.MIRROR_I18N = {\n  // note\n  'zh-tw': { a: '甲\\'乙', \"b_c\": \"\\u4e19\"," +
                       " d: 'x\\\n  y', },\n  en: { /* c */ a: 'A' }\n};\n", "MIRROR_I18N")
if table == {"zh-tw": {"a": "甲'乙", "b_c": "丙", "d": "x  y"}, "en": {"a": "A"}}:
    print("  ✓ i18n 表的引号键、转义、续行与注释都能读取")
else:
    print(f"  ✗ i18n 表读取不对： {table}")
    bad += 1

page = index.Page()
page.feed('<main><h1 data-i18n="title">标题</h1><p class="lead" data-i18n-html="lead">导语 <a>链接</a></p>'
          '<svg><path d="M0"/></svg><section id="deps"><h2 data-i18n="h">依赖</h2></section>'
          '<h3 id="q" data-i18n="q">问题<code>x</code>？</h3><p class="lead">不是导语</p></main>')
got = [(i["tag"], i["key"], i["id"], i["text"]) for i in page.items]
if got == [("h1", "title", None, "标题"), ("lead", "lead", None, "导语 链接"),
           ("h2", "h", "deps", "依赖"), ("h3", "q", "q", "问题x？")]:
    print("  ✓ 索引读取标题、导语与章节锚点（无 id 的标题取外层 id）")
else:
    print(f"  ✗ 页面解析不对： {got}")
    bad += 1

with tempfile.TemporaryDirectory() as base:
    tree = pathlib.Path(base)
    shutil.copytree(ROOT / "site", tree / "site")
    script = tree / "site" / "tools" / "build-search-index.py"
    faq = tree / "site" / "faq.html"
    source = faq.read_text()
    translations = index.js_table(source, "MIRROR_I18N")
    translations["zh-tw"]["title"] = "FAQ 常見問題"
    faq.write_text(re.sub(r"window\.MIRROR_I18N\s*=.*?</script>",
                          lambda _: "window.MIRROR_I18N = " + json.dumps(translations) + ";</script>",
                          source, flags=re.S))
    stale = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True)
    subprocess.run([sys.executable, script], check=True, capture_output=True, text=True)
    fresh = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True)
    if stale.returncode != 0 and "与页面不一致" in stale.stderr and fresh.returncode == 0:
        print("  ✓ 页面译文改动后搜索索引检查失败，重新生成后通过")
    else:
        print("  ✗ 搜索索引检查没有发现页面译文的改动")
        bad += 1

# The search logic: matching, ranking, package hits, the arrow keys and the shortcuts (tests/site-search.js).
logic = subprocess.run(["node", HERE / "site-search.js"], capture_output=True, text=True)
print(logic.stdout.rstrip())
if logic.returncode != 0:
    print(f"  ✗ 站内搜索逻辑测试未通过 {logic.stderr.strip()}")
    bad += 1

if bad:
    print(f"\n>>> {bad} 项未通过")
    sys.exit(1)
print("\n  三类检查器绕过均已覆盖")
