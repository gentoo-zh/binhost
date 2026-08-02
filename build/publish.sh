#!/bin/bash

set -euo pipefail

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

printf '%s\n' "${paths[@]}" |
    rsync -a --info=stats2 --files-from=- "${STAGE}/" "${REMOTE}:${REMOTE_ROOT}/" |
    grep -E "files transferred|Total transferred file size" | sed 's/^/    /'

rsync -a "${STAGE}/Packages" "${REMOTE}:${REMOTE_ROOT}/.Packages.new"
rsync -a "${STAGE}/Packages.gz" "${REMOTE}:${REMOTE_ROOT}/.Packages.gz.new"
# shellcheck disable=SC2029  # as above
ssh "${REMOTE}" "cd ${REMOTE_ROOT} && \
    mv -f .Packages.new Packages && \
    mv -f .Packages.gz.new Packages.gz"

ts=$(awk '/^TIMESTAMP: /{print $2; exit}' "${STAGE}/Packages")
n=$(awk '/^PACKAGES: /{print $2; exit}' "${STAGE}/Packages")
# shellcheck disable=SC2029  # REMOTE_ROOT is meant to expand locally
printf '{"packages":%s,"generated":%s}\n' "${n:-0}" "${ts:-0}" |
    ssh "${REMOTE}" "cat > ${REMOTE_ROOT}/.status.json.new &&
                     mv -f ${REMOTE_ROOT}/.status.json.new ${REMOTE_ROOT}/status.json"

# shellcheck disable=SC2029  # as above
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
