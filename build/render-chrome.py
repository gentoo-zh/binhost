#!/usr/bin/env python3
import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TPL = ROOT / "build" / "chrome"
BLOCK = re.compile(r"( *)<!-- chrome:(\w+)([^>]*?) -->\n.*?^ *<!-- /chrome:\2 -->\n",
                   re.S | re.M)


def stamp(body):
    def one(m):
        f = ROOT / "site" / m.group(1).lstrip("/")
        if not f.exists():
            return m.group(0)
        h = hashlib.blake2b(f.read_bytes(), digest_size=4).hexdigest()
        return f'{m.group(1)}?v={h}'
    return re.sub(r'(/assets/[\w.-]+\.(?:css|js))(?:\?v=\w+)?', one, body)


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
        new = stamp(new)
        if new == old:
            continue
        if check:
            stale.append(f.name)
        else:
            f.write_text(new)
            print(f"  更新 {f.name}")

    if check and stale:
        print("!!! 这些页面和 build/chrome/ 下的模板不一致：" + "，".join(stale),
              file=sys.stderr)
        print("    跑 python3 build/render-chrome.py 重新生成", file=sys.stderr)
        return 1
    if check:
        print("  共用部分: 各页与模板一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
