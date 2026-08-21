#!/usr/bin/env python3
"""Preserved libraries that something still links against.

A registry entry is not the same as a library still in use. portage drops an
unused one only when a later merge or unmerge notices, so a run that ends
without another merge leaves entries behind that harm nothing. emerge makes the
same distinction in `display_preserved_libs`: a consumer that is itself a
preserved library of the same package does not count, which is exactly the
shape binutils-libs takes when libctf and libopcodes reference libbfd.

Exit 0 when nothing outside the preserved set uses them, 1 when something does.
"""

import sys

import portage


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

    used = 0
    for cpv, paths in preserved.items():
        internal = {linkmap._obj_key(path) for path in paths}
        for path in paths:
            outside = [c for c in linkmap.findConsumers(path, greedy=False)
                       if linkmap._obj_key(c) not in internal]
            if not outside:
                print(f"仍在登记但没有使用者：{cpv} {path}")
                continue
            used += 1
            print(f"仍有使用者：{cpv} {path}")
            for consumer in sorted(outside)[:5]:
                print(f"    {consumer}")
    return 1 if used else 0


sys.exit(main())
