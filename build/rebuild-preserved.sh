#!/bin/bash

set -euo pipefail

LOG="${1:-/var/log/binhost/preserved-rebuild.log}"
EMERGE=(emerge --usepkg --changed-use --with-bdeps=y --keep-going --quiet-build)

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
