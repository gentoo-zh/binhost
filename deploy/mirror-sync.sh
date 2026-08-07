#!/bin/bash

set -euo pipefail

BASE="${BASE:-https://distfiles.gentoozh.org/binpkgs/x86-64}"
DEST="${DEST:-./x86-64}"
MAX_REMOVE_SHARE="${MAX_REMOVE_SHARE:-20}"
MAX_REMOVE_COUNT="${MAX_REMOVE_COUNT:-60}"

before=$(find "${DEST}" -name '*.gpkg.tar' -printf x 2>/dev/null | wc -c)

mkdir -p "${DEST}"

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

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

mv -f "${tmp}/Packages" "${DEST}/Packages"
mv -f "${tmp}/Packages.gz" "${DEST}/Packages.gz"

declare -A wanted=()
for p in "${paths[@]}"; do wanted["${p}"]=1; done

retire=()
have=0
while IFS= read -r -d '' f; do
    have=$((have + 1))
    rel=${f#"${DEST}/"}
    [[ -v wanted["${rel}"] ]] || retire+=("${f}")
done < <(find "${DEST}" -name '*.gpkg.tar' -print0)

over=0
base=${before}
(( base > 0 )) || base=${have}
(( ${#retire[@]} > 0 && base > 0 && ${#retire[@]} * 100 >= base * MAX_REMOVE_SHARE )) && over=1
(( ${#retire[@]} >= MAX_REMOVE_COUNT )) && over=1
if (( over )) && [[ ${FORCE_REMOVE:-0} != 1 ]]; then
    echo "!! 本次要清理 ${#retire[@]} 个，本次之前有 ${base} 个，达到 ${MAX_REMOVE_SHARE}% 或 ${MAX_REMOVE_COUNT} 个的上限，未清理" >&2
    echo "   索引与已下载的包都已就位，确认无误后以 FORCE_REMOVE=1 重新执行" >&2
    exit 3
fi

removed=0
for f in "${retire[@]}"; do
    rm -f "${f}"
    removed=$((removed + 1))
done

find "${DEST}" -type d -empty -delete

echo ">>> 新增 ${new}，重新下载 ${stale}，清理 ${removed}，共 ${#paths[@]}"
echo ">>> 将 ${DEST} 通过 HTTP 提供，用户 sync-uri 指向该地址即可"
