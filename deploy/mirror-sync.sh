#!/bin/bash

set -euo pipefail

BASE="${BASE:-https://distfiles.gentoozh.org/binpkgs/x86-64}"
DEST="${DEST:-./x86-64}"

mkdir -p "${DEST}"

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

echo ">>> 取索引"
curl -fsS --max-time 60 "${BASE}/Packages" -o "${tmp}/Packages"
curl -fsS --max-time 60 "${BASE}/Packages.gz" -o "${tmp}/Packages.gz"

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${tmp}/Packages")
(( ${#paths[@]} )) || { echo "索引中没有包，中止" >&2; exit 1; }

echo ">>> ${#paths[@]} 个包"

new=0
failed=0
for path in "${paths[@]}"; do
    case ${path} in
        /*|*/../*|../*|*/..|..) echo "!! 索引里的路径不合法，跳过：${path}" >&2
                                failed=$((failed + 1)); continue ;;
    esac
    [[ -f ${DEST}/${path} ]] && continue
    mkdir -p "${DEST}/$(dirname "${path}")"
    if curl -fsSL --max-time 900 "${BASE}/${path}" -o "${DEST}/${path}.part"; then
        mv -f "${DEST}/${path}.part" "${DEST}/${path}"
        new=$((new + 1))
    else
        rm -f "${DEST}/${path}.part"
        echo "!!! 无法取得 ${path}" >&2
        failed=$((failed + 1))
    fi
done

if (( failed )); then
    echo "!!! ${failed} 个包没取到，索引保持原样" >&2
    echo "    修好来源后重新执行；已取到的 ${new} 个不会重复下载" >&2
    exit 1
fi

mv -f "${tmp}/Packages" "${DEST}/Packages"
mv -f "${tmp}/Packages.gz" "${DEST}/Packages.gz"

declare -A wanted=()
for p in "${paths[@]}"; do wanted["${p}"]=1; done

removed=0
while IFS= read -r -d '' f; do
    rel=${f#"${DEST}/"}
    [[ -v wanted["${rel}"] ]] || { rm -f "${f}"; removed=$((removed + 1)); }
done < <(find "${DEST}" -name '*.gpkg.tar' -print0)

find "${DEST}" -type d -empty -delete

echo ">>> 新增 ${new}，清理 ${removed}，共 ${#paths[@]}"
echo ">>> 将 ${DEST} 通过 HTTP 提供，用户 sync-uri 指向该地址即可"
