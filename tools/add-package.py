#!/usr/bin/env python3
"""
add-package.py <category/package>
"""
import bisect
import pathlib
import re
import sys

LIST = pathlib.Path(__file__).resolve().parent.parent / "build" / "packages.txt"
ATOM = re.compile(r"^[a-z0-9][a-z0-9+._-]*/[A-Za-z0-9][A-Za-z0-9+._-]*$")


def main(cp):
    if not ATOM.match(cp):
        sys.exit(f"不是一个 category/package: {cp}")
    body = [l for l in LIST.read_text().splitlines() if l]
    if cp in body:
        print(f"{cp} 已经在清单里")
        return 0
    i = bisect.bisect_left([l.lower() for l in body], cp.lower())
    body.insert(i, cp)
    LIST.write_text("\n".join(body) + "\n")
    print(f"加入 {cp}（第 {i + 1} 行）")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
