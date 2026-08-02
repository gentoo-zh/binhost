#!/bin/bash

set -euo pipefail

REPO="${REPO:-https://github.com/gentoo-zh/binhost}"
WORK="${WORK:-/var/lib/binhost-site}"
DEST="${DEST:-/srv/mirrors}"
BRANCH="${BRANCH:-master}"

fresh=0
if [[ -d ${WORK}/.git ]]; then
    git -C "${WORK}" fetch --quiet origin "${BRANCH}"
else
    git clone --quiet --depth=1 --branch "${BRANCH}" "${REPO}" "${WORK}"
    fresh=1
fi

before=$(git -C "${WORK}" rev-parse HEAD)
git -C "${WORK}" reset --quiet --hard "origin/${BRANCH}"
after=$(git -C "${WORK}" rev-parse HEAD)

DONE="${DONE:-${WORK}/.synced}"
synced=$(cat "${DONE}" 2>/dev/null || true)

(( fresh )) || [[ ${before} != "${after}" ]] || [[ ${synced} != "${after}" ]] || exit 0

rsync -a --safe-links --delete "${WORK}/site/assets/" "${DEST}/assets/"
FPR_FILE="${FPR_FILE:-/etc/binhost/signing-key.fpr}"
if [[ -r ${FPR_FILE} ]]; then
    mapfile -t want < <(tr -d ' \r' < "${FPR_FILE}" | grep -oE '[0-9A-Fa-f]{40}' | tr 'a-f' 'A-F')
    mapfile -t got < <(gpg --with-colons --show-keys "${WORK}/site/gentoo-zh-binhost.asc" 2>/dev/null |
                       awk -F: '/^fpr:/{print $10}')
    unexpected=()
    for g in "${got[@]}"; do
        [[ " ${want[*]} " == *" ${g} "* ]] || unexpected+=("${g}")
    done
    if (( ${#want[@]} && ${#got[@]} && ${#unexpected[@]} == 0 )); then
        rsync -a --safe-links "${WORK}/site/gentoo-zh-binhost.asc" "${DEST}/"
    else
        echo "!! 公钥没有同步：仓库里是 ${got[*]:-空}，本机记录是 ${want[*]:-空}，其中不认得 ${unexpected[*]:-无}" >&2
    fi
else
    echo "!! ${FPR_FILE} 不存在，公钥未同步" >&2
fi

rsync -a --safe-links --include='*.html' --include='robots.txt' --exclude='*' "${WORK}/site/" "${DEST}/"

for f in "${DEST}"/*.html; do
    [ -e "${f}" ] || continue
    [ -e "${WORK}/site/$(basename "${f}")" ] && continue
    echo "  移除已从仓库删掉的页面：$(basename "${f}")"
    rm -f "${f}"
done

printf '%s' "${after}" > "${DONE}"
echo "site updated ${before:0:7} -> ${after:0:7}"
