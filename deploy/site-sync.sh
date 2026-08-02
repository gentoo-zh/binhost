#!/bin/bash

set -euo pipefail

REPO="${REPO:-https://github.com/gentoo-zh/binhost}"
WORK="${WORK:-/var/lib/binhost-site}"
DEST="${DEST:-/srv/mirrors}"
BRANCH="${BRANCH:-master}"
LOCK="${LOCK:-${WORK}.lock}"

if [[ -z ${SITE_SYNC_LOCKED:-} ]]; then
    mkdir -p "$(dirname "${LOCK}")"
    exec {lockfd}>"${LOCK}"
    flock -n "${lockfd}" || { echo "另一次站点同步正在进行（${LOCK}）"; exit 0; }
    export SITE_SYNC_LOCKED=1
fi

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

FPR_FILE="${FPR_FILE:-/etc/binhost/signing-key.fpr}"
if [[ ! -r ${FPR_FILE} ]]; then
    echo "!! ${FPR_FILE} 不存在，本轮不发布任何内容" >&2
    rm -f "${DONE}"
    exit 1
fi
mapfile -t want < <(tr -d ' \r' < "${FPR_FILE}" | grep -oE '[0-9A-Fa-f]{40}' | tr 'a-f' 'A-F')
mapfile -t got < <(gpg --with-colons --show-keys "${WORK}/site/gentoo-zh-binhost.asc" 2>/dev/null |
                   awk -F: '/^fpr:/{print $10}')
unexpected=()
for g in "${got[@]}"; do
    [[ " ${want[*]} " == *" ${g} "* ]] || unexpected+=("${g}")
done
if (( ${#want[@]} == 0 || ${#got[@]} == 0 || ${#unexpected[@]} )); then
    echo "!! 公钥未通过校验，本轮不发布任何内容" >&2
    echo "   本机记录的指纹：${want[*]:-无}" >&2
    echo "   仓库中的指纹：${got[*]:-无}" >&2
    echo "   记录中没有的指纹：${unexpected[*]:-无}" >&2
    rm -f "${DONE}"
    exit 1
fi

rsync -a --safe-links --delete "${WORK}/site/assets/" "${DEST}/assets/"
rsync -a --safe-links "${WORK}/site/gentoo-zh-binhost.asc" "${DEST}/"

rsync -a --safe-links --include='*.html' --include='robots.txt' --exclude='*' "${WORK}/site/" "${DEST}/"

for f in "${DEST}"/*.html; do
    [ -e "${f}" ] || continue
    [ -e "${WORK}/site/$(basename "${f}")" ] && continue
    echo "  移除已从仓库删掉的页面：$(basename "${f}")"
    rm -f "${f}"
done

printf '%s' "${after}" > "${DONE}"
echo "site updated ${before:0:7} -> ${after:0:7}"
