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
# A day. Once an ebuild leaves the overlay its distfile waits this long before
# it is moved out of the mirror.
DELETION_DELAY="${DELETION_DELAY:-86400}"
# Where those files wait before they are gone for good, and for how long. This
# is the layer that matters: with the trigger at one day, a wrong call reaches
# here within a day, and this window is the only chance to notice it. Two weeks
# is two of the weekly checks.
RECYCLE="${RECYCLE:-/var/lib/emirrordist/recycle}"
RECYCLE_DELAY="${RECYCLE_DELAY:-1209600}"

install -dm755 "${DEST}" "${STATE}" "${STATE}/tmp" "${RECYCLE}" /var/log/emirrordist

# DELETE=0 fetches without deleting. Useful when the overlay has just dropped a
# batch of versions and the old files should stay until someone has looked.
delete=(--delete
        --deletion-db "${STATE}/deletion.db"
        --deletion-delay "${DELETION_DELAY}"
        --scheduled-deletion-log /var/log/emirrordist/deletions.log
        # Deleted files move here first and are only removed for good after
        # RECYCLE_DELAY. emirrordist decides what to delete from what it managed
        # to read this round, and it exits 0 whether or not it read anything: if
        # the main tree is missing or unsynced, every ebuild fails aux_get, no
        # file has an owner, and the whole mirror is scheduled for deletion with
        # an empty failure log and nothing to alert on. The header of this file
        # says these are originals that cannot be fetched again, so the delay
        # alone is not enough of a guard.
        --recycle-dir "${RECYCLE}"
        --recycle-db "${STATE}/recycle.db"
        --recycle-deletion-delay "${RECYCLE_DELAY}")
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
