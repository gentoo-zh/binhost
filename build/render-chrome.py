#!/usr/bin/env python3
"""把共用的 head、导航栏、页脚写进各页的标记区间。

模板在 build/chrome/，不随站点发布。生成的仍是纯静态 HTML，同步脚本和 nginx
都不知道有这一步。

    python3 build/render-chrome.py           # 写回
    python3 build/render-chrome.py --check   # 只检查，有差异就非零退出（CI 用）

页里写：

    <!-- chrome:nav wide -->
    ...生成的内容...
    <!-- /chrome:nav -->

wide 是可选的变体，包列表和文件浏览器用宽版面。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TPL = ROOT / "build" / "chrome"
BLOCK = re.compile(r"( *)<!-- chrome:(\w+)([^>]*?) -->\n.*?^ *<!-- /chrome:\2 -->\n",
                   re.S | re.M)


def render(name, flags, indent):
    body = (TPL / f"{name}.html").read_text()
    body = body.replace("{{wide}}", " wide" if "wide" in flags else "")
    lines = [indent + l if l.strip() else l for l in body.splitlines(keepends=True)]
    head = f"{indent}<!-- chrome:{name}{flags} -->\n"
    return head + "".join(lines) + f"{indent}<!-- /chrome:{name} -->\n"


def main():
    check = "--check" in sys.argv
    site = ROOT / "site"
    stale = []
    for f in sorted(site.glob("*.html")):
        old = f.read_text()
        new = BLOCK.sub(lambda m: render(m.group(2), m.group(3), m.group(1)), old)
        if new == old:
            continue
        if check:
            stale.append(f.name)
        else:
            f.write_text(new)
            print(f"  更新 {f.name}")

    if check and stale:
        print("!!! 这些页面和 build/chrome/ 下的模板对不上：" + "，".join(stale),
              file=sys.stderr)
        print("    跑 python3 build/render-chrome.py 重新生成", file=sys.stderr)
        return 1
    if check:
        print("  共用部分: 各页与模板一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
