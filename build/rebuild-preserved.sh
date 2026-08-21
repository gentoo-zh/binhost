#!/bin/bash

set -euo pipefail

LOG="${1:-/var/log/binhost/preserved-rebuild.log}"
# No --usepkg: the packages this set names are exactly the ones linking the
# preserved library, and reinstalling one from a binary package that links
# it leaves the library preserved forever. Seen 2026-08-20 with
# app-emulation/looking-glass, whose binpkg from 07-26 still needed
# libbfd-2.46.0 after binutils-libs moved to 2.46.1.
EMERGE=(emerge --usepkg=n --changed-use --with-bdeps=y --keep-going --quiet-build)

if ! "${EMERGE[@]}" @preserved-rebuild >"${LOG}" 2>&1; then
    echo "!!! @preserved-rebuild 未完成" >&2
    tail -20 "${LOG}" >&2 || true
    exit 1
fi

if preserved=$(portageq list_preserved_libs / 2>&1); then
    echo "!!! @preserved-rebuild 完成后仍有保留库" >&2
    printf '%s\n' "${preserved}" >&2
    exit 1
else
    rc=$?
    if (( rc != 1 )); then
        echo "!!! 无法检查保留库" >&2
        printf '%s\n' "${preserved}" >&2
        exit 1
    fi
fi

rm -f "${LOG}"
