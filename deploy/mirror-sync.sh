#!/bin/bash
# For downstream mirrors: sync the gentoo-zh binhost into a local directory.
#
# PATH in the index is relative, so serving Packages together with the files at
# those same relative paths constitutes a complete binhost; users point
# sync-uri at that address.
#
# Use rsync://distfiles.gentoozh.org/gentoo-zh/binpkgs where rsync is
# available; this script is for the cases where only HTTP is.
#
#   DEST=/srv/mirror/gentoo-zh/binpkgs/x86-64 ./mirror-sync.sh
#
# Once a day is enough. Files already present are not fetched again: a package
# name carries its version and build id, so its content does not change.

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
    # 索引来自上游，PATH 直接拼进本地路径就等于让上游决定写到哪里。带 .. 的
    # 一条实测能写到 DEST 之外，覆盖执行账号有权限的任何文件。
    case ${path} in
        /*|*/../*|../*|*/..|..) echo "!! 索引里的路径不合法，跳过：${path}" >&2
                                failed=$((failed + 1)); continue ;;
    esac
    [[ -f ${DEST}/${path} ]] && continue
    mkdir -p "${DEST}/$(dirname "${path}")"
    # Write to a temporary name and rename, so an interruption cannot leave a
    # partial file passing for a complete package.
    if curl -fsSL --max-time 900 "${BASE}/${path}" -o "${DEST}/${path}.part"; then
        mv -f "${DEST}/${path}.part" "${DEST}/${path}"
        new=$((new + 1))
    else
        rm -f "${DEST}/${path}.part"
        echo "!!! 无法取得 ${path}" >&2
        failed=$((failed + 1))
    fi
done

# Do not swap the index while any package is missing. Swapping would point the
# new index at files that are not here, and emerge would meet a wall of 404s,
# whereas the old index is at least self-consistent. A transient upstream 5xx, a
# dropped connection or a full disk all end up here.
if (( failed )); then
    echo "!!! ${failed} 个包没取到，索引保持原样" >&2
    echo "    修好来源后重新执行；已取到的 ${new} 个不会重复下载" >&2
    exit 1
fi

# The index is written last, once everything it refers to is in place.
mv -f "${tmp}/Packages" "${DEST}/Packages"
mv -f "${tmp}/Packages.gz" "${DEST}/Packages.gz"

# Remove packages the index no longer names. After the index update, because
# until then they were still valid.
#
# Membership against a set, not by piping the list into grep -q: grep exits on
# the first match, printf dies of SIGPIPE, and pipefail turns that into a
# non-zero pipeline, which here reads as "not in the index" and deletes a
# package the index does name.
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
