#!/bin/bash
# Publish a staged generation to the mirror.
#
# The order is deliberate. No interruption may leave a client reading an index
# that points at files which are not there:
#
#   1. packages first, deleting nothing -- the old index is still valid and
#      everything it names is still present
#   2. the index is written under a temporary name and renamed into place,
#      which is atomic within one filesystem
#   3. only then are the files the index no longer names removed
#
# Reversing that gives clients 404s for the length of the gap.

set -euo pipefail

# The body is a function so the last line is the only thing that runs it. bash
# reads a script by byte offset as it executes, so replacing the file mid-run
# makes it resume at the same offset in the new file.
main() {
TAG="${TAG:-x86-64}"
STAGE="${STAGE:-/var/lib/binhost/stage/${TAG}}"
REMOTE="${REMOTE:-mirror}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/pub/binpkgs/${TAG}}"

[[ -f ${STAGE}/Packages ]] || { echo "nothing staged at ${STAGE}" >&2; exit 1; }

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${STAGE}/Packages")
(( ${#paths[@]} )) || { echo "index lists no packages" >&2; exit 1; }

echo ">>> 发布 ${#paths[@]} 个包到 ${REMOTE}:${REMOTE_ROOT}"

# shellcheck disable=SC2029  # the path is meant to expand locally
ssh "${REMOTE}" "install -dm755 ${REMOTE_ROOT}"

# --- 1. packages ------------------------------------------------------------------
# Send what the index names, not the whole directory: the staging area can hold
# leftovers from the previous generation. No --delete here; removal waits until
# the index has been swapped.
printf '%s\n' "${paths[@]}" |
    rsync -a --info=stats2 --files-from=- "${STAGE}/" "${REMOTE}:${REMOTE_ROOT}/" |
    grep -E "files transferred|Total transferred file size" | sed 's/^/    /'

# --- 2. index ------------------------------------------------------------------
rsync -a "${STAGE}/Packages" "${REMOTE}:${REMOTE_ROOT}/.Packages.new"
rsync -a "${STAGE}/Packages.gz" "${REMOTE}:${REMOTE_ROOT}/.Packages.gz.new"
# shellcheck disable=SC2029  # as above
ssh "${REMOTE}" "cd ${REMOTE_ROOT} && \
    mv -f .Packages.new Packages && \
    mv -f .Packages.gz.new Packages.gz"

# --- 2b. two numbers for the site ----------------------------------------------------
# The front page needs the package count and the timestamp, nothing else.
# Reading them from the index does not work: the browser sends
# Accept-Encoding: gzip, nginx then ignores the Range and sends the whole file,
# so opening the front page costs 39 KB to read two numbers.
ts=$(awk '/^TIMESTAMP: /{print $2; exit}' "${STAGE}/Packages")
n=$(awk '/^PACKAGES: /{print $2; exit}' "${STAGE}/Packages")
# shellcheck disable=SC2029  # REMOTE_ROOT is meant to expand locally
printf '{"packages":%s,"generated":%s}\n' "${n:-0}" "${ts:-0}" |
    ssh "${REMOTE}" "cat > ${REMOTE_ROOT}/.status.json.new &&
                     mv -f ${REMOTE_ROOT}/.status.json.new ${REMOTE_ROOT}/status.json"

# --- 3. remove what the index no longer names -------------------------------------------------
# The index is the list, not a comparison against the staging area: the index is
# what the outside world sees. Removing files can leave empty directories behind,
# which is what a fully removed package looks like.
# shellcheck disable=SC2029  # as above
# 清单的行数一起送过去。原来只查「空」：一次中途断掉的传输留下的是截断的
# 清单，非空，于是 grep -vxF -f 把截断点之后的线上套件全当成该删的。
want=${#paths[@]}
# shellcheck disable=SC2029  # want 与路径都是本地展开
retired=$(printf '%s\n' "${paths[@]}" | ssh "${REMOTE}" "
    cat > /tmp/binhost-keep-${TAG}.txt
    got=\$(wc -l < /tmp/binhost-keep-${TAG}.txt)
    if [ \"\${got}\" -ne ${want} ]; then
        echo \"保留清单只收到 \${got} 行，应为 ${want}，中止清理\" >&2
        exit 1
    fi
    cd ${REMOTE_ROOT} || exit 1
    find . -name '*.gpkg.tar' -printf '%P\n' |
        grep -vxF -f /tmp/binhost-keep-${TAG}.txt |
        tee /tmp/binhost-retire-${TAG}.txt |
        tr '\\n' '\\0' | xargs -0r rm -f
    find . -mindepth 1 -type d -empty -delete
    wc -l < /tmp/binhost-retire-${TAG}.txt
    rm -f /tmp/binhost-keep-${TAG}.txt /tmp/binhost-retire-${TAG}.txt")

echo ">>> 已发布 ${#paths[@]} 个，清理 ${retired} 个"

}

main "$@"
