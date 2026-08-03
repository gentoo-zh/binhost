#!/usr/bin/env python3
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PICK = re.compile(r'<div class="src-pick"([^>]*)data-src-switch="(\w+)"(.*?)</div>', re.S)
GROUP = re.compile(r'data-src-group="(\w+)"')
URI = re.compile(r'data-uri="([^"]+)"')
SLOT = re.compile(r'data-src-slot="(\w+)"([^>]*)')
CHIP = re.compile(r'data-src-copy="(\w+)"')


def main():
    bad = []
    for f in sorted((ROOT / "site").glob("*.html")):
        picks, kinds = {}, {}
        for pre, n, body in PICK.findall(f.read_text()):
            picks[n] = URI.findall(body + pre)
            m = GROUP.search(pre) or GROUP.search(body)
            kinds[n] = m.group(1) if m else "mirror"
        if not picks:
            continue
        text = f.read_text()

        for kind in set(kinds.values()):
            sets = {n: tuple(u) for n, u in picks.items() if kinds[n] == kind}
            if len(set(sets.values())) > 1:
                bad.append(f"{f.name}: {kind} 类各选择器的清单不一致 {sets}")
        for n, uris in picks.items():
            if len(uris) != len(set(uris)):
                bad.append(f"{f.name}: 选择器 {n} 有重复的镜像")
            if not uris:
                bad.append(f"{f.name}: 选择器 {n} 一个镜像都没有")

        for name, attrs in SLOT.findall(text):
            if name not in picks:
                bad.append(f"{f.name}: 槽位 {name} 没有对应的选择器")
            if "data-src-list" in attrs and "data-src-suffix" in attrs:
                bad.append(f"{f.name}: 槽位 {name} 同时要列表和后缀")
        for name in CHIP.findall(text):
            if name not in picks:
                bad.append(f"{f.name}: 复制按钮 {name} 没有对应的选择器")

        for m in re.finditer(r"data-src-list='([^']*)'", text):
            if "%s" not in m.group(1):
                bad.append(f"{f.name}: data-src-list 未包含 %s：{m.group(1)}")

    for b in bad:
        print("!!! " + b, file=sys.stderr)
    if bad:
        return 1
    print("  镜像选择器: markup 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
