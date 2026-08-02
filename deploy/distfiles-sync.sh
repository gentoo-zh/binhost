#!/bin/bash

set -euo pipefail

main() {
DEST="${DEST:-/srv/pub/distfiles}"
REPO="${REPO:-gentoo-zh}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
STATE="${STATE:-/var/lib/emirrordist}"
JOBS="${JOBS:-6}"
DELETION_DELAY="${DELETION_DELAY:-86400}"
RECYCLE="${RECYCLE:-/var/lib/emirrordist/recycle}"
RECYCLE_DELAY="${RECYCLE_DELAY:-1209600}"

install -dm755 "${DEST}" "${STATE}" "${STATE}/tmp" "${RECYCLE}" /var/log/emirrordist

delete=(--delete
        --deletion-db "${STATE}/deletion.db"
        --deletion-delay "${DELETION_DELAY}"
        --scheduled-deletion-log /var/log/emirrordist/deletions.log
        --recycle-dir "${RECYCLE}"
        --recycle-db "${STATE}/recycle.db"
        --recycle-deletion-delay "${RECYCLE_DELAY}")
[[ ${DELETE:-1} == 0 ]] && delete=()

emirrordist \
    --mirror \
    --repo "${REPO}" \
    --distfiles "${DEST}" \
    --jobs "${JOBS}" \
    "${delete[@]}" \
    --distfiles-db "${STATE}/distfiles.db" \
    --failure-log /var/log/emirrordist/failures.log \
    --success-log /var/log/emirrordist/successes.log \
    --temp-dir "${STATE}/tmp"

n=$(find "${DEST}" -type f ! -name layout.conf | wc -l)
echo "$(date '+%F %T') ${n} files, $(du -sh "${DEST}" | cut -f1)"

}

main "$@"
