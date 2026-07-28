#!/bin/bash
# Push the site and nginx config to the mirror server.
#
# Only ever touches the site's own files: the mirror payload under
# /srv/mirrors/gentoo-zh/ is published separately by build/publish.sh and must
# not be caught by a --delete here.

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
cd "$(dirname "$0")"

# packages.json is not pushed here: its content follows the overlay and the
# mirror generates it on its own schedule.

# Caching relies on nginx sending Cache-Control: no-cache with an ETag. The
# stylesheet URL is no longer rewritten here: the path that normally applies is
# the cron pull, which syncs the HTML as written, and rewriting on only one of
# the two paths just creates the impression that a hash is doing something.
rsync -a --safe-links --delete site/assets/ "${REMOTE}:/srv/mirrors/assets/"
# The signing public key is not pushed from here. site-sync.sh installs it only
# when its fingerprint matches the one recorded on the mirror, and that check is
# the only thing standing between the repository and the trust anchor users
# import. Pushing it from a second path would walk around the check.
rsync -a --safe-links site/*.html "${REMOTE}:/srv/mirrors/"

rsync -a --safe-links nginx/ "${REMOTE}:/tmp/nginx-conf/"
# Back up before overwriting: by the time nginx -t fails the broken config is
# already on disk, and without a backup the only way out is editing by hand.
ssh "${REMOTE}" '
    bak=/etc/nginx.bak
    sudo rm -rf "${bak}"; sudo cp -a /etc/nginx "${bak}"
    sudo cp /tmp/nginx-conf/nginx.conf /etc/nginx/nginx.conf
    sudo cp /tmp/nginx-conf/distfiles.conf /etc/nginx/conf.d/distfiles.conf
    sudo cp /tmp/nginx-conf/mirror-common.inc /etc/nginx/conf.d/mirror-common.inc
    rm -rf /tmp/nginx-conf
    if ! sudo nginx -t; then
        echo "!! 配置不通过，已还原" >&2
        sudo rm -rf /etc/nginx; sudo mv "${bak}" /etc/nginx
        exit 1
    fi
    sudo rc-service nginx reload
'
echo ">>> deployed to ${REMOTE}"
