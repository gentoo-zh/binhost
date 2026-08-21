#!/usr/bin/env python3
"""Preserved libraries that a rebuild was supposed to cover and did not.

A registry entry is not the same as a library still in use. portage drops an
unused one only when a later merge or unmerge notices, so a run that ends
without another merge leaves entries behind that harm nothing.

The question worth asking is the one `@preserved-rebuild` answers: which
installed packages consume a preserved library. portage builds that set in
`PreservedLibraryConsumerSet`, and two of its steps decide what counts.

It drops a consumer that is itself a preserved library of the same package,
which is the shape binutils-libs takes when libctf and libopcodes reference
libbfd. It then maps each remaining consumer back to its owning package and
silently drops the ones that map to nothing, calling that expected for
"preserved libraries of packages that have been uninstalled without
replacement".

An unowned consumer is therefore a file `@preserved-rebuild` cannot act on: no
package owns it, so no package can be rebuilt to replace it. Failing on one
asks the build for something portage has no way to deliver. It is reported and
allowed. A consumer that does map to an installed package is the real defect,
because the rebuild was asked to cover it and did not.

Exit 0 when every consumer is unowned or absent, 1 when an owned one remains.
"""

import sys

import portage


def owners(vardb, linkmap, path):
    """The installed packages owning path, as portage's own set resolves them."""
    found = []
    for cpv in linkmap.getOwners(path):
        try:
            pkg = vardb._pkg_str(cpv, None)
        except (KeyError, portage.exception.InvalidData):
            continue
        found.append(f"{pkg.cp}:{pkg.slot}")
    return found


def main():
    vardb = portage.db[portage.root]["vartree"].dbapi
    registry = vardb._plib_registry
    if registry is None:
        return 0

    registry.load()
    preserved = registry.getPreservedLibs()
    if not preserved:
        return 0

    linkmap = vardb._linkmap
    linkmap.rebuild()

    unrebuilt = 0
    for cpv, paths in preserved.items():
        internal = {linkmap._obj_key(path) for path in paths}
        for path in paths:
            outside = [c for c in linkmap.findConsumers(path, greedy=False)
                       if linkmap._obj_key(c) not in internal]
            if not outside:
                print(f"仍在登记但没有使用者：{cpv} {path}")
                continue
            owned = {}
            orphans = []
            for consumer in sorted(outside):
                atoms = owners(vardb, linkmap, consumer)
                if atoms:
                    owned[consumer] = atoms
                else:
                    orphans.append(consumer)
            if owned:
                unrebuilt += 1
                print(f"重建没有覆盖：{cpv} {path}")
                for consumer, atoms in list(owned.items())[:5]:
                    print(f"    {consumer}  属于 {' '.join(atoms)}")
            if orphans:
                print(f"无主使用者（portage 无法重建，放行）：{cpv} {path}")
                for consumer in orphans[:5]:
                    print(f"    {consumer}")
    return 1 if unrebuilt else 0


sys.exit(main())
