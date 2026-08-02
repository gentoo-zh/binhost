#!/bin/bash

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
cd "$(dirname "$0")"


rsync -a --safe-links --delete site/assets/ "${REMOTE}:/srv/mirrors/assets/"
rsync -a --safe-links site/*.html site/robots.txt "${REMOTE}:/srv/mirrors/"

rsync -a --safe-links nginx/ "${REMOTE}:/tmp/nginx-conf/"
ssh "${REMOTE}" '
    bak=/etc/nginx.bak
    sudo rm -rf "${bak}"; sudo cp -a /etc/nginx "${bak}"
    sudo cp /tmp/nginx-conf/nginx.conf /etc/nginx/nginx.conf
    sudo cp /tmp/nginx-conf/distfiles.conf /etc/nginx/conf.d/distfiles.conf
    sudo cp /tmp/nginx-conf/mirror-common.inc /etc/nginx/conf.d/mirror-common.inc
    sudo cp /tmp/nginx-conf/headers-site.inc /etc/nginx/conf.d/headers-site.inc
    sudo cp /tmp/nginx-conf/headers-files.inc /etc/nginx/conf.d/headers-files.inc
    rm -rf /tmp/nginx-conf
    if ! sudo nginx -t; then
        echo "!! 配置不通过，已还原" >&2
        sudo rm -rf /etc/nginx; sudo mv "${bak}" /etc/nginx
        exit 1
    fi
    sudo rc-service nginx reload
'
echo ">>> deployed to ${REMOTE}"
