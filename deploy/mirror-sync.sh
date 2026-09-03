#!/bin/bash

set -euo pipefail

BASE="${BASE:-https://distfiles.gentoozh.org/binpkgs/x86-64}"
DEST="${DEST:-./x86-64}"
# A rate limit, not a veto: what one run leaves behind the next run deletes.
# A cap that refuses instead ratchets, because the files it declines to delete
# still count against the following run.
REMOVE_PER_RUN="${REMOVE_PER_RUN:-60}"

# Skip removal entirely when the index that was just fetched carries less than
# this share of the packages the previous one carried.
REMOVE_MIN_KEEP_SHARE="${REMOVE_MIN_KEEP_SHARE:-50}"

INDEX_FILES=(Packages Packages.gz)

mkdir -p "${DEST}"
# A negative limit would make the loop remove nothing and report a backlog
# that never drains.
[[ ${REMOVE_PER_RUN} =~ ^[0-9]+$ ]] || {
    echo "REMOVE_PER_RUN 应为非负整数，收到：${REMOVE_PER_RUN}" >&2
    exit 1
}

# Read before the new index replaces it. The file count is not the same number,
# because it also carries whatever is still waiting to be removed.
packages_before=$(awk '/^PACKAGES: /{print $2; exit}' "${DEST}/Packages" 2>/dev/null) ||
    packages_before=0
[[ ${packages_before} =~ ^[0-9]+$ ]] || packages_before=0

exec 9>"${DEST}/.mirror-sync.lock"
flock -n 9 || { echo "另一次镜像同步仍在执行，本次中止" >&2; exit 1; }

tmp=$(mktemp -d "${DEST}/.index-gen-XXXXXXXX")
chmod 755 "${tmp}"
cleanup() {
    [[ -z ${tmp:-} ]] || rm -rf -- "${tmp}"
}
trap cleanup EXIT

activate_index_generation() {
    local gen="$1" name seed="" switch relink=0 active old

    case ${gen} in
        .index-gen-?*) ;;
        *) echo "索引代际目录名不合法：${gen:-空}" >&2; return 1 ;;
    esac
    if [[ -e ${DEST}/.index && ! -L ${DEST}/.index ]]; then
        echo "${DEST}/.index 不是符号链接，无法切换索引" >&2
        return 1
    fi
    for name in "${INDEX_FILES[@]}"; do
        [[ -s ${DEST}/${gen}/${name} ]] || {
            echo "${DEST}/${gen}/${name} 缺失或为空，索引保持原样" >&2
            return 1
        }
        if [[ -L ${DEST}/${name} ]]; then
            [[ $(readlink "${DEST}/${name}") == ".index/${name}" ]] || {
                echo "${DEST}/${name} 没有指向 .index/${name}，无法切换索引" >&2
                return 1
            }
        else
            relink=1
        fi
    done

    switch="${DEST}/.index-switch-${BASHPID}"
    rm -f -- "${switch}"

    # Preserve what readers see while regular files are converted to links.
    if (( relink )); then
        seed=$(mktemp -d "${DEST}/.index-seed-XXXXXXXX")
        chmod 755 "${seed}"
        for name in "${INDEX_FILES[@]}"; do
            [[ -e ${DEST}/${name} ]] || continue
            cp -pL "${DEST}/${name}" "${seed}/${name}"
        done
        ln -s "${seed##*/}" "${switch}"
        mv -Tf "${switch}" "${DEST}/.index"
        for name in "${INDEX_FILES[@]}"; do
            ln -s ".index/${name}" "${switch}"
            mv -Tf "${switch}" "${DEST}/${name}"
        done
    fi

    ln -s "${gen}" "${switch}"
    mv -Tf "${switch}" "${DEST}/.index"

    active=$(readlink "${DEST}/.index")
    for old in "${DEST}"/.index-gen-* "${DEST}"/.index-seed-*; do
        [[ -d ${old} ]] || continue
        [[ ${old##*/} == "${active}" ]] || rm -rf -- "${old}"
    done
}

echo ">>> 取索引"
curl -fsS --max-time 60 "${BASE}/Packages" -o "${tmp}/Packages"
curl -fsS --max-time 60 "${BASE}/Packages.gz" -o "${tmp}/Packages.gz"

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${tmp}/Packages")
(( ${#paths[@]} )) || { echo "索引中没有包，中止" >&2; exit 1; }

heads=$(grep -c '^PACKAGES: ' "${tmp}/Packages")
if (( heads != 1 )); then
    echo "索引里有 ${heads} 行 PACKAGES 头部，应恰好一行，中止" >&2
    exit 1
fi
declared=$(awk '/^PACKAGES: /{print $2; exit}' "${tmp}/Packages")
if ! [[ ${declared} =~ ^[1-9][0-9]*$ ]]; then
    echo "索引头部的数量不是正整数：${declared:-空}，中止" >&2
    exit 1
fi
if (( declared != ${#paths[@]} )); then
    echo "索引头部写 ${declared} 个，实际列出 ${#paths[@]} 个，索引不完整，中止" >&2
    exit 1
fi

command -v gzip >/dev/null || { echo "需要 gzip 才能核对两份索引，中止" >&2; exit 1; }
if ! cmp -s <(gzip -dc "${tmp}/Packages.gz") "${tmp}/Packages"; then
    echo "Packages 与 Packages.gz 内容不一致，两者不是同一代，中止" >&2
    exit 1
fi

echo ">>> ${#paths[@]} 个包"

declare -A size=()
while read -r p s; do size["${p}"]=${s}; done < <(
    awk '/^PATH: /{p=$2} /^SIZE: /{if (p != "") {print p, $2; p=""}}' "${tmp}/Packages")

new=0
failed=0
stale=0
for path in "${paths[@]}"; do
    case ${path} in
        /*|*/../*|../*|*/..|..) echo "!! 索引里的路径不合法，跳过：${path}" >&2
                                failed=$((failed + 1)); continue ;;
    esac
    want=${size["${path}"]:-}
    if ! [[ ${want} =~ ^[0-9]+$ ]]; then
        echo "!! 索引没有给出 ${path} 的 SIZE，无法核对，跳过" >&2
        failed=$((failed + 1))
        continue
    fi
    if [[ -f ${DEST}/${path} ]]; then
        [[ $(stat -c %s "${DEST}/${path}" 2>/dev/null || echo -1) == "${want}" ]] && continue
        echo "!! ${path} 大小与索引不符，重新下载" >&2
        stale=$((stale + 1))
    fi
    mkdir -p "${DEST}/$(dirname "${path}")"
    if curl -fsSL --max-time 900 "${BASE}/${path}" -o "${DEST}/${path}.part"; then
        got=$(stat -c %s "${DEST}/${path}.part" 2>/dev/null || echo -1)
        if [[ ${got} != "${want}" ]]; then
            rm -f "${DEST}/${path}.part"
            echo "!!! ${path} 下载到 ${got} 字节，索引写 ${want}" >&2
            failed=$((failed + 1))
            continue
        fi
        mv -f "${DEST}/${path}.part" "${DEST}/${path}"
        new=$((new + 1))
    else
        rm -f "${DEST}/${path}.part"
        echo "!!! 无法取得 ${path}" >&2
        failed=$((failed + 1))
    fi
done

if (( failed )); then
    echo "!!! ${failed} 个包下载失败，索引保持原样" >&2
    echo "    来源恢复后重新执行；已取到的 ${new} 个不会重复下载" >&2
    exit 1
fi

gen=${tmp##*/}
tmp=""
activate_index_generation "${gen}"

declare -A wanted=()
for p in "${paths[@]}"; do wanted["${p}"]=1; done

retire=()
while IFS= read -r -d '' f; do
    rel=${f#"${DEST}/"}
    [[ -v wanted["${rel}"] ]] || retire+=("${f}")
done < <(find "${DEST}" -name '*.gpkg.tar' -print0)

base=${packages_before}
(( base > 0 )) || base=$(find "${DEST}" -name '*.gpkg.tar' -printf x | wc -c)
if (( base > 0 )) && [[ ${FORCE_REMOVE:-0} != 1 ]] &&
   (( ${#paths[@]} * 100 < base * REMOVE_MIN_KEEP_SHARE )); then
    echo "!! 本次索引 ${#paths[@]} 个包，上一份 ${base} 个，不足 ${REMOVE_MIN_KEEP_SHARE}%，未清理" >&2
    echo "   索引与已下载的包都已就位" >&2
    exit 3
fi

# Sorted so a run that hits the limit removes the same first slice every time.
if (( ${#retire[@]} )); then
    mapfile -t retire < <(printf '%s\n' "${retire[@]}" | sort)
fi
limit=${#retire[@]}
[[ ${FORCE_REMOVE:-0} == 1 ]] || (( limit <= REMOVE_PER_RUN )) || limit=${REMOVE_PER_RUN}

removed=0
for f in "${retire[@]+"${retire[@]}"}"; do
    (( removed < limit )) || break
    rm -f "${f}"
    removed=$((removed + 1))
done
pending=$(( ${#retire[@]} - removed ))

find "${DEST}" -type d -empty -delete

if (( pending )); then
    echo ">>> 新增 ${new}，重新下载 ${stale}，清理 ${removed}，还有 ${pending} 个由后续轮次清理，共 ${#paths[@]}"
else
    echo ">>> 新增 ${new}，重新下载 ${stale}，清理 ${removed}，共 ${#paths[@]}"
fi
echo ">>> 将 ${DEST} 通过 HTTP 提供，用户 sync-uri 指向该地址即可"
