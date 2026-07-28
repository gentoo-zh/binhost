#!/bin/bash
# Pull the published site onto the mirror. Runs from cron on the mirror itself.
#
# The mirror pulls rather than CI pushing, so nothing outside ever holds a key
# that reaches this machine and there is no inbound path to abuse. The cost is
# that a change lands within the poll interval instead of instantly, which for
# a static site is not a cost worth paying anything for.
#
# Only site content is synced. The nginx configuration stays a manual, root
# operation: a repository push should not be able to change how the server
# behaves.

set -euo pipefail

REPO="${REPO:-https://github.com/gentoo-zh/binhost}"
WORK="${WORK:-/var/lib/binhost-site}"
DEST="${DEST:-/srv/mirrors}"
BRANCH="${BRANCH:-master}"

# A fresh clone has nothing to compare against, so it must always deploy --
# otherwise a newly provisioned mirror waits for the next upstream commit
# before it ever serves the site.
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

(( fresh )) || [[ ${before} != "${after}" ]] || exit 0

# --delete only inside assets/: everything else in DEST belongs to the package
# publisher, and wiping it would take the repository down with the site.
rsync -a --delete "${WORK}/site/assets/" "${DEST}/assets/"
# packages.json is not here: gen-packages.py on the mirror produces it from the
# overlay, so its content follows the overlay rather than this repository's
# commits.
#
# The signing public key is the trust anchor users import. Carried by this
# five-minute automatic channel, anyone who can change the repository could
# replace it and the mirror would follow, while users still see our domain. So
# it is synced only when its fingerprint matches the one recorded on the server,
# which is read from the machine and not from the repository.
FPR_FILE="${FPR_FILE:-/etc/binhost/signing-key.fpr}"
if [[ -r ${FPR_FILE} ]]; then
    want=$(tr -d ' \n' < "${FPR_FILE}")
    got=$(gpg --with-colons --show-keys "${WORK}/site/gentoo-zh-binhost.asc" 2>/dev/null |
          awk -F: '/^fpr:/{print $10; exit}')
    if [[ ${got} == "${want}" ]]; then
        rsync -a "${WORK}/site/gentoo-zh-binhost.asc" "${DEST}/"
    else
        echo "!! 公钥指纹对不上，没有同步：仓库里是 ${got:-空}，本机记录是 ${want}" >&2
    fi
else
    echo "!! ${FPR_FILE} 不存在，公钥未同步" >&2
fi

# --include/--exclude rather than naming files one by one: missing a new page
# only means it does not go live, while naming a deleted one makes rsync return
# 23 and, under set -e, stops the whole sync. site/*.html with --delete is not
# an option either, because DEST also holds the published packages and
# distfiles.
rsync -a --include='*.html' --exclude='*' "${WORK}/site/" "${DEST}/"

# A page deleted from the repository used to stay served for good: rsync without
# --delete only ever adds. /mirror went on answering 200 with the old table for
# as long as nobody looked. Compare the two sets by name instead -- only the
# top-level .html files DEST got from here, never a directory, so the published
# packages are out of reach of this.
for f in "${DEST}"/*.html; do
    [ -e "${f}" ] || continue
    [ -e "${WORK}/site/$(basename "${f}")" ] && continue
    echo "  移除已从仓库删掉的页面：$(basename "${f}")"
    rm -f "${f}"
done

echo "site updated ${before:0:7} -> ${after:0:7}"
