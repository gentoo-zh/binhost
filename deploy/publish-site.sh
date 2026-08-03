#!/bin/bash

set -euo pipefail

SRC="${1:?用法： $0 <site 目录> [目标目录]}"
DEST="${2:-${DEST:-/srv/mirrors}}"
FPR_FILE="${FPR_FILE:-/etc/binhost/signing-key.fpr}"

[[ -d ${SRC} ]] || { echo "!! ${SRC} 不存在" >&2; exit 1; }
[[ -r ${SRC}/gentoo-zh-binhost.asc ]] ||
    { echo "!! ${SRC} 未包含 gentoo-zh-binhost.asc" >&2; exit 1; }

if [[ ! -r ${FPR_FILE} ]]; then
    echo "!! ${FPR_FILE} 不存在，不发布任何内容" >&2
    exit 1
fi

mapfile -t want < <(tr -d ' \r' < "${FPR_FILE}" | grep -oE '[0-9A-Fa-f]{40}' | tr 'a-f' 'A-F')
mapfile -t got < <(gpg --with-colons --show-keys "${SRC}/gentoo-zh-binhost.asc" 2>/dev/null |
                   awk -F: '$1=="pub"{p=1;next} $1=="sub"{p=0} $1=="fpr"&&p{print $10;p=0}')
unexpected=()
for g in "${got[@]}"; do
    [[ " ${want[*]} " == *" ${g} "* ]] || unexpected+=("${g}")
done
if (( ${#want[@]} == 0 || ${#got[@]} == 0 || ${#unexpected[@]} )); then
    echo "!! 公钥未通过校验，不发布任何内容" >&2
    echo "   本机记录的指纹：${want[*]:-无}" >&2
    echo "   来源中的指纹：${got[*]:-无}" >&2
    echo "   记录之外的指纹：${unexpected[*]:-无}" >&2
    exit 1
fi

# One rsync, so a failure cannot leave assets from one generation beside pages
# from another. --delay-updates renames everything in at the end, which keeps
# that window down to the renames themselves.
#
# --delete only considers what the includes select. DEST also holds the
# published packages, and rsync does not delete excluded paths unless asked
# with --delete-excluded, so those stay.
rsync -a --checksum --safe-links --delete --delay-updates \
    --include='/assets/***' \
    --include='/gentoo-zh-binhost.asc' \
    --include='/*.html' \
    --include='/robots.txt' \
    --exclude='*' \
    "${SRC}/" "${DEST}/"
