#!/bin/bash
# Push the site and nginx config to the mirror server.
#
# Only ever touches the site's own files: the mirror payload under
# /srv/mirrors/gentoo-zh/ is published separately by build/publish.sh and must
# not be caught by a --delete here.

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
cd "$(dirname "$0")"

# packages.json 不在这里推：它的内容随 overlay 变化，由镜像机每天生成。

# 缓存靠 nginx 发的 Cache-Control: no-cache 加 ETag。这里不再改写样式表地址：
# 平时生效的是 cron 拉取那条路径，它同步的是原始 HTML，两边改写不一致只会
# 让人以为哈希在起作用。
rsync -a --delete site/assets/ "${REMOTE}:/srv/mirrors/assets/"
rsync -a site/*.html site/gentoo-zh-binhost.asc "${REMOTE}:/srv/mirrors/"

rsync -a nginx/ "${REMOTE}:/tmp/nginx-conf/"
# 先备份再覆盖：nginx -t 失败时坏配置已经在盘上了，没有备份就只能手改。
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
