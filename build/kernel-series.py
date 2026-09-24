#!/usr/bin/env python3
"""Print "series version" for every PACKAGE version in OVERLAY over TREE."""

import functools
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    MetadataUnavailable, pinned_portdbapi, split_cpv, vercmp,
)
from portage.versions import ver_regexp                       # noqa: E402


def series_of(version):
    match = ver_regexp.fullmatch(version)
    if match is None:
        raise ValueError(f"invalid Gentoo version: {version}")
    parts = [match.group(1), *match.group(2).lstrip(".").split(".")]
    return ".".join(p for p in parts[:2] if p)


def compare_versions(left, right):
    by_series = vercmp(left[0], right[0]) or 0
    return by_series or vercmp(left[1], right[1]) or 0


def all_versions(db, package):
    found = {(series_of(v), v) for v in
             (split_cpv(str(cpv))[1] for cpv in db.match(package)) if v}
    return sorted(found, key=functools.cmp_to_key(compare_versions))


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
