#!/bin/bash

set -euo pipefail

main() {
TAG="${TAG:-x86-64}"
STAGE="${STAGE:-/var/lib/binhost/stage/${TAG}}"
REMOTE="${REMOTE:-mirror}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/pub/binpkgs/${TAG}}"

MAX_RETIRE_SHARE="${MAX_RETIRE_SHARE:-50}"

[[ -f ${STAGE}/Packages ]] || { echo "暂存区 ${STAGE} 里没有索引" >&2; exit 1; }

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${STAGE}/Packages")
(( ${#paths[@]} )) || { echo "索引里没有列出任何包" >&2; exit 1; }

declared=$(awk '/^PACKAGES: /{print $2; exit}' "${STAGE}/Packages")
if [[ ${declared} =~ ^[0-9]+$ ]] && (( declared != ${#paths[@]} )); then
    echo "索引头部写 ${declared} 个，实际列出 ${#paths[@]} 个，中止发布" >&2
    exit 1
fi

missing=0
for p in "${paths[@]}"; do
    [[ -s ${STAGE}/${p} ]] || { echo "!! 索引列出但暂存区里没有或为空：${p}" >&2
                                missing=$((missing + 1)); }
done
(( missing )) && { echo "${missing} 个包不在暂存区，中止发布" >&2; exit 1; }

echo ">>> 发布 ${#paths[@]} 个包到 ${REMOTE}:${REMOTE_ROOT}"

# shellcheck disable=SC2029  # the path is meant to expand locally
ssh "${REMOTE}" "install -dm755 ${REMOTE_ROOT}"

printf '%s\n' "${paths[@]}" |
    rsync -a --info=stats2 --files-from=- "${STAGE}/" "${REMOTE}:${REMOTE_ROOT}/" |
    { grep -E "files transferred|Total transferred file size" || true; } | sed 's/^/    /'

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
    find . -name '*.gpkg.tar' -printf '%P\n' | sort > /tmp/binhost-have-${TAG}.txt
    have=\$(wc -l < /tmp/binhost-have-${TAG}.txt)
    grep -vxF -f /tmp/binhost-keep-${TAG}.txt /tmp/binhost-have-${TAG}.txt \
        > /tmp/binhost-retire-${TAG}.txt || true
    n=\$(wc -l < /tmp/binhost-retire-${TAG}.txt)
    if [ \"\${have}\" -gt 0 ] && [ \$(( n * 100 )) -gt \$(( have * ${MAX_RETIRE_SHARE} )) ] &&
       [ -z '${FORCE_RETIRE:-}' ]; then
        echo \"本轮要清理 \${n}/\${have} 个，超过 ${MAX_RETIRE_SHARE}%，未清理\" >&2
        echo \"确认无误后以 FORCE_RETIRE=1 重新执行\" >&2
        rm -f /tmp/binhost-keep-${TAG}.txt /tmp/binhost-have-${TAG}.txt /tmp/binhost-retire-${TAG}.txt
        exit 3
    fi
    tr '\\n' '\\0' < /tmp/binhost-retire-${TAG}.txt | xargs -0r rm -f
    find . -mindepth 1 -type d -empty -delete
    echo \"\${n}\"
    rm -f /tmp/binhost-keep-${TAG}.txt /tmp/binhost-have-${TAG}.txt /tmp/binhost-retire-${TAG}.txt") || {
    rc=$?
    if (( rc == 3 )); then
        echo ">>> 已发布 ${#paths[@]} 个；清理被上限拦下，索引与包体都已就位" >&2
        exit 3
    fi
    exit "${rc}"
}

echo ">>> 已发布 ${#paths[@]} 个，清理 ${retired} 个"

}

main "$@"
