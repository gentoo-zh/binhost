#!/bin/bash

set -euo pipefail

main() {
TAG="${TAG:-x86-64}"
STAGE="${STAGE:-/var/lib/binhost/stage/${TAG}}"
REMOTE="${REMOTE:-mirror}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/pub/binpkgs/${TAG}}"

MAX_RETIRE_SHARE="${MAX_RETIRE_SHARE:-20}"
MAX_RETIRE_COUNT="${MAX_RETIRE_COUNT:-60}"

index_header_ok() {
    local file="$1" listed="$2" n
    n=$(grep -c '^PACKAGES: ' "${file}")
    if [ "${n}" -ne 1 ]; then
        echo "索引里有 ${n} 行 PACKAGES 头部，应恰好一行" >&2
        return 1
    fi
    declared=$(awk '/^PACKAGES: /{print $2; exit}' "${file}")
    if ! [[ ${declared} =~ ^[1-9][0-9]*$ ]]; then
        echo "索引头部的数量不是正整数：${declared:-空}" >&2
        return 1
    fi
    if (( declared != listed )); then
        echo "索引头部写 ${declared} 个，实际列出 ${listed} 个" >&2
        return 1
    fi
}

[[ -f ${STAGE}/Packages ]] || { echo "暂存区 ${STAGE} 里没有索引" >&2; exit 1; }

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${STAGE}/Packages")
(( ${#paths[@]} )) || { echo "索引里没有列出任何包" >&2; exit 1; }

missing=0
index_header_ok "${STAGE}/Packages" "${#paths[@]}" || { echo "中止发布" >&2; exit 1; }

if [[ ! -s ${STAGE}/Packages.gz ]]; then
    echo "缺少 ${STAGE}/Packages.gz，中止发布" >&2
    exit 1
fi
if ! cmp -s <(gzip -dc "${STAGE}/Packages.gz") "${STAGE}/Packages"; then
    echo "Packages 与 Packages.gz 内容不一致，中止发布" >&2
    exit 1
fi

while read -r p size; do
    actual=$(stat -c %s "${STAGE}/${p}" 2>/dev/null || echo -1)
    if [[ ${size} =~ ^[0-9]+$ ]] && (( actual != size )); then
        echo "!! ${p} 实际 ${actual} 字节，索引写 ${size}" >&2
        missing=$((missing + 1))
    fi
done < <(awk '/^PATH: /{p=$2} /^SIZE: /{if (p != "") {print p, $2; p=""}}' "${STAGE}/Packages")

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
# shellcheck disable=SC2029
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
    over=0
    [ \"\${n}\" -gt 0 ] && [ \"\${have}\" -gt 0 ] &&
        [ \$(( n * 100 )) -ge \$(( have * ${MAX_RETIRE_SHARE} )) ] && over=1
    [ \"\${n}\" -ge ${MAX_RETIRE_COUNT} ] && over=1
    if [ \"\${over}\" -eq 1 ] && [ '${FORCE_RETIRE:-0}' != 1 ]; then
        echo \"本轮要清理 \${n}/\${have} 个，达到 ${MAX_RETIRE_SHARE}% 或 ${MAX_RETIRE_COUNT} 个的上限，未清理\" >&2
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
