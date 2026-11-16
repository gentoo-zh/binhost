#!/usr/bin/env python3
"""
check-new-deps.py <base-tree> <channel>
"""
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent


def world(tree, channel):
    path = tree / "builders" / channel / "world"
    text = path.read_text() if path.exists() else ""
    return {line.strip() for line in text.splitlines()
            if line.strip() and not line.startswith("#")}


def main(base, channel):
    added = world(REPO, channel) - world(pathlib.Path(base), channel)
    if not added:
        print(f">>> {channel}: 没有新增的包")
        return 0
    print(f">>> {channel}: 解析 {' '.join(sorted(added))}", flush=True)
    env = dict(os.environ, FEATURES="-getbinpkg", EMERGE_DEFAULT_OPTS="--with-bdeps=y")
    result = subprocess.run(
        ["emerge", "--pretend", "--quiet", "--oneshot", *sorted(added)],
        env=env, check=False)
    if result.returncode != 0:
        print(f"!!! {channel}: 依赖无法在构建机上满足", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
