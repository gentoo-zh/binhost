#!/usr/bin/env python3
"""镜像选择器的静态检查。

会悄悄坏掉的是 markup：加了镜像只加进一部分选择器、槽位指向不存在的选择器、
两种形态写反。这些改完页面看着还正常，点下去才发现。行为本身在浏览器里验。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PICK = re.compile(r'<div class="src-pick"[^>]*data-src-switch="(\w+)"(.*?)</div>', re.S)
URI = re.compile(r'data-uri="([^"]+)"')
SLOT = re.compile(r'data-src-slot="(\w+)"([^>]*)')
CHIP = re.compile(r'data-src-copy="(\w+)"')


def main():
    bad = []
    for f in sorted((ROOT / "site").glob("*.html")):
        picks = {n: URI.findall(body) for n, body in PICK.findall(f.read_text())}
        if not picks:
            continue
        text = f.read_text()

        # 一页上的选择器问的是同一件事，镜像清单必须一致，否则点了同步不过去
        sets = {n: tuple(u) for n, u in picks.items()}
        if len(set(sets.values())) > 1:
            bad.append(f"{f.name}: 各选择器的镜像清单不一致 {sets}")
        for n, uris in picks.items():
            if len(uris) != len(set(uris)):
                bad.append(f"{f.name}: 选择器 {n} 有重复的镜像")
            if not uris:
                bad.append(f"{f.name}: 选择器 {n} 一个镜像都没有")

        for name, attrs in SLOT.findall(text):
            if name not in picks:
                bad.append(f"{f.name}: 槽位 {name} 没有对应的选择器")
            # 两种形态互斥：一个地址加后缀，或者一整个列表
            if "data-src-list" in attrs and "data-src-suffix" in attrs:
                bad.append(f"{f.name}: 槽位 {name} 同时要列表和后缀")
        for name in CHIP.findall(text):
            if name not in picks:
                bad.append(f"{f.name}: 复制按钮 {name} 没有对应的选择器")

        # 列表形态要留出放地址的位置，%s 漏了就写死成一个
        for m in re.finditer(r"data-src-list='([^']*)'", text):
            if "%s" not in m.group(1):
                bad.append(f"{f.name}: data-src-list 里没有 %s：{m.group(1)}")

    for b in bad:
        print("!!! " + b, file=sys.stderr)
    if bad:
        return 1
    print("  镜像选择器: markup 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
