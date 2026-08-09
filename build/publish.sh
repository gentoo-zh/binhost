#!/bin/bash

set -euo pipefail

main() {
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=build/channel.sh
. "${SCRIPT_DIR}/channel.sh"

STAGE="${STAGE:-/var/lib/binhost/stage/${CHANNEL_STORAGE}}"
REMOTE="${REMOTE:-mirror}"
REMOTE_ROOT="${REMOTE_ROOT:-${CHANNEL_REMOTE_ROOT}}"

MAX_RETIRE_SHARE="${MAX_RETIRE_SHARE:-20}"
MAX_RETIRE_COUNT="${MAX_RETIRE_COUNT:-60}"

# These six describe one generation and have to change together. Each name on
# the mirror is a symlink into .gen/, and .gen is a symlink to the generation
# directory, so replacing all six is one rename of .gen.
GEN_FILES=(Packages Packages.gz installed.txt official.txt source.txt generation.json)

# Every publisher writes the same staging names under REMOTE_ROOT, so two of
# them at once would interleave into one mixed generation. One builder plus the
# local lock is not the guarantee: a manual run and the timer are two.
RUN_ID="${RUN_ID:-$(hostname -s)-$$-$(date +%s)}"
LOCK_DIR="${LOCK_DIR:-${REMOTE_ROOT}/.publish.lock}"
LOCK_STALE_H="${LOCK_STALE_H:-6}"

# shellcheck disable=SC2029
ssh "${REMOTE}" "install -dm755 ${REMOTE_ROOT}"

# shellcheck disable=SC2029
held=$(ssh "${REMOTE}" "
    set -u
    if mkdir '${LOCK_DIR}' 2>/dev/null; then
        printf '%s\n' '${RUN_ID}' > '${LOCK_DIR}/owner'
        echo taken
        exit 0
    fi
    age=\$(( \$(date +%s) - \$(stat -c %Y '${LOCK_DIR}' 2>/dev/null || date +%s) ))
    if [ \"\${age}\" -ge \$(( ${LOCK_STALE_H} * 3600 )) ]; then
        rm -rf '${LOCK_DIR}'
        if mkdir '${LOCK_DIR}' 2>/dev/null; then
            printf '%s\n' '${RUN_ID}' > '${LOCK_DIR}/owner'
            echo stale-taken
            exit 0
        fi
    fi
    printf 'busy %s\n' \"\$(cat '${LOCK_DIR}/owner' 2>/dev/null || echo 未知)\"
") || { echo "!! 无法在镜像机上取得发布锁" >&2; exit 1; }

case "${held}" in
    taken) ;;
    stale-taken) echo ">>> 接管了超过 ${LOCK_STALE_H} 小时的陈旧发布锁" ;;
    *) echo "!! 镜像机上已有发布进行中（${held#busy }），本次不发布" >&2; exit 1 ;;
esac

release_lock() {
    # shellcheck disable=SC2029
    ssh "${REMOTE}" "
        if [ \"\$(cat '${LOCK_DIR}/owner' 2>/dev/null)\" = '${RUN_ID}' ]; then
            rm -rf '${LOCK_DIR}'
        fi" 2>/dev/null || true
}
trap release_lock EXIT
QUARANTINE="${STAGE}/quarantine.txt"

if [[ -s ${QUARANTINE} ]]; then
    q=$(wc -l < "${QUARANTINE}")
    echo ">>> ${q} 个产物不可继续散布，先从公开路径移除"
    # shellcheck disable=SC2029
    gone=$(ssh "${REMOTE}" "
        set -eu
        cd ${REMOTE_ROOT} || exit 1
        tmp=\$(mktemp -d) || exit 1
        trap 'rm -rf \"\${tmp}\"' EXIT
        cat > \"\${tmp}/deny\"
        n=0
        while IFS= read -r rel; do
            [ -n \"\${rel}\" ] || continue
            case \"\${rel}\" in /*|*..*) echo \"拒绝：\${rel}\" >&2; exit 1 ;; esac
            if [ -e \"\${rel}\" ]; then rm -f -- \"\${rel}\" && n=\$(( n + 1 )); fi
        done < \"\${tmp}/deny\"
        find . -mindepth 1 -type d -empty -delete
        echo \"\${n}\"" < "${QUARANTINE}") || {
        echo "!! 不可继续散布的产物未能移除" >&2
        exit 1
    }
    echo ">>> 实际移除 ${gone} 个"
fi

if [[ -s ${STAGE}/publish-blocked.txt ]]; then
    cat "${STAGE}/publish-blocked.txt" >&2
    exit 1
fi

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

[[ -f ${STAGE}/Packages ]] || { echo "暂存区 ${STAGE} 不存在索引" >&2; exit 1; }

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${STAGE}/Packages")
(( ${#paths[@]} )) || { echo "索引未列出任何软件包" >&2; exit 1; }

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

while read -r n path nsize size; do
    if (( n != 1 )); then
        echo "!! 有 ${n} 行 PATH 的 stanza：${path:-未知}" >&2
        missing=$((missing + 1))
        continue
    fi
    if (( nsize != 1 )); then
        echo "!! ${path} 有 ${nsize} 行 SIZE，应恰好一行" >&2
        missing=$((missing + 1))
        continue
    fi
    if ! [[ ${size} =~ ^[0-9]+$ ]]; then
        echo "!! ${path} 的 SIZE 不是非负整数：${size}" >&2
        missing=$((missing + 1))
        continue
    fi
    actual=$(stat -c %s "${STAGE}/${path}" 2>/dev/null || echo -1)
    if (( actual != size )); then
        echo "!! ${path} 实际 ${actual} 字节，索引写 ${size}" >&2
        missing=$((missing + 1))
    fi
done < <(awk -v RS='' '
    {
        np = 0; ns = 0; path = ""; size = ""
        n = split($0, lines, "\n")
        for (i = 1; i <= n; i++) {
            if (lines[i] ~ /^PATH: /) { np++; sub(/^PATH: /, "", lines[i]); path = lines[i] }
            if (lines[i] ~ /^SIZE: /) { ns++; sub(/^SIZE: /, "", lines[i]); size = lines[i] }
        }
        if (np || ns) print np, path, ns, size
    }' "${STAGE}/Packages")

dupes=$(printf '%s\n' "${paths[@]}" | sort | uniq -d)
if [[ -n ${dupes} ]]; then
    echo "!! 索引里有重复的 PATH：" >&2
    printf '   %s\n' "${dupes}" >&2
    missing=$((missing + 1))
fi

for p in "${paths[@]}"; do
    case ${p} in
        /*|*/../*|../*|*/..|..|"") echo "!! 索引里的 PATH 不合法：${p}" >&2
                                   missing=$((missing + 1)); continue ;;
    esac
    [[ -s ${STAGE}/${p} ]] || { echo "!! 索引列出但暂存区不存在或为空：${p}" >&2
                                missing=$((missing + 1)); }
done
(( missing )) && { echo "索引有 ${missing} 处不合规，中止发布" >&2; exit 1; }

python3 "$(dirname "$0")/generation.py" verify "${STAGE}" || {
    echo "同代清单验证失败，中止发布" >&2
    exit 1
}

echo ">>> 发布 ${#paths[@]} 个包到 ${REMOTE}:${REMOTE_ROOT}"

# shellcheck disable=SC2029
before=$(ssh "${REMOTE}" "find ${REMOTE_ROOT} -name '*.gpkg.tar' -printf x 2>/dev/null | wc -c")
[[ ${before} =~ ^[0-9]+$ ]] || before=0

printf '%s\n' "${paths[@]}" |
    rsync -a --info=stats2 --files-from=- "${STAGE}/" "${REMOTE}:${REMOTE_ROOT}/" |
    { grep -E "files transferred|Total transferred file size" || true; } | sed 's/^/    /'

GEN=".gen-${RUN_ID}"
# shellcheck disable=SC2029  # REMOTE_ROOT is meant to expand locally
ssh "${REMOTE}" "install -dm755 '${REMOTE_ROOT}/${GEN}'"
printf '%s\n' "${GEN_FILES[@]}" |
    rsync -a --files-from=- "${STAGE}/" "${REMOTE}:${REMOTE_ROOT}/${GEN}/"

# shellcheck disable=SC2029  # REMOTE_ROOT and GEN are meant to expand locally
if ! ssh "${REMOTE}" "sh -s '${REMOTE_ROOT}' '${GEN}' ${GEN_FILES[*]}" <<'SWITCH'
set -u
cd "$1" || exit 1
gen="$2"
shift 2
files="$*"
tmp=".switch-${gen#.gen-}"

if [ -e .gen ] && [ ! -L .gen ]; then
    echo "!! .gen 不是符号链接，无法切换代际" >&2
    exit 1
fi

# Turning the six names into links must not change what they resolve to, so
# the first run seeds a generation from what is already published. From then on
# the rename at the end is the only thing a reader can observe.
relink=0
for name in ${files}; do
    [ -L "${name}" ] || relink=1
done
if [ "${relink}" = 1 ]; then
    seed=".gen-seed-${gen#.gen-}"
    rm -rf "${seed}" && mkdir "${seed}" || exit 1
    # -L is cp's default and is written out because it is the point: a name
    # that is already a link contributes what it resolves to, so a root where
    # only some names were converted is seeded by value like the rest.
    for name in ${files}; do
        [ -e "${name}" ] || continue
        cp -pL "${name}" "${seed}/${name}" || exit 1
    done
    ln -sfn "${seed}" "${tmp}" && mv -Tf "${tmp}" .gen || exit 1
    for name in ${files}; do
        ln -sfn ".gen/${name}" "${tmp}" && mv -Tf "${tmp}" "${name}" || exit 1
    done
fi

# After the seed, so that aborting here leaves the six reading what they read
# before this run rather than a half-built generation.
for name in ${files}; do
    if [ ! -s "${gen}/${name}" ]; then
        echo "!! ${gen}/${name} 缺失或为空，不切换" >&2
        exit 1
    fi
done

ln -sfn "${gen}" "${tmp}" || exit 1
mv -Tf "${tmp}" .gen || { rm -f "${tmp}"; exit 1; }

for old in .gen-*; do
    [ -d "${old}" ] || continue
    [ "${old}" = "${gen}" ] || rm -rf "${old}"
done
SWITCH
then
    echo "!! 代际未能切换，公开的仍是上一代" >&2
    exit 1
fi

ts=$(awk '/^TIMESTAMP: /{print $2; exit}' "${STAGE}/Packages")
n=$(awk '/^PACKAGES: /{print $2; exit}' "${STAGE}/Packages")
overlay="" deps=""
if [[ -r ${STAGE}/counts.txt ]]; then
    { read -r overlay; read -r deps; } < "${STAGE}/counts.txt" || true
fi
[[ ${overlay} =~ ^[0-9]+$ ]] || overlay=${n:-0}
[[ ${deps} =~ ^[0-9]+$ ]] || deps=0
# shellcheck disable=SC2029  # REMOTE_ROOT is meant to expand locally
printf '{"packages":%s,"overlay":%s,"deps":%s,"generated":%s}\n' \
    "${n:-0}" "${overlay}" "${deps}" "${ts:-0}" |
    ssh "${REMOTE}" "cat > ${REMOTE_ROOT}/.status.json.${RUN_ID}.new &&
                     mv -f ${REMOTE_ROOT}/.status.json.${RUN_ID}.new ${REMOTE_ROOT}/status.json"

# shellcheck disable=SC2029  # as above
want=${#paths[@]}
# shellcheck disable=SC2029
retired=$(printf '%s\n' "${paths[@]}" | ssh "${REMOTE}" "
    set -u
    tmp=\$(mktemp -d) || exit 1
    trap 'rm -rf \"\${tmp}\"' EXIT
    cat > \"\${tmp}/keep\"
    got=\$(wc -l < \"\${tmp}/keep\")
    if [ \"\${got}\" -ne ${want} ]; then
        echo \"保留清单只收到 \${got} 行，应为 ${want}，中止清理\" >&2
        exit 1
    fi
    cd ${REMOTE_ROOT} || exit 1
    find . -name '*.gpkg.tar' -printf '%P\n' | sort > \"\${tmp}/have\"
    have=\$(wc -l < \"\${tmp}/have\")
    grep -vxF -f \"\${tmp}/keep\" \"\${tmp}/have\" \
        > \"\${tmp}/retire\" || true
    n=\$(wc -l < \"\${tmp}/retire\")
    over=0
    base=${before}
    [ \"\${base}\" -gt 0 ] || base=\${have}
    [ \"\${n}\" -gt 0 ] && [ \"\${base}\" -gt 0 ] &&
        [ \$(( n * 100 )) -ge \$(( base * ${MAX_RETIRE_SHARE} )) ] && over=1
    [ \"\${n}\" -ge ${MAX_RETIRE_COUNT} ] && over=1
    if [ \"\${over}\" -eq 1 ] && [ '${FORCE_RETIRE:-0}' != 1 ]; then
        echo \"本次要清理 \${n} 个，本次之前有 \${base} 个，达到 ${MAX_RETIRE_SHARE}% 或 ${MAX_RETIRE_COUNT} 个的上限，未清理\" >&2
        echo \"确认无误后以 FORCE_RETIRE=1 重新执行\" >&2
        exit 3
    fi
    tr '\\n' '\\0' < \"\${tmp}/retire\" | xargs -0r rm -f
    find . -mindepth 1 -type d -empty -delete
    echo \"\${n}\"") || {
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
