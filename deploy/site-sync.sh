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

PUBLISH="${PUBLISH:-}"
if [[ -z ${PUBLISH} ]]; then
    for c in "$(dirname "$0")/publish-site.sh" /usr/local/lib/binhost/publish-site.sh; do
        [[ -x ${c} ]] && { PUBLISH="${c}"; break; }
    done
fi
if [[ ! -x ${PUBLISH} ]]; then
    echo "!! 未找到 publish-site.sh，本轮不发布任何内容" >&2
    rm -f "${DONE}"
    exit 1
fi

if ! "${PUBLISH}" "${WORK}/site" "${DEST}"; then
    rm -f "${DONE}"
    exit 1
fi

printf '%s' "${after}" > "${DONE}"
echo "site updated ${before:0:7} -> ${after:0:7}"
