#!/usr/bin/env python3
"""
retire-package.py <category/package> <reason>
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LIST = HERE / "packages.txt"
EXCLUDED = HERE / "excluded.txt"
ATOM = re.compile(r"^[a-z0-9][a-z0-9+._-]*/[A-Za-z0-9][A-Za-z0-9+._-]*$")

GONE = "overlay 里已没有这个包"


def already_excluded(cp):
    if not EXCLUDED.exists():
        return False
    for line in EXCLUDED.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            if re.split(r"\s{2,}|\t", line, maxsplit=1)[0].strip() == cp:
                return True
    return False


def main(cp, reason):
    if not ATOM.match(cp):
        sys.exit(f"不是一个 category/package: {cp}")
    if not reason.strip():
        sys.exit("原因不能为空")

    body = [l for l in LIST.read_text().splitlines() if l]
    if cp not in body:
        sys.exit(f"{cp} 不在清单里")
    body.remove(cp)
    LIST.write_text("\n".join(body) + "\n")

    if reason == GONE:
        print(f"移出 {cp}：{reason}")
        return 0
    if already_excluded(cp):
        print(f"移出 {cp}：excluded.txt 里已经有它")
        return 0

    text = EXCLUDED.read_text() if EXCLUDED.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    EXCLUDED.write_text(f"{text}{cp}\t{reason}\n")
    print(f"移出 {cp}，写进 excluded.txt：{reason}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
