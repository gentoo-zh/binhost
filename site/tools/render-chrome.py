#!/usr/bin/env python3
import hashlib
import pathlib
import re
import sys

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
    return re.sub(r'(/assets/[\w.-]+\.(?:css|js))(?:\?v=\w+)?', one, body)


def render(name, flags, indent):
    body = (TPL / f"{name}.html").read_text()
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
    for name in sorted((set(starts) | set(ends) | set(complete)) - set(expected)):
        errors.append(f"存在未知的 {name} 标记")
    return errors


def main():
    check = "--check" in sys.argv
    site = ROOT / "site"
    expected = {p.stem for p in TPL.glob("*.html")}
    stale, invalid = [], []
    for f in sorted(site.glob("*.html")):
        old = f.read_text()
        errors = marker_errors(old, expected)
        if errors:
            invalid.extend(f"{f.name}: {error}" for error in errors)
            continue
        new = BLOCK.sub(lambda m: render(m.group(2), m.group(3), m.group(1)), old)
        new = stamp(new)
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
