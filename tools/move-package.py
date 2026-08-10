#!/usr/bin/env python3

import pathlib
import re
import sys


LIST = pathlib.Path(__file__).resolve().parent.parent / "build" / "packages.txt"
STABLE_EXCLUDED = LIST.with_name("stable-excluded.txt")
ATOM = re.compile(r"^[a-z0-9][a-z0-9+._-]*/[A-Za-z0-9][A-Za-z0-9+._-]*$")


def move_stable_exclusion(path, source, target):
    path = pathlib.Path(path)
    if not path.exists():
        return
    lines = path.read_text().splitlines()
    changed = False
    for index, line in enumerate(lines):
        if line.split(maxsplit=1)[:1] == [source]:
            lines[index] = target + line[len(source):]
            changed = True
    if changed:
        path.write_text("\n".join(lines) + "\n")


def main(source, target, path=LIST, stable_path=STABLE_EXCLUDED):
    if not ATOM.match(source) or not ATOM.match(target):
        raise ValueError("source and target must be category/package atoms")
    path = pathlib.Path(path)
    packages = [line for line in path.read_text().splitlines() if line]
    if source not in packages:
        raise ValueError(f"{source} is not in packages.txt")
    if target in packages:
        raise ValueError(f"{target} is already in packages.txt")
    packages[packages.index(source)] = target
    path.write_text("\n".join(sorted(packages, key=str.lower)) + "\n")
    move_stable_exclusion(stable_path, source, target)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("move-package.py <old category/package> <new category/package>")
    try:
        main(sys.argv[1], sys.argv[2])
    except ValueError as error:
        sys.exit(str(error))
