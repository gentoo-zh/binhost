#!/usr/bin/env python3
"""Every version of the package the overlay offers, with its series.

The -bin ebuilds fetch these files by URL, so one has to exist for every
version the overlay carries: dropping a file that an ebuild still names leaves
that version unfetchable. The overlay is therefore the whole answer, both for
what to build and for what to keep.

The series is the major.minor pair and only decides which directory the file
goes in, matching the layout Gentoo uses for its own dist-kernel archive.

Reads PACKAGE, OVERLAY and TREE from the environment, prints "series version".
"""

import functools
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


def all_versions(db, package):
    """[(series, version)], ordered by series then by version."""
    found = {(series_of(v), v) for v in
             (split_cpv(str(cpv))[1] for cpv in db.match(package)) if v}
    return sorted(found, key=lambda pair: (
        [int(p) if p.isdigit() else p for p in pair[0].split(".")],
        functools.cmp_to_key(vercmp)(pair[1]),
    ))


def main():
    package = os.environ.get("PACKAGE", "sys-kernel/gentoo-cjk-kernel")
    overlay = os.environ.get("OVERLAY", "/var/lib/binhost/overlay")
    tree = os.environ.get("TREE", "/var/db/repos/gentoo")
    try:
        db = pinned_portdbapi(overlay, tree)
    except MetadataUnavailable as e:
        sys.exit(f"cannot read the overlay: {e}")
    found = all_versions(db, package)
    if not found:
        sys.exit(f"{package}: the overlay offers no version")
    for series, version in found:
        print(f"{series} {version}")


if __name__ == "__main__":
    main()
