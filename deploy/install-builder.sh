#!/bin/bash
# 把构建这一侧装到构建机上。在本机执行，通过 ssh 作用于目标。
#
#   REMOTE="ssh -i ~/.ssh/gentoobuild -p 49887 user@host" ./deploy/install-builder.sh
#
# 构建机与镜像机分开装：前者要 docker、签名密钥、overlay 副本，
# 后者只要 nginx 与同步脚本，两边没有共用的部分。
#
# 装之前先确认：docker 可用、签名密钥在 SIGNING_GNUPGHOME、
# 能免密 ssh 到镜像机（publish.sh 要往那边推）。

set -euo pipefail

REMOTE="${REMOTE:?用法: REMOTE=\"ssh ...\" $0}"
ROOT="${ROOT:-/var/lib/binhost}"
SIGNING_KEY="${SIGNING_KEY:?需要签名密钥指纹}"
# 构建以谁的身份跑。overlay 副本、docker、到镜像机的 ssh 密钥都要属于它。
BUILD_USER="${BUILD_USER:-adminc3b9c6}"

cd "$(dirname "$0")/.."

say() { printf '\n=== %s ===\n' "$1"; }

say "上传构建脚本"
tmp=$(${REMOTE} 'mktemp -d')
rsync -a -e "${REMOTE% *}" build/ "${REMOTE##* }:${tmp}/"

# shellcheck disable=SC2029  # 路径要在本地展开
${REMOTE} "set -euo pipefail
sudo install -dm755 '${ROOT}' '${ROOT}/logs' '${ROOT}/stage'
sudo rsync -a --delete '${tmp}/' '${ROOT}/build/'
rm -rf '${tmp}'
sudo install -m755 '${ROOT}/build/status.sh' /usr/local/bin/binhost-status

echo '--- overlay 副本'
# 属主要和跑它的用户一致：定时任务以 ${BUILD_USER} 跑，属主是别人时 git 报
# dubious ownership，overlay 更新会一直失败而没有任何迹象
[ -d '${ROOT}/overlay/.git' ] ||
    sudo git clone --quiet https://github.com/gentoo-zh/overlay '${ROOT}/overlay'
sudo chown -R ${BUILD_USER}:${BUILD_USER} '${ROOT}'

echo '--- 告警凭据'
# 构建以 ${BUILD_USER} 执行，凭据为 root 0600 时读取失败，alert() 会一言不发
# 地跳过，整台机器的告警就是哑的。
if sudo test -e /etc/binhost/alert.conf; then
    # 目录也要能进：/etc/binhost 本身为 drwx------ root 时，把文件 chown
    # 过去照样读不到，而 alert() 看到的只是「读不到」
    sudo chmod 755 /etc/binhost
    sudo chown ${BUILD_USER}:${BUILD_USER} /etc/binhost/alert.conf
    sudo chmod 600 /etc/binhost/alert.conf
    sudo -u ${BUILD_USER} test -r /etc/binhost/alert.conf &&
        echo '    ${BUILD_USER} 能读到' ||
        echo '    !! ${BUILD_USER} 仍然读不到，告警会是哑的'
else
    echo '    /etc/binhost/alert.conf 还没有，告警不会发出'
fi
"

say "定时单元"
rsync -a -e "${REMOTE% *}" deploy/systemd/ "${REMOTE##* }:/tmp/systemd/"
${REMOTE} "sudo install -m644 /tmp/systemd/binhost-*.service /tmp/systemd/binhost-*.timer \
    /etc/systemd/system/
rm -rf /tmp/systemd
sudo sed -i -e 's|^Environment=SIGNING_KEY=.*|Environment=SIGNING_KEY=${SIGNING_KEY}|' \
    /etc/systemd/system/binhost-build.service
# 两个单元都跑在构建用户下，属主不一致时 git 与 ssh 都会失败
sudo sed -i -e 's|^User=.*|User=${BUILD_USER}|' -e 's|^Group=.*|Group=${BUILD_USER}|' \
    /etc/systemd/system/binhost-build.service /etc/systemd/system/binhost-status.service
sudo systemctl daemon-reload
sudo systemctl enable --now binhost-build.timer binhost-status.timer
systemctl list-timers --all --no-pager | grep binhost || true"

say "完成"
echo "还要手工配：签名密钥（${ROOT}/gnupg）、到镜像机的免密 ssh、"
echo "告警凭据 /etc/binhost/alert.conf。"
