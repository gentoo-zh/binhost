#!/bin/bash

set -euo pipefail

BASE="${BASE:-https://distfiles.gentoozh.org/binpkgs/x86-64}"
DEST="${DEST:-./x86-64}"
MAX_REMOVE_SHARE="${MAX_REMOVE_SHARE:-50}"

mkdir -p "${DEST}"

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

echo ">>> 取索引"
curl -fsS --max-time 60 "${BASE}/Packages" -o "${tmp}/Packages"
curl -fsS --max-time 60 "${BASE}/Packages.gz" -o "${tmp}/Packages.gz"

mapfile -t paths < <(awk '/^PATH: /{print $2}' "${tmp}/Packages")
(( ${#paths[@]} )) || { echo "索引中没有包，中止" >&2; exit 1; }

declared=$(awk '/^PACKAGES: /{print $2; exit}' "${tmp}/Packages")
if [[ ${declared} =~ ^[0-9]+$ ]] && (( declared != ${#paths[@]} )); then
    echo "索引头部写 ${declared} 个，实际列出 ${#paths[@]} 个，索引不完整，中止" >&2
    exit 1
fi

if command -v gzip >/dev/null && ! cmp -s <(gzip -dc "${tmp}/Packages.gz") "${tmp}/Packages"; then
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
    if [[ -f ${DEST}/${path} ]]; then
        want=${size["${path}"]:-}
        [[ -z ${want} ]] && continue
        [[ $(stat -c %s "${DEST}/${path}" 2>/dev/null || echo -1) == "${want}" ]] && continue
        echo "!! ${path} 大小与索引不符，重新下载" >&2
        stale=$((stale + 1))
        rm -f "${DEST}/${path}"
    fi
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

if (( have > 0 && ${#retire[@]} * 100 > have * MAX_REMOVE_SHARE )) && [[ -z ${FORCE_REMOVE:-} ]]; then
    echo "!! 本轮要清理 ${#retire[@]}/${have} 个，超过 ${MAX_REMOVE_SHARE}%，未清理" >&2
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
