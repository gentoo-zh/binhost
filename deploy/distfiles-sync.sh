#!/bin/bash

set -euo pipefail

main() {
DEST="${DEST:-/srv/pub/distfiles}"
REPO="${REPO:-gentoo-zh}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
STATE="${STATE:-/var/lib/emirrordist}"
JOBS="${JOBS:-6}"
# emirrordist renames a finished download into place, so the temporary
# directory has to be on the same filesystem as the distfiles. Default it to
# the mount point holding them, outside the directory nginx serves.
TEMP_DIR="${TEMP_DIR:-$(df -P "${DEST%/*}" | awk 'NR==2 {print $6}')/.emirrordist-tmp}"

install -dm755 "${DEST}" "${STATE}" "${TEMP_DIR}" /var/log/emirrordist

if [[ $(stat -c %d "${TEMP_DIR}") != $(stat -c %d "${DEST}") ]]; then
    echo "!! ${TEMP_DIR} 与 ${DEST} 不在同一个文件系统" >&2
    echo "   emirrordist 会以 rename 落地，跨设备时 portage 的回退路径本身有缺陷，整轮会中断" >&2
    exit 1
fi

# audit-distfiles.py is the only process allowed to remove public files.
emirrordist \
    --mirror \
    --repo "${REPO}" \
    --distfiles "${DEST}" \
    --jobs "${JOBS}" \
    --distfiles-db "${STATE}/distfiles.db" \
    --failure-log /var/log/emirrordist/failures.log \
    --success-log /var/log/emirrordist/successes.log \
    --temp-dir "${TEMP_DIR}"

n=$(find "${DEST}" -type f ! -name layout.conf | wc -l)
echo "$(date '+%F %T') ${n} files, $(du -sh "${DEST}" | cut -f1)"

}

main "$@"
