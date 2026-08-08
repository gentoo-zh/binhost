#!/usr/bin/env python3
"""The newest version of each major.minor series the overlay offers.

A distribution kernel puts every version in its own slot and the archive keeps
one build per series, so the series list has to come from the overlay rather
than from a written-down table: a bump inside a series then needs no edit and a
new series appears on its own.

Reads PACKAGE, OVERLAY and TREE from the environment, prints "series version".
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    MetadataUnavailable, pinned_portdbapi, split_cpv, vercmp,
)


def series_of(version):
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def newest_per_series(db, package):
    best = {}
    for cpv in db.match(package):
        version = split_cpv(str(cpv))[1]
        if version is None:
            continue
        key = series_of(version)
        if key not in best or (vercmp(version, best[key]) or 0) > 0:
            best[key] = version
    return best


def main():
    package = os.environ.get("PACKAGE", "sys-kernel/gentoo-cjk-kernel")
    overlay = os.environ.get("OVERLAY", "/var/lib/binhost/overlay")
    tree = os.environ.get("TREE", "/var/db/repos/gentoo")
    try:
        db = pinned_portdbapi(overlay, tree)
    except MetadataUnavailable as e:
        sys.exit(f"cannot read the overlay: {e}")
    best = newest_per_series(db, package)
    if not best:
        sys.exit(f"{package}: the overlay offers no version")
    for key in sorted(best, key=lambda k: [int(p) if p.isdigit() else p
                                           for p in k.split(".")]):
        print(f"{key} {best[key]}")


if __name__ == "__main__":
    main()
