#!/usr/bin/env python3
"""Rewrite a package list so listed packages build every slot they offer.

emerge resolves one slot per atom, so a bare category/package builds only the
newest. Distribution kernels put each version in its own slot and we carry
several at once, so those packages are named in all-slots.txt and expanded
here into one slot atom per slot the overlay currently offers.

Expanding from the overlay rather than from a written-down list means a
version bump inside a slot needs no edit here, which is the point for a long
term support line.

Usage: expand-slots.py <packages> <all-slots> <overlay> <output>
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, MetadataUnavailable, pinned_portdbapi, split_cpv,
)

GENTOO_TREE = os.environ.get("GENTOO_TREE", "/var/db/repos/gentoo")


def read_marked(path):
    """category/package -> reason, one per line, tab separated."""
    out = {}
    previous = None
    for lineno, raw in enumerate(pathlib.Path(path).read_text().splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        package, separator, reason = raw.partition("\t")
        package, reason = package.strip(), reason.strip()
        if not separator or not reason:
            sys.exit(f"{path}:{lineno}: needs a tab and a reason")
        if not ATOM.match(package):
            sys.exit(f"{path}:{lineno}: not a category/package: {package!r}")
        if package in out:
            sys.exit(f"{path}:{lineno}: duplicate: {package}")
        if previous is not None and package.lower() < previous:
            sys.exit(f"{path}:{lineno}: not sorted")
        out[package] = reason
        previous = package.lower()
    return out


def slots_of(db, package):
    """Every slot the overlay offers for this package, newest version first."""
    found = {}
    for cpv in db.match(package):
        slot = db.aux_get(cpv, ["SLOT"], myrepo="gentoo-zh")[0].split("/", 1)[0]
        found.setdefault(slot, cpv)
    return found


def expand(packages, marked, db):
    out = []
    for package in packages:
        if package not in marked:
            out.append(package)
            continue
        slots = slots_of(db, package)
        if not slots:
            sys.exit(f"{package}: listed in all-slots but the overlay has no version")
        for slot in sorted(slots, key=lambda s: split_cpv(slots[s])[1] or ""):
            out.append(f"{package}:{slot}")
    return out


def main(packages_path, marked_path, overlay, out_path):
    packages = [l.strip() for l in pathlib.Path(packages_path).read_text().splitlines()
                if l.strip() and not l.strip().startswith("#")]
    marked = read_marked(marked_path)
    unknown = sorted(set(marked) - set(packages))
    if unknown:
        sys.exit(f"{marked_path}: not in the package list: {', '.join(unknown)}")
    try:
        db = pinned_portdbapi(overlay, GENTOO_TREE)
    except MetadataUnavailable as e:
        sys.exit(f"cannot read the overlay, nothing expanded: {e}")
    lines = expand(packages, marked, db)
    pathlib.Path(out_path).write_text("\n".join(lines) + "\n")
    added = len(lines) - len(packages)
    print(f">>> {len(lines)} atoms ({added} extra slots from {len(marked)} packages)")


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__.strip().splitlines()[-1])
    main(*sys.argv[1:])
