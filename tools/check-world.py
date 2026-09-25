#!/usr/bin/env python3

import argparse
import pathlib
import sys

parser = argparse.ArgumentParser()
parser.add_argument("world", nargs="+")
parser.add_argument("--tree", action="append", required=True)
args = parser.parse_args()

missing = sorted({
    atom
    for world in args.world
    for atom in pathlib.Path(world).read_text().split()
    if not any(next(pathlib.Path(tree, atom.partition(":")[0]).glob("*.ebuild"), None)
               for tree in args.tree)
})
for atom in missing:
    print(f"{atom}：给定的树中都没有 ebuild")
sys.exit(1 if missing else 0)
