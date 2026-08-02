#!/usr/bin/env python3
import itertools
import json
import pathlib
import sys

from portage.versions import vercmp

CASES = pathlib.Path(__file__).with_name("vercmp-cases.json")
data = json.loads(CASES.read_text())
versions = data["versions"]
pairs = {(a, b): want for a, b, want in data["pairs"]}

bad = 0
for a, b in itertools.combinations_with_replacement(versions, 2):
    c = vercmp(a, b)
    if c is None:
        print(f"  ✗ portage 无法比较 {a} 与 {b}")
        bad += 1
        continue
    want = 0 if c == 0 else (-1 if c < 0 else 1)
    if (a, b) not in pairs:
        print(f"  ✗ 清单里缺 {a} vs {b}")
        bad += 1
    elif pairs[(a, b)] != want:
        print(f"  ✗ {a} vs {b}: 清单写 {pairs[(a, b)]}，portage 说 {want}")
        bad += 1

extra = set(pairs) - set(itertools.combinations_with_replacement(versions, 2))
for a, b in sorted(extra):
    print(f"  ✗ 清单里多出 {a} vs {b}")
    bad += 1

if bad:
    print(f"\n>>> vercmp-cases.json 与 portage 不一致，{bad} 处")
    sys.exit(1)
print(f"  {len(versions)} 个版本，{len(pairs)} 组，与 portage 一致")
