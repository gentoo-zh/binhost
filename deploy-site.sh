#!/bin/bash

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
LOCK="${LOCK:-/var/lib/binhost-site.lock}"
cd "$(dirname "$0")"

stage=$(ssh "${REMOTE}" 'mktemp -d')
# shellcheck disable=SC2064
trap "ssh '${REMOTE}' 'rm -rf ${stage}'" EXIT

rsync -a --safe-links site/assets "${REMOTE}:${stage}/"
rsync -a --safe-links site/*.html site/robots.txt "${REMOTE}:${stage}/"

# shellcheck disable=SC2029
ssh "${REMOTE}" "flock -w 300 '${LOCK}' -c '
    rsync -a --delete ${stage}/assets/ /srv/mirrors/assets/
    rsync -a ${stage}/*.html ${stage}/robots.txt /srv/mirrors/
'" || { echo "!! 未能取得镜像机上的站点锁（${LOCK}）" >&2; exit 1; }

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
