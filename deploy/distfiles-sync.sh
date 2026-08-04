#!/bin/bash

set -euo pipefail

main() {
DEST="${DEST:-/srv/pub/distfiles}"
REPO="${REPO:-gentoo-zh}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
STATE="${STATE:-/var/lib/emirrordist}"
JOBS="${JOBS:-6}"

install -dm755 "${DEST}" "${STATE}" "${STATE}/tmp" /var/log/emirrordist

# audit-distfiles.py is the only process allowed to remove public files.
emirrordist \
    --mirror \
    --repo "${REPO}" \
    --distfiles "${DEST}" \
    --jobs "${JOBS}" \
    --distfiles-db "${STATE}/distfiles.db" \
    --failure-log /var/log/emirrordist/failures.log \
    --success-log /var/log/emirrordist/successes.log \
    --temp-dir "${STATE}/tmp"

n=$(find "${DEST}" -type f ! -name layout.conf | wc -l)
echo "$(date '+%F %T') ${n} files, $(du -sh "${DEST}" | cut -f1)"

}

main "$@"
