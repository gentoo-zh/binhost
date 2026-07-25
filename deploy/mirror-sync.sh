#!/bin/bash
# 供下游镜像站使用：将 gentoo-zh binhost 同步到本地目录。
#
# 索引中的 PATH 为相对路径，因此将 Packages 与相同相对路径下的文件一并提供，
# 即构成一个完整的 binhost，用户将 sync-uri 指向该地址即可。
#
# 需要 rsync 时用 rsync://distfiles.gentoozh.org/gentoo-zh/binpkgs，本脚本供只能
# 走 HTTP 的场合使用。
#
#   DEST=/srv/mirror/gentoo-zh/binpkgs/x86-64 ./mirror-sync.sh
#
# 建议每日执行一次。已存在的文件不会重复下载：包名含版本与 build id，内容不变。

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
    [[ -f ${DEST}/${path} ]] && continue
    mkdir -p "${DEST}/$(dirname "${path}")"
    # 先写临时文件再改名，中断时不会留下不完整的文件冒充完整包
    if curl -fsSL --max-time 900 "${BASE}/${path}" -o "${DEST}/${path}.part"; then
        mv -f "${DEST}/${path}.part" "${DEST}/${path}"
        new=$((new + 1))
    else
        rm -f "${DEST}/${path}.part"
        echo "!!! 无法取得 ${path}" >&2
        failed=$((failed + 1))
    fi
done

# 有包没取到就不换索引。换掉会让新索引指向本地不存在的文件，
# 使用者 emerge 收到的是一片 404，而旧索引至少还是自洽的。
# 上游临时 5xx、网络中断、磁盘满都会走到这里。
if (( failed )); then
    echo "!!! ${failed} 个包没取到，索引保持原样" >&2
    echo "    修好来源后重跑；已取到的 ${new} 个不会重复下载" >&2
    exit 1
fi

# 索引最后写入：此前它引用的文件均已就位。
mv -f "${tmp}/Packages" "${DEST}/Packages"
mv -f "${tmp}/Packages.gz" "${DEST}/Packages.gz"

# 清理索引中已不存在的包。置于索引更新之后：在此之前它们仍然有效。
removed=0
while IFS= read -r -d '' f; do
    rel=${f#"${DEST}/"}
    printf '%s\n' "${paths[@]}" | grep -qxF "${rel}" || { rm -f "${f}"; removed=$((removed + 1)); }
done < <(find "${DEST}" -name '*.gpkg.tar' -print0)

find "${DEST}" -type d -empty -delete

echo ">>> 新增 ${new}，清理 ${removed}，共 ${#paths[@]}"
echo ">>> 将 ${DEST} 通过 HTTP 提供，用户 sync-uri 指向该地址即可"
