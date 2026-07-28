#!/bin/bash
# Fetch distfiles onto the mirror. Runs hourly from cron.
#
# binpkgs are derived: lose one and a rebuild produces it again. distfiles are
# the originals -- once upstream drops a release it is gone. So this exists to
# preserve, not to save bandwidth.
#
# emirrordist reads the overlay's Manifests, verifies digests, maintains the
# mirror layout, and skips RESTRICT=mirror natively (an explicit check in
# FetchIterator.py), so nothing here has to gate that.

set -euo pipefail

# The body is a function so the last line is the only thing that runs it. bash
# reads a script by byte offset as it executes, so replacing the file mid-run
# (an rsync deploy, say) makes it resume at the same offset in the new file.
main() {
DEST="${DEST:-/srv/pub/distfiles}"
REPO="${REPO:-gentoo-zh}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
STATE="${STATE:-/var/lib/emirrordist}"
# Concurrency follows the upstreams, not the CPU. This box does BLAKE2B at
# 600 MB/s on one core while a distfile arrives at 2.4 MB/s -- the wait is the
# network. Six streams aggregate to about 15 MB/s, low enough that hosts like
# GitHub do not rate-limit us.
JOBS="${JOBS:-6}"
# A week. Once an ebuild leaves the overlay its distfile waits this long before
# deletion, which leaves room to roll back.
DELETION_DELAY="${DELETION_DELAY:-604800}"

install -dm755 "${DEST}" "${STATE}" "${STATE}/tmp" /var/log/emirrordist

# DELETE=0 fetches without deleting. Useful when the overlay has just dropped a
# batch of versions and the old files should stay until someone has looked.
delete=(--delete
        --deletion-db "${STATE}/deletion.db"
        --deletion-delay "${DELETION_DELAY}"
        --scheduled-deletion-log /var/log/emirrordist/deletions.log)
[[ ${DELETE:-1} == 0 ]] && delete=()

# The overlay copy is updated by daily.sh, not here: the package list step reads
# it too.
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
