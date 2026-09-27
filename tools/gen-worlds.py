#!/usr/bin/env python3
"""
gen-worlds.py [--check]

Generates builders/{stable,unstable}/world from build/packages.txt and build/stable-excluded.txt.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def atoms(path):
    lines = (l.split("#")[0].split("\t")[0].strip() for l in (ROOT / path).read_text().splitlines())
    return {l for l in lines if l}


def main(check):
    packages = atoms("build/packages.txt")
    worlds = {
        "unstable": packages | atoms("builders/unstable/world-base"),
        "stable": packages - atoms("build/stable-excluded.txt") | atoms("builders/stable/world-base"),
    }
    drift = []
    for channel, world in worlds.items():
        path = ROOT / "builders" / channel / "world"
        text = "".join(a + "\n" for a in sorted(world, key=str.lower))
        if not path.exists() or path.read_text() != text:
            drift.append(channel)
            if not check:
                path.write_text(text)
    for channel in drift:
        print(f"builders/{channel}/world {'与清单不一致' if check else '已更新'}")
    return 1 if check and drift else 0


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--check"]):
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:] == ["--check"]))
