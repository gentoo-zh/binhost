#!/bin/bash

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
LOCK="${LOCK:-/var/lib/binhost-site.lock}"
cd "$(dirname "$0")"

stage=$(ssh "${REMOTE}" 'mktemp -d')
# shellcheck disable=SC2064
trap "ssh '${REMOTE}' 'rm -rf ${stage}'" EXIT

rsync -a --safe-links site/ "${REMOTE}:${stage}/"

# shellcheck disable=SC2029  # stage and LOCK are meant to expand locally
ssh "${REMOTE}" "flock -w 300 '${LOCK}' -c \
    '/usr/local/lib/binhost/publish-site.sh ${stage} /srv/mirrors'" ||
    { echo "!! 站点未发布：未取得站点锁，或公钥校验未通过" >&2; exit 1; }

rsync -a --safe-links nginx/ "${REMOTE}:/tmp/nginx-conf/"
ssh "${REMOTE}" '
    bak=/etc/nginx.bak
    sudo rm -rf "${bak}"; sudo cp -a /etc/nginx "${bak}"
    sudo cp /tmp/nginx-conf/nginx.conf /etc/nginx/nginx.conf
    sudo cp /tmp/nginx-conf/distfiles.conf /etc/nginx/conf.d/distfiles.conf
    sudo cp /tmp/nginx-conf/mirror-common.inc /etc/nginx/conf.d/mirror-common.inc
    sudo cp /tmp/nginx-conf/headers-files.inc /etc/nginx/conf.d/headers-files.inc
    sudo cp /tmp/nginx-conf/headers-listing.inc /etc/nginx/conf.d/headers-listing.inc
    sudo cp /tmp/nginx-conf/listing-txt.xsl /etc/nginx/conf.d/listing-txt.xsl
    sudo rm -f /etc/nginx/conf.d/headers-site.inc
    rm -rf /tmp/nginx-conf
    if ! sudo nginx -t; then
        echo "!! 配置不通过，已还原" >&2
        sudo rm -rf /etc/nginx; sudo mv "${bak}" /etc/nginx
        exit 1
    fi
    # A reload parses the new config in the running binary; once emerge has
    # replaced it, that binary keeps the old config, so upgrade instead.
    pid=$(sudo cat /run/nginx/nginx.pid 2>/dev/null || sudo cat /run/nginx.pid 2>/dev/null || true)
    if [ -n "${pid}" ] && sudo readlink "/proc/${pid}/exe" | grep -q " (deleted)$"; then
        sudo rc-service nginx upgrade || { echo "!! nginx 未能换用重新编译的程序" >&2; exit 1; }
    else
        sudo rc-service nginx reload || { echo "!! nginx 未能重新载入配置" >&2; exit 1; }
    fi
    # rc-service returns 0 even when nginx kept the old config, so ask it.
    for _ in 1 2 3 4 5; do
        ct=$(curl -s -o /dev/null -w "%{content_type}" -H "Host: distfiles.gentoozh.org" http://127.0.0.1/distfiles/ || true)
        case "${ct}" in text/plain*) exit 0 ;; esac
        sleep 1
    done
    echo "!! 运行中的 nginx 仍按旧配置响应：curl 取得的 /distfiles/ 是 ${ct:-无响应}" >&2
    exit 1
'
echo ">>> deployed to ${REMOTE}"
