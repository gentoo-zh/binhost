#!/bin/bash

set -euo pipefail

LOG="${1:-/var/log/binhost/preserved-rebuild.log}"
CONSUMERS="${CONSUMERS:-/usr/local/bin/preserved-consumers}"
# No --usepkg: this set names the packages linking the preserved library, and a
# binary package built against the old one would come back linking it again.
EMERGE=(emerge --usepkg=n --changed-use --with-bdeps=y --keep-going --quiet-build)

if ! "${EMERGE[@]}" @preserved-rebuild >"${LOG}" 2>&1; then
    echo "!!! @preserved-rebuild 未完成" >&2
    tail -20 "${LOG}" >&2 || true
    exit 1
fi

# Asking whether the registry is empty fails a run that is fine: portage leaves
# an entry until some later merge notices nothing needs it, and the last step of
# a build is not a merge. Ask instead whether anything still links them.
if ! report=$(python3 "${CONSUMERS}" 2>&1); then
    echo "!!! 保留库仍有使用者，重建没有覆盖它们" >&2
    printf '%s\n' "${report}" >&2
    exit 1
fi
[[ -z ${report} ]] || printf '%s\n' "${report}"

rm -f "${LOG}"
